# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Linha nova na cotação (VA22) + claim no mesmo clique (opção A, 22/10/2026)."""

from dataclasses import replace

import pytest

from claim_service import ClaimService, cotacao_gravada, etapas_do_modo
from config import ConfigError, load_settings
from models import ClaimRequest
from sap_fake import FakeSap
from sap_gateway import ResultadoIncerto, StatusMessage, ValorRejeitado
from state import Estado as E
from storage import Storage
from validators import validate


@pytest.fixture
def db(tmp_path):
    s = Storage(tmp_path / "h.db")
    yield s
    s.close()


@pytest.fixture
def cfg(settings):
    return replace(settings, automatico_habilitado=True)


@pytest.fixture
def req_linha(request_valido):
    return replace(request_valido, item="", linha_nova=True)


def _servico(settings, db, **fake):
    sap = FakeSap(**fake)
    return ClaimService(settings, sap, db), sap


# ---------------------------------------------------------------- configuração

def test_materiais_e_centros_por_tipo(settings):
    # Confirmado em 22/10/2026: Produto A 10000001 / 1001, Produto B 10000002 / 1002
    assert (settings.rota("PRODUTO_A").material, settings.rota("PRODUTO_A").centro) == ("10000001", "1001")
    for tipo in ("PRODUTO_B", "PRODUTO_B_CUSTO"):
        assert (settings.rota(tipo).material, settings.rota(tipo).centro) == ("10000002", "1002")
    assert settings.linha_quantidade == "1"


def test_material_sem_centro_e_recusado(tmp_path):
    from conftest import texto_settings_padrao
    texto = texto_settings_padrao().replace("centro = 1001\n", "", 1)
    caminho = tmp_path / "s.ini"
    caminho.write_text(texto, encoding="utf-8")
    with pytest.raises(ConfigError, match="material e centro"):
        load_settings(caminho)


# ---------------------------------------------------------------- formulário

def test_item_ignorado_quando_linha_nova():
    req = ClaimRequest.from_form(tipo="PRODUTO_A", descricao="d", texto_livre="t", ordem="1234567",
                                 item="20", arquivo="", sem_anexo=True, linha_nova=True)
    assert req.item == "" and req.linha_nova


def test_validacao_nao_exige_item_com_linha_nova(settings, req_linha):
    assert not [p for p in validate(req_linha, settings) if p.campo == "item"]


def test_validacao_exige_item_sem_linha_nova(settings, req_linha):
    assert [p for p in validate(replace(req_linha, linha_nova=False), settings) if p.campo == "item"]


def test_etapa_da_linha_so_aparece_quando_marcada():
    assert "linha" not in [e for e, _ in etapas_do_modo("AUTOMATICO")]
    etapas = [e for e, _ in etapas_do_modo("AUTOMATICO", linha_nova=True)]
    assert etapas.index("sessao") < etapas.index("linha") < etapas.index("nota")
    assert [e for e, _ in etapas_do_modo("ENSAIO", linha_nova=True)] == ["validacao", "sessao", "linha"]


# ---------------------------------------------------------------- confirmação da VA22

def test_confirmacao_da_cotacao():
    ok = StatusMessage("S", "Cotação 1234567 foi gravado(a)", "V1", "311")
    assert cotacao_gravada(ok, "1234567")
    assert not cotacao_gravada(ok, "21733815")                      # outra cotação
    assert not cotacao_gravada(StatusMessage("W", ok.texto, "V1", "311"), "1234567")
    assert not cotacao_gravada(StatusMessage("S", "Nenhum dado alterado", "V1", "041"), "1234567")


# ---------------------------------------------------------------- fluxo

def test_linha_e_claim_no_mesmo_clique(cfg, db, req_linha):
    servico, sap = _servico(cfg, db, itens_cotacao=["10", "20", "30", "40"])
    r = servico.executar(req_linha, "AUTOMATICO")
    assert r.estado == E.CONCLUIDO and r.linha_criada == "50"
    assert sap.gravacoes[0] == "LINHA 1234567/50"            # a linha é gravada antes de tudo
    assert sap.nota_preenchida["item"] == "50"                 # e o claim vai para o item novo
    assert "Linha 50" in r.mensagem
    execucao = db.obter(r.execucao_id)
    assert (execucao.item, execucao.linha_criada) == ("50", "50")
    assert sap.chamadas.index("gravar_cotacao") < sap.chamadas.index("abrir_criacao")


def test_produto_b_usa_material_e_centro_do_produto_b(cfg, db, req_linha):
    servico, sap = _servico(cfg, db)
    servico.executar(replace(req_linha, tipo="PRODUTO_B_CUSTO"), "AUTOMATICO")
    eventos = [e.detalhe for e in db.eventos(db.recentes(1)[0].id) if e.tipo == "LINHA_PREENCHIDA"]
    assert eventos == ["item 20 · material 10000002 · centro 1002"]


def test_ensaio_da_linha_nao_grava_e_nao_abre_o_claim(cfg, db, req_linha):
    servico, sap = _servico(cfg, db)
    r = servico.executar(req_linha, "ENSAIO")
    assert r.estado == E.ENSAIO_CONCLUIDO and "Nada foi gravado" in r.mensagem
    assert "gravar_cotacao" not in sap.chamadas and "abrir_criacao" not in sap.chamadas
    assert sap.gravacoes == []


def test_centro_errado_na_tela_para_antes_de_gravar(cfg, db, req_linha):
    servico, sap = _servico(cfg, db, linha_lida={"centro": "1001"})
    r = servico.executar(replace(req_linha, tipo="PRODUTO_B"), "AUTOMATICO")
    assert r.estado == E.FALHA_RECUPERAVEL and "centro '1001'" in r.mensagem
    assert "gravar_cotacao" not in sap.chamadas


def test_erro_antes_de_gravar_a_linha_nao_deixa_nada(cfg, db, req_linha):
    servico, sap = _servico(cfg, db, falhar_em={"preencher_linha": ValorRejeitado("Material bloqueado")})
    r = servico.executar(req_linha, "AUTOMATICO")
    assert r.estado == E.FALHA_RECUPERAVEL and "Nada foi gravado" in r.mensagem


def test_gravacao_da_linha_sem_confirmacao_e_revisao(cfg, db, req_linha):
    servico, sap = _servico(cfg, db, status_apos_gravar_cotacao=StatusMessage("", ""))
    r = servico.executar(req_linha, "AUTOMATICO")
    assert r.estado == E.REVISAO_NECESSARIA
    assert "pode ter sido gravada" in r.mensagem and "item 20" in r.mensagem
    assert "abrir_criacao" not in sap.chamadas                # o claim não é tentado


def test_queda_ao_gravar_a_linha_e_revisao(cfg, db, req_linha):
    servico, _ = _servico(cfg, db, falhar_em={"gravar_cotacao": ResultadoIncerto("conexão caiu")})
    assert servico.executar(req_linha, "AUTOMATICO").estado == E.REVISAO_NECESSARIA


def test_falha_no_claim_depois_da_linha_e_revisao_com_o_item(cfg, db, req_linha):
    servico, sap = _servico(cfg, db, falhar_em={"selecionar_atividades": ValorRejeitado("grade estranha")})
    r = servico.executar(req_linha, "AUTOMATICO")
    assert r.estado == E.REVISAO_NECESSARIA and r.linha_criada == "20"
    assert "JÁ FOI GRAVADA" in r.mensagem and "item 20 SEM marcar" in r.mensagem
    assert db.obter(r.execucao_id).item == "20"


def test_nova_linha_bloqueada_enquanto_a_anterior_esta_sem_claim(cfg, db, req_linha):
    servico, _ = _servico(cfg, db, falhar_em={"selecionar_atividades": ValorRejeitado("grade estranha")})
    servico.executar(req_linha, "AUTOMATICO")
    servico2, sap2 = _servico(cfg, db)
    r = servico2.executar(req_linha, "AUTOMATICO")
    assert r.estado == E.RECEBIDO and "item 20" in r.mensagem
    assert sap2.chamadas == []


def test_claim_do_item_criado_e_protegido_contra_duplicidade(cfg, db, req_linha, request_valido):
    servico, _ = _servico(cfg, db)
    servico.executar(req_linha, "AUTOMATICO")                       # cria item 20 + claim
    servico2, sap2 = _servico(cfg, db)
    r = servico2.executar(replace(request_valido, item="20"), "AUTOMATICO")
    assert r.estado == E.RECEBIDO and "Já existe execução" in r.mensagem
    assert sap2.chamadas == []


def test_banco_antigo_ganha_a_coluna(tmp_path):
    import sqlite3
    caminho = tmp_path / "antigo.db"
    from storage import ESQUEMA
    con = sqlite3.connect(caminho)
    con.executescript(ESQUEMA)
    con.close()
    s = Storage(caminho)
    colunas = {l["name"] for l in s._con.execute("PRAGMA table_info(execucoes)")}
    s.close()
    assert "linha_criada" in colunas


def test_aviso_de_condicoes_de_pagamento_aceito(settings):
    # Trava de publicação: sem esta linha no settings.ini, a linha nova para na VA22.
    assert "Entrar Condições pagamento" in settings.avisos_aceitos


def test_linha_com_aviso_aceito_segue(cfg, db, req_linha):
    from sap_gateway import LinhaPreenchida
    servico, sap = _servico(cfg, db)
    original = sap.preencher_linha

    def com_aviso(**k):
        l = original(**k)
        return LinhaPreenchida(l.item, l.material, l.centro, StatusMessage("W", "Entrar Condições pagamento"))
    sap.preencher_linha = com_aviso
    r = servico.executar(req_linha, "AUTOMATICO")
    assert r.estado == E.CONCLUIDO


# ---------------------------------------------------------------- revisão da banca (27/10/2026)

def test_segunda_linha_nova_logo_depois_pede_confirmacao(cfg, db, req_linha):
    servico, _ = _servico(cfg, db)
    assert servico.executar(req_linha, "AUTOMATICO").estado == E.CONCLUIDO
    servico2, sap2 = _servico(cfg, db, itens_cotacao=["10", "20"])
    r = servico2.executar(req_linha, "AUTOMATICO")             # clique repetido por engano
    assert r.estado == E.RECEBIDO and r.confirmar == "linha_extra" and sap2.chamadas == []
    servico3, sap3 = _servico(cfg, db, itens_cotacao=["10", "20"])
    r3 = servico3.executar(replace(req_linha, confirmar_linha_extra=True), "AUTOMATICO")
    assert r3.estado == E.CONCLUIDO and r3.linha_criada == "30"


def test_linha_gravada_sem_zac_libera_o_claim_do_item_e_segura_outra_linha(cfg, db, req_linha):
    sem_anexo = replace(req_linha, arquivo=None, sem_anexo=True)
    servico, _ = _servico(cfg, db, falhar_em={"selecionar_atividades": ValorRejeitado("grade")})
    r = servico.executar(sem_anexo, "AUTOMATICO")
    assert r.estado == E.FALHA_RECUPERAVEL and r.linha_criada == "20" and "SEM marcar" in r.mensagem
    s2, sap2 = _servico(cfg, db, itens_cotacao=["10", "20"])
    r2 = s2.executar(sem_anexo, "AUTOMATICO")                   # outra linha nova: bloqueada
    assert r2.estado == E.RECEBIDO and "item 20" in r2.mensagem and sap2.chamadas == []
    s3, sap3 = _servico(cfg, db, itens_cotacao=["10", "20"])
    r3 = s3.executar(replace(sem_anexo, linha_nova=False, item="20"), "AUTOMATICO")   # o claim do item 20
    assert r3.estado == E.CONCLUIDO and "gravar_cotacao" not in sap3.chamadas
    s4, sap4 = _servico(cfg, db, itens_cotacao=["10", "20"])
    assert s4.executar(sem_anexo, "AUTOMATICO").estado == E.CONCLUIDO    # agora pode outra linha


def test_linha_incerta_resolvida_como_inexistente_libera_linha_nova(cfg, db, req_linha):
    from controlador import resolver_pendencia
    servico, _ = _servico(cfg, db, status_apos_gravar_cotacao=StatusMessage("", ""))
    r = servico.executar(req_linha, "AUTOMATICO")
    assert r.estado == E.REVISAO_NECESSARIA and db.obter(r.execucao_id).linha_criada == "?20"
    resolver_pendencia(db, r.execucao_id, criado=False, linha_existe=False)
    s2, sap2 = _servico(cfg, db)
    assert s2.executar(req_linha, "AUTOMATICO").estado == E.CONCLUIDO and "gravar_cotacao" in sap2.chamadas


def test_linha_incerta_confirmada_vira_item_da_execucao(cfg, db, req_linha):
    from controlador import resolver_pendencia
    servico, _ = _servico(cfg, db, status_apos_gravar_cotacao=StatusMessage("", ""))
    r = servico.executar(req_linha, "AUTOMATICO")
    resolver_pendencia(db, r.execucao_id, criado=False, linha_existe=True)
    ex = db.obter(r.execucao_id)
    assert (ex.linha_criada, ex.item) == ("20", "20")
    s2, sap2 = _servico(cfg, db)
    assert s2.executar(req_linha, "AUTOMATICO").estado == E.RECEBIDO and sap2.chamadas == []
