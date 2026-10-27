# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""REVISOR TESTADOR: máquina de estados, resolução de pendências, storage antigo, filtro."""

import sqlite3
from dataclasses import replace

import pytest

from controlador import filtrar_cotacoes, pendencias, resolver_cotacao, resolver_pendencia
from cotacao import CotacaoRequest
from cotacao_service import CotacaoService
from sap_fake import FakeSap
from sap_gateway import StatusMessage
from state import BLOQUEIAM_DUPLICIDADE, TERMINAIS, TRANSICOES, Estado as E, TransicaoInvalida
from storage import ESQUEMA, Storage
from storage_cotacao import CotacaoStorage


# ------------------------------------------------------------------ state.py

def _alcancaveis(de):
    vistos, pilha = set(), [de]
    while pilha:
        for p in TRANSICOES[pilha.pop()]:
            if p not in vistos:
                vistos.add(p)
                pilha.append(p)
    return vistos


def test_rev_terminais_exatos():
    assert TERMINAIS == {E.CONCLUIDO, E.ENSAIO_CONCLUIDO, E.FALHA_DEFINITIVA}


@pytest.mark.parametrize("de", [E.AGUARDANDO_CONFIRMACAO, E.REVISAO_NECESSARIA, E.CONCLUIDO])
def test_rev_depois_do_envio_nao_volta_a_executar(de):
    assert not {E.PRONTO_PARA_EXECUCAO, E.EXECUTANDO, E.FALHA_RECUPERAVEL} & _alcancaveis(de)


def test_rev_falha_recuperavel_so_vem_de_executando():
    assert [d for d, ps in TRANSICOES.items() if E.FALHA_RECUPERAVEL in ps] == [E.EXECUTANDO]


def test_rev_todo_estado_alcanca_um_terminal():
    for e in E:
        assert e in TERMINAIS or _alcancaveis(e) & TERMINAIS, e


def test_rev_pendentes_bloqueiam_duplicidade():
    assert {E.AGUARDANDO_CONFIRMACAO, E.REVISAO_NECESSARIA, E.EXECUTANDO} <= BLOQUEIAM_DUPLICIDADE


# ------------------------------------------------------------------ resolver_pendencia (claim), todos os estados

def _claim_em(db, req, caminho):
    eid = db.criar_execucao(req, "AUTOMATICO")
    for e in caminho:
        db.transitar(eid, e)
    return eid


CAMINHOS_CLAIM = {
    "PRONTO": (E.VALIDANDO, E.PRONTO_PARA_EXECUCAO),
    "EXECUTANDO": (E.VALIDANDO, E.PRONTO_PARA_EXECUCAO, E.EXECUTANDO),
    "AGUARDANDO": (E.VALIDANDO, E.PRONTO_PARA_EXECUCAO, E.EXECUTANDO, E.AGUARDANDO_CONFIRMACAO),
    "REVISAO": (E.VALIDANDO, E.PRONTO_PARA_EXECUCAO, E.EXECUTANDO, E.REVISAO_NECESSARIA),
}


@pytest.mark.parametrize("nome,criado", [(n, c) for n in CAMINHOS_CLAIM for c in (True, False)])
def test_rev_resolver_claim_em_todo_estado_pendente(tmp_path, request_valido, nome, criado):
    db = Storage(tmp_path / "r.db")
    eid = _claim_em(db, request_valido, CAMINHOS_CLAIM[nome])
    assert eid in [e.id for e in pendencias(db)]                 # aparece na aba Pendências
    try:
        resolver_pendencia(db, eid, criado=criado, numero_nota="100065700")
        ex = db.obter(eid)
    finally:
        db.close()
    assert ex.estado == (E.CONCLUIDO if criado else E.FALHA_DEFINITIVA)


def test_rev_resolver_claim_que_falha_nao_deixa_meio_gravado(tmp_path, request_valido):
    """Se a resolução não puder ser aplicada, nada pode mudar (nem nota, nem estado)."""
    db = Storage(tmp_path / "r.db")
    eid = _claim_em(db, request_valido, CAMINHOS_CLAIM["PRONTO"])
    try:
        resolver_pendencia(db, eid, criado=True, numero_nota="100065700")
    except Exception:  # noqa: BLE001
        pass
    ex = db.obter(eid)
    db.close()
    assert ex.estado == E.CONCLUIDO or (ex.estado == E.PRONTO_PARA_EXECUCAO and ex.numero_nota is None), \
        f"estado {ex.estado.value}, nota {ex.numero_nota!r}"


# ------------------------------------------------------------------ resolver_cotacao, todos os estados

def _creq():
    return CotacaoRequest.from_form(tipo="Nacional", regiao="Sul", cliente="Usina", projeto="P1", produto_a=True)


CAMINHOS_COT = {
    "EXECUTANDO": (E.VALIDANDO, E.PRONTO_PARA_EXECUCAO, E.EXECUTANDO),
    "AGUARDANDO": (E.VALIDANDO, E.PRONTO_PARA_EXECUCAO, E.EXECUTANDO, E.AGUARDANDO_CONFIRMACAO),
    "REVISAO": (E.VALIDANDO, E.PRONTO_PARA_EXECUCAO, E.EXECUTANDO, E.AGUARDANDO_CONFIRMACAO,
                E.REVISAO_NECESSARIA),
}


@pytest.mark.parametrize("nome,criada", [(n, c) for n in CAMINHOS_COT for c in (True, False)])
def test_rev_resolver_cotacao_em_todo_estado_pendente(tmp_path, nome, criada):
    db = CotacaoStorage(tmp_path / "c.db")
    cid = db.criar(_creq(), "AUTOMATICO")
    for e in CAMINHOS_COT[nome]:
        db.transitar(cid, e)
    assert cid in [c.id for c in db.pendentes()]
    try:
        resolver_cotacao(db, cid, criada=criada, numero="21800009")
        reg = db.obter(cid)
    finally:
        db.close()
    assert reg.estado == (E.CONCLUIDO if criada else E.FALHA_DEFINITIVA)


def test_rev_cotacao_incerta_resolvida_guarda_as_linhas_para_o_claim(settings, tmp_path):
    """Depois de 'cotação existe', o botão 'Criar claim' precisa das linhas (item/rota)."""
    cfg = replace(settings, automatico_habilitado=True)
    db = CotacaoStorage(tmp_path / "c.db")
    s = CotacaoService(cfg, FakeSap(status_apos_gravar_cotacao=StatusMessage("", "")), db)
    from pastas import PlanoPastas
    plano = PlanoPastas("TU", tmp_path / "R.0", None, tmp_path, tmp_path, 2026)
    r = s.executar_cotacao(_creq(), "AUTOMATICO", plano)
    assert r.estado == E.REVISAO_NECESSARIA and r.linhas            # a execução sabia as linhas
    resolver_cotacao(db, r.cotacao_id, criada=True, numero="21800009")
    reg = db.obter(r.cotacao_id)
    db.close()
    assert reg.lista_linhas, "linhas perdidas: 'Criar claim' da cotação resolvida fica impossível"


# ------------------------------------------------------------------ storage com banco antigo

def _banco_antigo(caminho, request_valido):
    con = sqlite3.connect(caminho)
    con.executescript(ESQUEMA)                    # 1ª versão: sem linha_criada
    con.execute("INSERT INTO execucoes (id, criado_em, atualizado_em, modo, tipo, ordem, item, estado, numero_nota) "
                "VALUES ('ANTIGO1', '2026-10-01T10:00:00', '2026-10-01T10:00:00', 'AUTOMATICO', 'PRODUTO_A', "
                "?, ?, 'CONCLUIDO', '423000001')", (request_valido.ordem, request_valido.item))
    con.execute("INSERT INTO execucoes (id, criado_em, atualizado_em, modo, tipo, ordem, item, estado) "
                "VALUES ('ANTIGO2', '2026-10-02T10:00:00', '2026-10-02T10:00:00', 'AUTOMATICO', 'PRODUTO_A', "
                "'99', '10', 'REVISAO_NECESSARIA')")
    con.commit()
    con.close()


def test_rev_banco_antigo_com_dados_continua_protegendo(tmp_path, request_valido):
    caminho = tmp_path / "antigo.db"
    _banco_antigo(caminho, request_valido)
    db = Storage(caminho)
    try:
        assert db.obter("ANTIGO1").linha_criada is None
        assert [e.id for e in db.possiveis_duplicidades(request_valido.ordem, request_valido.item)] == ["ANTIGO1"]
        assert [e.id for e in db.pendentes()] == ["ANTIGO2"]
        assert db.linhas_sem_claim("99") == []
        resolver_pendencia(db, "ANTIGO2", criado=True, numero_nota="1")
        assert len(db.recentes()) == 2
    finally:
        db.close()


def test_rev_banco_antigo_aberto_duas_vezes(tmp_path, request_valido):
    """Interface e thread abrem o banco: a migração não pode quebrar a segunda abertura."""
    caminho = tmp_path / "antigo.db"
    _banco_antigo(caminho, request_valido)
    a, b = Storage(caminho), Storage(caminho)
    a.close()
    b.close()


def test_rev_banco_de_claims_ganha_tabela_de_cotacoes(tmp_path, request_valido):
    caminho = tmp_path / "antigo.db"
    _banco_antigo(caminho, request_valido)
    c = CotacaoStorage(caminho)
    assert c.recentes() == [] and c.pendentes() == []
    c.close()
    s = Storage(caminho)
    assert s.obter("ANTIGO1").numero_nota == "423000001"
    s.close()


# ------------------------------------------------------------------ filtrar_cotacoes

def test_rev_filtro_com_campos_none(tmp_path):
    db = CotacaoStorage(tmp_path / "c.db")
    especial = CotacaoRequest.from_form(tipo="Cliente Especial", projeto="K-77", produto_a=True)
    db.criar(especial, "SIMULACAO")                          # cliente "", numero None
    regs = db.recentes()
    db.close()
    assert filtrar_cotacoes(regs, "k-77") == regs
    assert filtrar_cotacoes(regs, "especial") == regs
    assert filtrar_cotacoes(regs, "nada") == []


def test_rev_filtro_com_texto_none(tmp_path):
    db = CotacaoStorage(tmp_path / "c.db")
    db.criar(_creq(), "SIMULACAO")
    regs = db.recentes()
    db.close()
    assert filtrar_cotacoes(regs, None) == regs


def test_rev_filtro_so_espacos_e_acentos():
    class R:
        cliente, projeto, numero, pais, regiao, tipo = "Açúcar Exemplo", "Caldeira", None, None, "Sul", "Nacional"
    assert filtrar_cotacoes([R], "   ") == [R]
    assert filtrar_cotacoes([R], "AÇUCAR") == [R]
