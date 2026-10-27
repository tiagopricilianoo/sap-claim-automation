# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""REVISOR 4 (TESTADOR), RODADA 2: cotação (correções 12, 16) e migração da tabela cotacoes."""

import sqlite3
from dataclasses import replace

import pytest

from controlador import Executor, resolver_cotacao
from cotacao import CotacaoRequest
from cotacao_service import CotacaoService
from sap_fake import FakeSap
from sap_gateway import StatusMessage
from state import Estado as E
from storage_cotacao import CotacaoStorage


def _req(**kw):
    base = dict(tipo="Nacional", regiao="Sul", cliente="Usina Boa Vista", projeto="Cogeração 2026",
                produto_a=True, produto_b=True)
    base.update(kw)
    return CotacaoRequest.from_form(**base)


def _cfg(settings):
    return replace(settings, automatico_habilitado=True)


def test_rev2_cotacao_service_nao_executa_claim(settings, tmp_path, request_valido):
    db = CotacaoStorage(tmp_path / "d.db")
    svc = CotacaoService(_cfg(settings), FakeSap(), db)
    for chamada in (lambda: svc.executar(request_valido, "AUTOMATICO"), lambda: svc.ensaio(request_valido)):
        with pytest.raises(TypeError):
            chamada()
    db.close()


def test_rev2_fabrica_recebe_o_modo_real_na_cotacao(settings, tmp_path):
    vistos = []

    def fabrica(cfg, modo):
        vistos.append(modo)
        return FakeSap()
    ex = Executor(_cfg(settings), tmp_path / "d.db", fabrica_sap=fabrica)
    ex.iniciar_cotacao(_req(), "SIMULACAO", None)
    ex.aguardar()
    assert vistos == ["SIMULACAO"]


@pytest.mark.parametrize("criada", [True, False])
def test_rev2_cotacao_incerta_resolvida_guarda_linhas(settings, tmp_path, criada):
    db = CotacaoStorage(tmp_path / "d.db")
    svc = CotacaoService(_cfg(settings), FakeSap(status_apos_gravar_cotacao=StatusMessage("", "")), db)
    svc.criar_pastas = lambda *a, **k: tmp_path
    r = svc.executar_cotacao(_req(), "AUTOMATICO", object())
    assert r.estado == E.REVISAO_NECESSARIA
    resolver_cotacao(db, r.cotacao_id, criada=criada, numero="21800001" if criada else "")
    reg = db.obter(r.cotacao_id)
    db.close()
    assert [l["item"] for l in reg.lista_linhas] == ["10", "20"]
    assert reg.estado == (E.CONCLUIDO if criada else E.FALHA_DEFINITIVA)


def test_rev2_cotacao_resolvida_nao_existe_libera_a_proxima(settings, tmp_path):
    db = CotacaoStorage(tmp_path / "d.db")
    svc = CotacaoService(_cfg(settings), FakeSap(status_apos_gravar_cotacao=StatusMessage("", "")), db)
    r = svc.executar_cotacao(_req(), "AUTOMATICO", object())
    resolver_cotacao(db, r.cotacao_id, criada=False)
    sap2 = FakeSap()
    svc2 = CotacaoService(_cfg(settings), sap2, db)
    svc2.criar_pastas = lambda *a, **k: tmp_path
    r2 = svc2.executar_cotacao(_req(), "AUTOMATICO", object())
    db.close()
    assert r2.estado == E.CONCLUIDO


def test_rev2_cotacao_mesmo_projeto_com_acento_e_caixa_diferentes_bloqueia(settings, tmp_path):
    db = CotacaoStorage(tmp_path / "d.db")
    svc = CotacaoService(_cfg(settings), FakeSap(), db)
    svc.criar_pastas = lambda *a, **k: tmp_path
    assert svc.executar_cotacao(_req(), "AUTOMATICO", object()).estado == E.CONCLUIDO
    sap2 = FakeSap()
    r2 = CotacaoService(_cfg(settings), sap2, db).executar_cotacao(
        _req(cliente="USINA  BOA VISTA", projeto="cogeracao 2026", produto_b=False), "AUTOMATICO", object())
    db.close()
    assert sap2.gravacoes == [] and r2.estado == E.RECEBIDO


def test_rev2_banco_de_cotacoes_antigo_sem_colunas_opcionais(tmp_path):
    caminho = tmp_path / "antigo.db"
    con = sqlite3.connect(caminho)
    con.executescript("""
        CREATE TABLE cotacoes (id TEXT PRIMARY KEY, criado_em TEXT NOT NULL, atualizado_em TEXT NOT NULL,
            modo TEXT NOT NULL, tipo TEXT NOT NULL, projeto TEXT NOT NULL, produto_a INTEGER NOT NULL,
            produto_b INTEGER NOT NULL, chave TEXT NOT NULL, estado TEXT NOT NULL);
        INSERT INTO cotacoes VALUES ('C1', '2026-10-20T10:00:00', '2026-10-20T10:00:00', 'AUTOMATICO',
            'Nacional', 'Cogeração 2026', 1, 0, 'Nacional|usina boa vista|cogeracao 2026', 'CONCLUIDO');
    """)
    con.commit()
    con.close()
    db = CotacaoStorage(caminho)
    repetidas = db.duplicidades(_req(produto_b=False))
    reg = db.obter("C1")
    db.close()
    assert [r.id for r in repetidas] == ["C1"] and reg.lista_linhas == []
