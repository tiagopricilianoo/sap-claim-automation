# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""REVISOR 4 (TESTADOR), RODADA 2: ataque às correções de duplicidade, linha nova e resolução."""

from dataclasses import replace

import pytest

from claim_service import ClaimService
from controlador import pendencias, resolver_pendencia
from models import ClaimRequest, normalizar_numero
from sap_fake import FakeSap
from sap_gateway import ResultadoIncerto, StatusMessage, ValorRejeitado
from state import Estado as E
from storage import Storage


def _cfg(settings):
    return replace(settings, automatico_habilitado=True)


def _rodar(cfg, db, req, modo="AUTOMATICO", **fake):
    sap = FakeSap(**fake)
    return ClaimService(cfg, sap, db).executar(req, modo), sap


def _linha(req):
    return replace(req, item="", linha_nova=True)


def _forcar(db, req, modo, caminho, **campos):
    eid = db.criar_execucao(req, modo)
    for e in caminho:
        db.transitar(eid, e)
    if campos:
        db._atualizar(eid, **campos)
    return eid


ATE_EXEC = (E.VALIDANDO, E.PRONTO_PARA_EXECUCAO, E.EXECUTANDO)


# ------------------------------------------------------------------ normalização (correção 1)

@pytest.mark.parametrize("valor,esperado", [
    ("010", "10"), ("000", "0"), ("0", "0"), ("", ""), ("10", "10"),
    ("０１０", "０１０"),          # dígito largo: não é ASCII, fica como está (a validação recusa)
    ("٠١٠", "٠١٠"),              # dígitos arábicos idem
])
def test_rev2_normalizar_numero_bordas(valor, esperado):
    assert normalizar_numero(valor) == esperado


@pytest.mark.parametrize("ordem", ["​1234567", "1234567​", "2173 3814", "1234567﻿"])
def test_rev2_caractere_invisivel_na_ordem_e_recusado(settings, arquivo_pdf, ordem):
    from validators import validate
    req = ClaimRequest.from_form(tipo="PRODUTO_A", descricao="d", texto_livre="t", ordem=ordem, item="10",
                                 arquivo=str(arquivo_pdf))
    assert any(p.campo == "ordem" for p in validate(req, settings))


def test_rev2_item_zero_e_aceito_pela_validacao(settings, arquivo_pdf):
    """'0' / '000' vira item 0 (cabeçalho no SAP, POSNR 000000) e passa na validação."""
    from validators import validate
    req = ClaimRequest.from_form(tipo="PRODUTO_A", descricao="d", texto_livre="t", ordem="1234567", item="000",
                                 arquivo=str(arquivo_pdf))
    assert req.item == "0"
    assert [p for p in validate(req, settings) if p.campo == "item"], "item 0 aceito como item de cotação"


def test_rev2_item_zero_colide_com_linha_nova_em_andamento(tmp_path, request_valido):
    """ltrim('0','0') = '' : o item 0 'enxerga' execuções de linha nova (item vazio) como duplicidade."""
    db = Storage(tmp_path / "d.db")
    _forcar(db, _linha(request_valido), "AUTOMATICO", ATE_EXEC)
    achadas = db.possiveis_duplicidades("1234567", "0", modo="AUTOMATICO")
    db.close()
    assert achadas == [], f"item 0 bloqueado por execução de linha nova sem item: {[a.id for a in achadas]}"


@pytest.mark.parametrize("item_sap", ["20", "020", "000020"])
def test_rev2_item_da_linha_lido_com_zeros_continua_protegido(settings, tmp_path, request_valido, item_sap):
    """A VA22 pode devolver o item com zeros (POSNR NUMC 6): a proteção tem que valer igual."""
    cfg = _cfg(settings)
    db = Storage(tmp_path / "d.db")
    sap = FakeSap(falhar_em={"selecionar_atividades": ValorRejeitado("grade")})
    original = sap.preencher_linha

    def preencher(**kw):
        l = original(**kw)
        sap._linha_pendente = item_sap
        return replace(l, item=item_sap)
    sap.preencher_linha = preencher
    r1 = ClaimService(cfg, sap, db).executar(_linha(request_valido), "AUTOMATICO")
    assert r1.estado == E.REVISAO_NECESSARIA
    # mesma ordem/item "20" digitado pelo usuário: tem que bloquear (o ZDC/claim do item pode existir)
    r2, sap2 = _rodar(cfg, db, replace(request_valido, item="20"))
    # outra linha nova: tem que bloquear (linha 20 sem claim)
    r3, sap3 = _rodar(cfg, db, _linha(request_valido), itens_cotacao=["10", "20"])
    db.close()
    assert sap2.gravacoes == [] and r2.estado == E.RECEBIDO
    assert "gravar_cotacao" not in sap3.chamadas


# ------------------------------------------------------------------ linha nova repetida (correção 2)

def test_rev2_segunda_linha_nova_pede_confirmacao_e_confirmada_grava(settings, tmp_path, request_valido):
    cfg = _cfg(settings)
    db = Storage(tmp_path / "d.db")
    r1, _ = _rodar(cfg, db, _linha(request_valido))
    assert r1.estado == E.CONCLUIDO
    r2, sap2 = _rodar(cfg, db, _linha(request_valido), itens_cotacao=["10", "20"])
    assert r2.confirmar == "linha_extra" and sap2.gravacoes == []
    r3, sap3 = _rodar(cfg, db, replace(_linha(request_valido), confirmar_linha_extra=True),
                      itens_cotacao=["10", "20"])
    db.close()
    assert r3.estado == E.CONCLUIDO and len([g for g in sap3.gravacoes if g.startswith("LINHA")]) == 1


def test_rev2_linha_nova_repetida_com_ordem_com_zeros(settings, tmp_path, request_valido):
    cfg = _cfg(settings)
    db = Storage(tmp_path / "d.db")
    _rodar(cfg, db, _linha(request_valido))
    r2, sap2 = _rodar(cfg, db, replace(_linha(request_valido), ordem="001234567"), itens_cotacao=["10", "20"])
    db.close()
    assert sap2.gravacoes == [] and r2.confirmar == "linha_extra"


def test_rev2_linha_nova_resolvida_concluida_tambem_pede_confirmacao(settings, tmp_path, request_valido):
    """Linha nova que terminou em revisão e foi resolvida 'claim criado': clique repetido logo depois."""
    cfg = _cfg(settings)
    db = Storage(tmp_path / "d.db")
    r1, _ = _rodar(cfg, db, _linha(request_valido), status_apos_gravar=StatusMessage("", ""))
    assert r1.estado == E.REVISAO_NECESSARIA and r1.linha_criada == "20"
    resolver_pendencia(db, r1.execucao_id, criado=True, numero_nota="100063949")
    r2, sap2 = _rodar(cfg, db, _linha(request_valido), itens_cotacao=["10", "20"])
    db.close()
    assert sap2.gravacoes == [] and r2.confirmar == "linha_extra"


def test_rev2_ensaio_e_simulacao_nao_disparam_confirmacao_de_linha_real(settings, tmp_path, request_valido):
    cfg = _cfg(settings)
    db = Storage(tmp_path / "d.db")
    _rodar(cfg, db, _linha(request_valido), modo="SIMULACAO")
    _rodar(cfg, db, _linha(request_valido), modo="ENSAIO")
    r, sap = _rodar(cfg, db, _linha(request_valido))
    db.close()
    assert r.estado == E.CONCLUIDO and r.confirmar == ""


# ------------------------------------------------------------------ recuperação da linha nova (correção 3)

def test_rev2_linha_confirmada_sem_zac_libera_claim_do_item_e_bloqueia_outra_linha(settings, tmp_path,
                                                                                   request_valido):
    cfg = _cfg(settings)
    db = Storage(tmp_path / "d.db")
    r1, _ = _rodar(cfg, db, _linha(request_valido), falhar_em={"abrir_criacao": ValorRejeitado("CLM1")})
    assert r1.estado == E.FALHA_RECUPERAVEL and r1.linha_criada == "20"
    r_linha, sap_linha = _rodar(cfg, db, _linha(request_valido), itens_cotacao=["10", "20"])
    assert "gravar_cotacao" not in sap_linha.chamadas
    r_claim, _ = _rodar(cfg, db, replace(request_valido, item="20"))       # a orientação dada ao usuário
    assert r_claim.estado == E.CONCLUIDO
    r_dup, sap_dup = _rodar(cfg, db, replace(request_valido, item="020"))
    db.close()
    assert sap_dup.gravacoes == []


def test_rev2_linha_incerta_criado_sem_responder_a_linha_perde_a_protecao(settings, tmp_path, request_valido):
    """resolver_pendencia(criado=True) numa linha '?20' sem linha_existe: o claim fica com item vazio e o
    item 20 deixa de ser protegido contra outro claim."""
    cfg = _cfg(settings)
    db = Storage(tmp_path / "d.db")
    r1, _ = _rodar(cfg, db, _linha(request_valido), status_apos_gravar_cotacao=StatusMessage("", ""))
    assert r1.estado == E.REVISAO_NECESSARIA and r1.linha_criada == "?20"
    resolver_pendencia(db, r1.execucao_id, criado=True, numero_nota="100063949")   # linha_existe omitido
    r2, sap2 = _rodar(cfg, db, replace(request_valido, item="20"))
    db.close()
    assert sap2.gravacoes == [], f"segundo claim para o item 20: {sap2.gravacoes}"


def test_rev2_linha_incerta_resposta_contraditoria_e_aceita(tmp_path, request_valido):
    """'A linha NÃO existe' + 'o claim foi criado' é contraditório e deveria ser recusado."""
    db = Storage(tmp_path / "d.db")
    eid = _forcar(db, _linha(request_valido), "AUTOMATICO", ATE_EXEC + (E.REVISAO_NECESSARIA,),
                  linha_criada="?20")
    with pytest.raises(ValueError):
        resolver_pendencia(db, eid, criado=True, numero_nota="1", linha_existe=False)
    db.close()


@pytest.mark.parametrize("linha_existe,bloqueia", [(None, True), (True, True), (False, False)])
def test_rev2_linha_incerta_nao_criado_respeita_resposta_da_linha(settings, tmp_path, request_valido,
                                                                  linha_existe, bloqueia):
    cfg = _cfg(settings)
    db = Storage(tmp_path / "d.db")
    r1, _ = _rodar(cfg, db, _linha(request_valido), status_apos_gravar_cotacao=StatusMessage("", ""))
    resolver_pendencia(db, r1.execucao_id, criado=False, linha_existe=linha_existe)
    r2, sap2 = _rodar(cfg, db, _linha(request_valido))
    db.close()
    assert ("gravar_cotacao" not in sap2.chamadas) == bloqueia


def test_rev2_claim_simulado_desbloqueia_linha_real_sem_claim(settings, tmp_path, request_valido):
    """O 'NOT EXISTS ... CONCLUIDO' de linhas_sem_claim não filtra o modo: um claim SIMULADO do item 20
    apaga o bloqueio da linha 20 REAL, e outra linha real é gravada na VA22."""
    cfg = _cfg(settings)
    db = Storage(tmp_path / "d.db")
    r1, _ = _rodar(cfg, db, _linha(request_valido), falhar_em={"abrir_criacao": ValorRejeitado("CLM1")})
    assert r1.estado == E.FALHA_RECUPERAVEL and r1.linha_criada == "20"
    rs, _ = _rodar(cfg, db, replace(request_valido, item="20"), modo="SIMULACAO")
    assert rs.estado == E.CONCLUIDO
    r2, sap2 = _rodar(cfg, db, _linha(request_valido), itens_cotacao=["10", "20"])
    db.close()
    assert "gravar_cotacao" not in sap2.chamadas, f"linha real duplicada: {sap2.gravacoes}"


def test_rev2_claim_simulado_nao_bloqueia_claim_real(settings, tmp_path, request_valido):
    cfg = _cfg(settings)
    db = Storage(tmp_path / "d.db")
    _rodar(cfg, db, request_valido, modo="SIMULACAO")
    r, _ = _rodar(cfg, db, request_valido)
    r3, sap3 = _rodar(cfg, db, request_valido)
    db.close()
    assert r.estado == E.CONCLUIDO
    assert sap3.gravacoes == []          # o claim REAL bloqueia o seguinte


# ------------------------------------------------------------------ interrupção (correção 17)

def _parar_em(etapa_alvo):
    import threading
    ev = threading.Event()

    def progresso(etapa, situacao, detalhe):
        if etapa == etapa_alvo and situacao == "ok":
            ev.set()
    return ev, progresso


@pytest.mark.parametrize("parar_apos,linha_nova,estado_esperado", [
    ("processamento", False, E.FALHA_RECUPERAVEL),     # nada gravado (com anexo, o ZDC já foi): ver abaixo
    ("linha", True, E.FALHA_RECUPERAVEL),
    ("sessao", True, E.FALHA_RECUPERAVEL),
])
def test_rev2_parar_sem_nada_gravado_e_falha_comum(settings, tmp_path, request_valido, parar_apos, linha_nova,
                                                   estado_esperado):
    cfg = _cfg(settings)
    db = Storage(tmp_path / "d.db")
    ev, progresso = _parar_em(parar_apos)
    req = replace(_linha(request_valido) if linha_nova else request_valido, sem_anexo=True, arquivo=None)
    r = ClaimService(cfg, FakeSap(), db, progresso=progresso, cancelar=ev).executar(req, "AUTOMATICO")
    db.close()
    assert r.estado == estado_esperado, (r.estado, r.mensagem)
    if linha_nova and parar_apos == "linha":
        assert "FOI GRAVADA" in r.mensagem and r.linha_criada == "20"
    else:
        assert "Nada foi gravado" in r.mensagem


def test_rev2_parar_depois_do_zac_continua_revisao(settings, tmp_path, request_valido):
    cfg = _cfg(settings)
    db = Storage(tmp_path / "d.db")
    ev, progresso = _parar_em("documento")
    r = ClaimService(cfg, FakeSap(), db, progresso=progresso, cancelar=ev).executar(request_valido, "AUTOMATICO")
    r2, sap2 = _rodar(cfg, db, request_valido)
    db.close()
    assert r.estado == E.REVISAO_NECESSARIA and r.documento_dms
    assert sap2.gravacoes == []


# ------------------------------------------------------------------ resolver (correção 4)

_NAO_PENDENTES = [
    (),                                  # RECEBIDO
    (E.VALIDANDO,),
    ATE_EXEC + (E.FALHA_RECUPERAVEL,),
    ATE_EXEC + (E.FALHA_DEFINITIVA,),
    ATE_EXEC + (E.ENSAIO_CONCLUIDO,),
    ATE_EXEC + (E.AGUARDANDO_CONFIRMACAO, E.CONCLUIDO),
]


@pytest.mark.parametrize("caminho,criado", [(c, k) for c in _NAO_PENDENTES for k in (True, False)])
def test_rev2_resolver_estado_nao_pendente_recusa_sem_mudar_nada(tmp_path, request_valido, caminho, criado):
    db = Storage(tmp_path / "d.db")
    eid = _forcar(db, request_valido, "AUTOMATICO", caminho)
    antes = (db.obter(eid), len(db.eventos(eid)))
    with pytest.raises(ValueError):
        resolver_pendencia(db, eid, criado=criado, numero_nota="1")
    depois = (db.obter(eid), len(db.eventos(eid)))
    db.close()
    assert antes == depois


@pytest.mark.parametrize("numero", ["", " ", "12a", "１２", "-1", "1.0", None])
def test_rev2_resolver_criado_com_numero_invalido_nao_muda_nada(tmp_path, request_valido, numero):
    db = Storage(tmp_path / "d.db")
    eid = _forcar(db, request_valido, "AUTOMATICO", ATE_EXEC + (E.REVISAO_NECESSARIA,))
    n = len(db.eventos(eid))
    with pytest.raises((ValueError, AttributeError)):
        resolver_pendencia(db, eid, criado=True, numero_nota=numero)
    assert db.obter(eid).estado == E.REVISAO_NECESSARIA and len(db.eventos(eid)) == n
    db.close()


def test_rev2_resolver_linha_incerta_com_falha_no_meio_nao_deixa_meio_gravado(tmp_path, request_valido):
    """definir_linha grava ANTES das transições, fora de uma transação única: se a transição falhar
    (ex.: banco travado / outra conexão mudou o estado), a linha já foi alterada."""
    db = Storage(tmp_path / "d.db")
    eid = _forcar(db, _linha(request_valido), "AUTOMATICO", ATE_EXEC + (E.REVISAO_NECESSARIA,),
                  linha_criada="?20")
    original = db.transitar

    def transitar_falha(*a, **k):
        raise RuntimeError("database is locked")
    db.transitar = transitar_falha
    with pytest.raises(RuntimeError):
        resolver_pendencia(db, eid, criado=False, linha_existe=False)
    db.transitar = original
    ex = db.obter(eid)
    db.close()
    assert ex.linha_criada == "?20", f"linha apagada sem a resolução ter sido gravada: {ex.linha_criada!r}"


def test_rev2_pendencias_nao_inclui_falha_recuperavel_com_linha(settings, tmp_path, request_valido):
    """A linha gravada sem claim (FALHA_RECUPERAVEL) não aparece em Pendências: só a mensagem orienta."""
    cfg = _cfg(settings)
    db = Storage(tmp_path / "d.db")
    r1, _ = _rodar(cfg, db, _linha(request_valido), falhar_em={"abrir_criacao": ValorRejeitado("CLM1")})
    ids = [e.id for e in pendencias(db)]
    db.close()
    assert r1.execucao_id not in ids     # informativo: comportamento escolhido pelo desenvolvedor


# ------------------------------------------------------------------ banco antigo + correções

def test_rev2_banco_antigo_com_item_e_ordem_com_zeros_bloqueia(tmp_path, request_valido, settings):
    """Registro gravado pela versão de 26/10 (sem normalização): '01234567'/'010' CONCLUIDO."""
    import sqlite3
    caminho = tmp_path / "antigo.db"
    db = Storage(caminho)
    eid = _forcar(db, replace(request_valido, ordem="01234567", item="010"), "AUTOMATICO",
                  ATE_EXEC + (E.AGUARDANDO_CONFIRMACAO, E.CONCLUIDO))
    db.close()
    con = sqlite3.connect(caminho)
    con.execute("UPDATE execucoes SET ordem='01234567', item='010' WHERE id=?", (eid,))
    con.commit()
    con.close()
    db = Storage(caminho)
    r, sap = _rodar(_cfg(settings), db, request_valido)
    db.close()
    assert sap.gravacoes == [] and r.estado == E.RECEBIDO
