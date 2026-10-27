# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""REVISOR TESTADOR: 'nunca gravar duas vezes' (claim, linha nova, cotação)."""

from dataclasses import replace

import pytest

from claim_service import ClaimService
from controlador import resolver_pendencia
from cotacao import CotacaoRequest
from cotacao_service import CotacaoService
from pastas import ProjetoJaExiste, planejar_pastas
from sap_fake import FakeSap
from sap_gateway import ElementoNaoEncontrado, ResultadoIncerto, SapError, StatusMessage, ValorRejeitado
from state import Estado as E
from storage import Storage
from storage_cotacao import CotacaoStorage


def _cfg(settings):
    return replace(settings, automatico_habilitado=True)


def _rodar(cfg, db, req, modo="AUTOMATICO", **fake):
    sap = FakeSap(**fake)
    return ClaimService(cfg, sap, db).executar(req, modo), sap


# ------------------------------------------------------------------ claim: chave ordem/item

@pytest.mark.parametrize("ordem2,item2", [
    ("1234567", "010"),        # item com zero à esquerda (SAP: NUMC 6 -> 000010)
    ("1234567", "000010"),
    ("01234567", "10"),        # ordem com zero à esquerda (SAP: ALPHA -> 001234567)
    ("001234567", "000010"),
])
def test_rev_mesma_ordem_item_com_zeros_nao_grava_segundo_claim(settings, tmp_path, request_valido, ordem2, item2):
    cfg = _cfg(settings)
    db = Storage(tmp_path / "d.db")
    r1, _ = _rodar(cfg, db, request_valido)
    assert r1.estado == E.CONCLUIDO
    r2, sap2 = _rodar(cfg, db, replace(request_valido, ordem=ordem2, item=item2))
    db.close()
    assert sap2.gravacoes == [], f"2º claim gravado para {ordem2}/{item2}: {sap2.gravacoes}"
    assert r2.estado == E.RECEBIDO


def test_rev_falha_recuperavel_nao_bloqueia_nova_tentativa(settings, tmp_path, request_valido):
    cfg = _cfg(settings)
    db = Storage(tmp_path / "d.db")
    r1, _ = _rodar(cfg, db, request_valido, sessao_info=None)
    assert r1.estado == E.FALHA_RECUPERAVEL
    r2, _ = _rodar(cfg, db, request_valido)
    db.close()
    assert r2.estado == E.CONCLUIDO


def test_rev_assistido_bloqueia_completo_da_mesma_ordem(settings, tmp_path, request_valido):
    cfg = _cfg(settings)
    db = Storage(tmp_path / "d.db")
    r1, _ = _rodar(cfg, db, request_valido, modo="ASSISTIDO")
    assert r1.estado == E.REVISAO_NECESSARIA
    r2, sap2 = _rodar(cfg, db, request_valido)
    db.close()
    assert r2.estado == E.RECEBIDO and sap2.chamadas == []


def test_rev_execucao_travada_em_executando_bloqueia(settings, tmp_path, request_valido):
    """Programa fechado no meio (estado EXECUTANDO): pode ter gravado o documento."""
    cfg = _cfg(settings)
    db = Storage(tmp_path / "d.db")
    eid = db.criar_execucao(request_valido, "AUTOMATICO")
    for e in (E.VALIDANDO, E.PRONTO_PARA_EXECUCAO, E.EXECUTANDO):
        db.transitar(eid, e)
    r2, sap2 = _rodar(cfg, db, request_valido)
    db.close()
    assert r2.estado == E.RECEBIDO and sap2.chamadas == []


# ------------------------------------------------------------------ propriedade: falha em qualquer chamada

METODOS = ["sessao", "abrir_cotacao", "preencher_linha", "gravar_cotacao", "abrir_criacao", "preencher_nota",
           "enter", "confirmar_popup", "criar_documento", "selecionar_atividades", "por_em_processamento",
           "gravar_nota", "encerrar"]
ERROS = [SapError("x"), ValorRejeitado("x"), ElementoNaoEncontrado("x"), ResultadoIncerto("x"), RuntimeError("x")]
CASOS = [(m, e, linha) for m in METODOS for e in ERROS for linha in (False, True)]


@pytest.mark.parametrize("metodo,erro,linha_nova", CASOS)
def test_rev_falha_em_qualquer_ponto_nunca_grava_duas_vezes(settings, tmp_path, request_valido, metodo, erro,
                                                            linha_nova):
    cfg = _cfg(settings)
    db = Storage(tmp_path / "d.db")
    req = replace(request_valido, item="", linha_nova=True) if linha_nova else request_valido
    r, sap = _rodar(cfg, db, req, falhar_em={metodo: erro},
                    popups_apos_enter=["O cliente X tem bloqueio de registro"])
    tipos = [g.split()[0] for g in sap.gravacoes]
    assert all(tipos.count(t) <= 1 for t in set(tipos)), sap.gravacoes
    # O que pode ter sido gravado (enviado) define o estado mínimo
    # Enviado = algo gravado, ou um comando de gravação que falhou sem confirmação.
    # (criar_documento com erro comum = falha ANTES do Ctrl+S no SAP real: nada enviado.)
    enviados = bool(sap.gravacoes) or metodo in ("gravar_cotacao", "gravar_nota") or \
        (metodo == "criar_documento" and isinstance(erro, ResultadoIncerto))
    # Só a LINHA confirmada gravada (nada do claim enviado): falha comum com a linha registrada
    # (correção de 27/10: o claim do item pode ser criado; nova "linha nova" fica bloqueada).
    so_linha = bool(sap.gravacoes) and all(g.startswith("LINHA") for g in sap.gravacoes) and \
        metodo != "gravar_nota" and not (metodo == "criar_documento" and isinstance(erro, ResultadoIncerto))
    if so_linha:
        assert r.estado == E.FALHA_RECUPERAVEL and r.linha_criada and not r.linha_criada.startswith("?"), \
            (metodo, r.estado, r.mensagem)
    elif enviados:
        assert r.estado in (E.CONCLUIDO, E.REVISAO_NECESSARIA), (metodo, r.estado, r.mensagem)
    else:
        assert r.estado in (E.FALHA_RECUPERAVEL, E.FALHA_DEFINITIVA), (metodo, r.estado, r.mensagem)
    # Uma 2ª execução igual não pode gravar o claim de novo se algo foi enviado
    if enviados and not linha_nova:
        r2, sap2 = _rodar(cfg, db, req)
        assert sap2.gravacoes == [], (metodo, sap2.gravacoes)
    # ...nem outra linha na cotação se uma linha foi (ou pode ter sido) gravada
    if linha_nova and (any(g.startswith("LINHA") for g in sap.gravacoes) or metodo == "gravar_cotacao"):
        r3, sap3 = _rodar(cfg, db, req)
        assert "gravar_cotacao" not in sap3.chamadas, (metodo, sap3.gravacoes)
    db.close()


# ------------------------------------------------------------------ linha nova

def test_rev_linha_incerta_resolvida_como_claim_inexistente_nao_libera_outra_linha(settings, tmp_path,
                                                                                   request_valido):
    """A linha '?20' pode existir na VA22; dizer 'o claim não existe' não diz nada sobre a linha."""
    cfg = _cfg(settings)
    db = Storage(tmp_path / "d.db")
    req = replace(request_valido, item="", linha_nova=True)
    r1, _ = _rodar(cfg, db, req, status_apos_gravar_cotacao=StatusMessage("", ""))
    assert r1.estado == E.REVISAO_NECESSARIA
    resolver_pendencia(db, r1.execucao_id, criado=False)      # o claim de fato não existe
    r2, sap2 = _rodar(cfg, db, req)
    db.close()
    assert "gravar_cotacao" not in sap2.chamadas, \
        f"uma 2ª linha foi gravada na cotação: {sap2.gravacoes}"


def test_rev_linha_gravada_e_claim_falho_resolvido_nao_libera_outra_linha(settings, tmp_path, request_valido):
    cfg = _cfg(settings)
    db = Storage(tmp_path / "d.db")
    req = replace(request_valido, item="", linha_nova=True)
    r1, _ = _rodar(cfg, db, req, falhar_em={"selecionar_atividades": ValorRejeitado("grade")})
    assert r1.estado == E.REVISAO_NECESSARIA and r1.linha_criada == "20"
    resolver_pendencia(db, r1.execucao_id, criado=False)
    r2, sap2 = _rodar(cfg, db, req, itens_cotacao=["10", "20"])
    db.close()
    assert "gravar_cotacao" not in sap2.chamadas, f"linha 20 já existe e outra foi gravada: {sap2.gravacoes}"


# ------------------------------------------------------------------ cotação

def _req(**kw):
    base = dict(tipo="Nacional", regiao="Sul", cliente="Usina Boa Vista", projeto="Cogeração 2026",
                produto_a=True, produto_b=False)
    base.update(kw)
    return CotacaoRequest.from_form(**base)


def _rede(settings, tmp_path):
    tu, tr = tmp_path / "TU", tmp_path / "TR"
    tu.mkdir(exist_ok=True)
    tr.mkdir(exist_ok=True)
    return replace(settings.cotacao, raiz_produto_a=str(tu), raiz_produto_b=str(tr))


def _cot(cfg, db, req, plano, **fake):
    sap = FakeSap(**fake)
    s = CotacaoService(cfg, sap, db)
    s.criar_pastas = lambda p, n: p.base
    return s.executar_cotacao(req, "AUTOMATICO", plano), sap


def test_rev_cotacao_incerta_bloqueia_a_segunda(settings, tmp_path):
    cfg = _cfg(settings)
    db = CotacaoStorage(tmp_path / "c.db")
    plano = planejar_pastas(_req(), _rede(settings, tmp_path), perguntar=lambda *a: False, ano=2026)
    r1, _ = _cot(cfg, db, _req(), plano, falhar_em={"gravar_cotacao_nova": ResultadoIncerto("caiu")})
    assert r1.estado == E.REVISAO_NECESSARIA
    r2, sap2 = _cot(cfg, db, _req(cliente="USINA  boa vista", projeto="Cogeracao 2026"), plano)
    db.close()
    assert r2.estado == E.RECEBIDO and sap2.chamadas == []


def test_rev_cotacao_falha_antes_de_gravar_libera(settings, tmp_path):
    cfg = _cfg(settings)
    db = CotacaoStorage(tmp_path / "c.db")
    plano = planejar_pastas(_req(), _rede(settings, tmp_path), perguntar=lambda *a: False, ano=2026)
    r1, _ = _cot(cfg, db, _req(), plano, sessao_info=None)
    assert r1.estado == E.FALHA_RECUPERAVEL
    r2, _ = _cot(cfg, db, _req(), plano)
    db.close()
    assert r2.estado == E.CONCLUIDO


def test_rev_especial_projeto_que_ja_tem_pasta_para_antes_do_sap(settings, tmp_path):
    """Para Nacional/Exportação a pasta existente bloqueia (proteção entre colegas). Especial também deveria."""
    cfg = _rede(settings, tmp_path)
    (tmp_path / "TU" / "Propostas_2026" / "Exportação" / "Europa" / "Cliente Especial" / "K-77" / "R.0").mkdir(parents=True)
    req = CotacaoRequest.from_form(tipo="Cliente Especial", projeto="K-77", produto_a=True)
    with pytest.raises(ProjetoJaExiste):
        planejar_pastas(req, cfg, perguntar=lambda *a: False, ano=2026)


@pytest.mark.parametrize("metodo", ["sessao", "iniciar_cotacao", "preencher_cliente", "preencher_validade",
                                    "preencher_linhas_novas", "preencher_cabecalho", "gravar_cotacao_nova",
                                    "encerrar"])
def test_rev_cotacao_falha_em_qualquer_ponto(settings, tmp_path, metodo):
    cfg = _cfg(settings)
    db = CotacaoStorage(tmp_path / "c.db")
    plano = planejar_pastas(_req(), _rede(settings, tmp_path), perguntar=lambda *a: False, ano=2026)
    r, sap = _cot(cfg, db, _req(), plano, falhar_em={metodo: RuntimeError("x")})
    assert len(sap.gravacoes) <= 1
    if "gravar_cotacao_nova" in sap.chamadas:
        assert r.estado in (E.CONCLUIDO, E.REVISAO_NECESSARIA)
    else:
        assert r.estado in (E.FALHA_RECUPERAVEL, E.FALHA_DEFINITIVA)
    r2, sap2 = _cot(cfg, db, _req(), plano)
    db.close()
    if "gravar_cotacao_nova" in sap.chamadas:
        assert sap2.gravacoes == []
