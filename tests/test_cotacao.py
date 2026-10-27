# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Cotação nova (VA21) unificada: regras, plano, pastas e serviço (sem SAP, sem rede)."""

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from config import CotacaoConfig
from cotacao import CotacaoRequest, planejar, resumo_plano, validar_cotacao
from cotacao_service import CotacaoService, etapas_cotacao_do_modo, numero_cotacao
from pastas import ProjetoJaExiste, criar_pastas, planejar_pastas
from sap_fake import FakeSap
from sap_gateway import ElementoNaoEncontrado, ResultadoIncerto, StatusMessage
from state import Estado as E
from storage_cotacao import CotacaoStorage


def _req(**kw):
    base = dict(tipo="Nacional", regiao="Sul", pais="", cliente="Usina Boa Vista", projeto="Cogeração 2026",
                produto_a=True, produto_b=False)
    base.update(kw)
    return CotacaoRequest.from_form(**base)


# ---------------------------------------------------------------- configuração e regras

def test_valores_do_programa_anterior(settings):
    c = settings.cotacao
    assert (c.tipo_documento, c.organizacao, c.canal, c.escritorio) == ("ZQT1", "1000", "30", "X001")
    n, e, k = c.tipos["Nacional"], c.tipos["Exportação"], c.tipos["Cliente Especial"]
    assert (n.setor, n.emissor, n.utilizacao, n.equipe_produto_a, n.equipe_produto_b) == ("20", "CLIENTE X", "003", "E10", "E11")
    assert (e.setor, e.emissor, e.utilizacao, e.equipe_produto_a, e.codigo_postal) == ("80", "CLIENTE Y", "004", "E12", "1")
    assert (k.equipe_produto_a, k.nome_cliente_fixo, k.pede_cliente) == ("E14", "cliente", False)


def test_produto_a_e_produto_b_juntos_uma_cotacao_duas_linhas(settings):
    plano = planejar(_req(produto_b=True), settings, hoje=date(2026, 10, 26))
    assert plano.principal == "TU" and plano.equipe == "E10"
    assert [(l.equipamento, l.material, l.centro) for l in plano.linhas] == [
        ("Produto A", "10000001", "1001"), ("Produto B", "10000002", "1002")]
    assert plano.validade == date(2027, 10, 26)


def test_so_produto_b_usa_equipe_do_produto_b(settings):
    plano = planejar(_req(produto_a=False, produto_b=True), settings)
    assert plano.principal == "TR" and plano.equipe == "E11" and len(plano.linhas) == 1


def test_endereco_e_referencia_cortados_como_antes(settings):
    plano = planejar(_req(cliente="Companhia Energética Muito Grande", projeto="Projeto Expansão Fase Dois"),
                     settings)
    assert plano.cidade == "Projeto Expansã" and plano.nome_endereco == "Companhia Energética Muito Grande"
    assert plano.referencia == "Companhia Energ - Projeto Expansã"


def test_especial_sem_cliente(settings):
    req = CotacaoRequest.from_form(tipo="Cliente Especial", cliente="ignorado", projeto="K-77", produto_a=True)
    assert validar_cotacao(req, settings) == []
    plano = planejar(req, settings)
    assert (req.regiao, req.pais, req.cliente, plano.nome_endereco, plano.equipe) == (
        "Europa", "Cliente Especial", "", "cliente", "E14")


def test_validacoes(settings):
    campos = lambda r: {p.campo for p in validar_cotacao(r, settings)}
    assert campos(_req(regiao="")) == {"regiao"}
    assert campos(_req(tipo="Exportação", regiao="Europa", pais="")) == {"pais"}
    assert campos(_req(tipo="Exportação", regiao="Europa", pais="Alemanha")) == set()
    assert campos(_req(cliente='A/B')) == {"cliente"}
    assert campos(_req(projeto="x" * 51)) == {"projeto"}
    assert campos(_req(produto_a=False)) == {"equipamentos"}
    assert campos(_req(cliente="CON")) == {"cliente"}


def test_resumo_mostra_o_que_sera_criado(settings):
    texto = "\n".join(resumo_plano(planejar(_req(produto_b=True), settings), settings))
    assert "ZQT1" in texto and "equipe E10" in texto and "Linha 20: Produto B · material 10000002 · centro 1002" in texto


def test_numero_da_cotacao():
    assert numero_cotacao(StatusMessage("S", "Cotação 21800001 foi gravado(a)", "V1", "311")) == "21800001"
    assert numero_cotacao(StatusMessage("W", "Cotação 21800001 foi gravado(a)", "V1", "311")) == ""
    assert numero_cotacao(StatusMessage("S", "Nenhum dado foi alterado", "V1", "041")) == ""


# ---------------------------------------------------------------- pastas

def _cfg_rede(settings, tmp_path) -> CotacaoConfig:
    tu, tr = tmp_path / "TU", tmp_path / "TR"
    (tu / "PLANILHA DE CUSTO").mkdir(parents=True, exist_ok=True)
    (tu / "PLANILHA DE CUSTO" / "FPV_TU.xlsm").write_bytes(b"x")
    (tu / "Padrão de Propostas").mkdir(exist_ok=True)
    (tu / "Padrão de Propostas" / "Proposta.xlsm").write_bytes(b"x")
    (tr / "PLANILHA DE CUSTO").mkdir(parents=True, exist_ok=True)
    (tr / "PLANILHA DE CUSTO" / "FPV_TR.xlsm").write_bytes(b"x")
    return replace(settings.cotacao, raiz_produto_a=str(tu), raiz_produto_b=str(tr))


def test_pastas_produto_a_nacional(settings, tmp_path):
    cfg = _cfg_rede(settings, tmp_path)
    atalhos = []
    plano = planejar_pastas(_req(), cfg, perguntar=lambda *a: False, ano=2026)
    assert plano.base == tmp_path / "TU" / "Propostas_2026" / "Brasil" / "Sul" / "Usina Boa Vista" / "Cogeração 2026" / "R.0"
    base = criar_pastas(plano, "21800001", criar_atalho=lambda arq, alvo: atalhos.append((arq.name, alvo)))
    assert (base / "Propostas" / "Numero cotação 21800001.txt").exists()
    assert (base / "Custos" / "FPV_TU.xlsm").exists() and (base / "Propostas" / "Proposta.xlsm").exists()
    assert (base.parent / "R.X" / "Claim" / "Nº da Claim.txt").exists()
    assert ("Proposta AT.lnk", str(tmp_path / "TU" / "Aplicacao" / "Proposta AT")) in atalhos


def test_pastas_produto_b_exportacao(settings, tmp_path):
    cfg = _cfg_rede(settings, tmp_path)
    atalhos = []
    req = _req(tipo="Exportação", regiao="Europa", pais="Alemanha", produto_a=False, produto_b=True)
    plano = planejar_pastas(req, cfg, perguntar=lambda *a: False, ano=2026)
    assert plano.base.parts[-6:] == ("Exportação", "Europa", "Alemanha", "Usina Boa Vista", "Cogeração 2026", "R.0")
    assert "Propostas - 2026" in str(plano.base)
    base = criar_pastas(plano, "21800002", criar_atalho=lambda arq, alvo: atalhos.append(arq.name))
    assert (base / "Custos" / "FPV_TR.xlsm").exists()
    assert sorted(atalhos) == ["Modelos de Propostas.lnk", "Proposta AT.lnk"]


def test_projeto_que_ja_tem_pasta_para_antes_do_sap(settings, tmp_path):
    cfg = _cfg_rede(settings, tmp_path)
    (tmp_path / "TU" / "Propostas_2026" / "Brasil" / "Sul" / "Usina Boa Vista" / "Cogeracao 2026").mkdir(parents=True, exist_ok=True)
    with pytest.raises(ProjetoJaExiste):
        planejar_pastas(_req(), cfg, perguntar=lambda *a: False, ano=2026)


def test_cliente_parecido_pergunta(settings, tmp_path):
    cfg = _cfg_rede(settings, tmp_path)
    (tmp_path / "TU" / "Propostas_2026" / "Brasil" / "Sul" / "Usina Boa Vista S.A").mkdir(parents=True, exist_ok=True)
    perguntas = []
    plano = planejar_pastas(_req(), cfg, perguntar=lambda t, x: perguntas.append(t) or True, ano=2026)
    assert perguntas == ["Cliente parecido encontrado"]
    assert "Usina Boa Vista S.A" in str(plano.base)


def test_especial_pastas(settings, tmp_path):
    cfg = _cfg_rede(settings, tmp_path)
    req = CotacaoRequest.from_form(tipo="Cliente Especial", projeto="K-77", produto_a=True)
    plano = planejar_pastas(req, cfg, perguntar=lambda *a: False, ano=2026)
    base = criar_pastas(plano, "21800003", criar_atalho=lambda *a: None)
    assert base.parts[-5:] == ("Exportação", "Europa", "Cliente Especial", "K-77", "R.0")
    assert (base / "FPV" / "FPV_TU.xlsm").exists()


# ---------------------------------------------------------------- serviço

@pytest.fixture
def db(tmp_path):
    s = CotacaoStorage(tmp_path / "h.db")
    yield s
    s.close()


@pytest.fixture
def cfg(settings):
    return replace(settings, automatico_habilitado=True)


def _servico(settings, db, **fake):
    sap = FakeSap(**fake)
    return CotacaoService(settings, sap, db), sap


def _plano_pastas(cfg, tmp_path, req):
    return planejar_pastas(req, _cfg_rede(cfg, tmp_path), perguntar=lambda *a: False, ano=2026)


def test_cotacao_completa_com_duas_linhas_e_pastas(cfg, db, tmp_path):
    req = _req(produto_b=True)
    servico, sap = _servico(cfg, db)
    servico.criar_pastas = lambda plano, numero: plano.base
    r = servico.executar_cotacao(req, "AUTOMATICO", _plano_pastas(cfg, tmp_path, req))
    assert r.estado == E.CONCLUIDO and r.numero == "21800001"
    assert [(l["item"], l["equipamento"], l["rota"]) for l in r.linhas] == [
        ("10", "Produto A", "PRODUTO_A"), ("20", "Produto B", "PRODUTO_B")]
    assert sap.cotacao_dados["equipe"] == "E10" and sap.cotacao_dados["setor"] == "20"
    assert sap.cotacao_linhas == [("10000001", "1001", "1"), ("10000002", "1002", "1")]
    assert r.pasta.endswith("R.0") and db.obter(r.cotacao_id).numero == "21800001"


def test_ensaio_nao_grava_nem_cria_pastas(cfg, db, tmp_path):
    servico, sap = _servico(cfg, db)
    r = servico.executar_cotacao(_req(), "ENSAIO", None)
    assert r.estado == E.ENSAIO_CONCLUIDO and "gravar_cotacao_nova" not in sap.chamadas and sap.gravacoes == []
    assert [e for e, _ in etapas_cotacao_do_modo("ENSAIO")][-1] == "cabecalho"


def test_exportacao_confirma_a_janela_extra(cfg, db):
    servico, sap = _servico(cfg, db,
                            janela_exportacao="Endereço de dds.mestre para o Emissor da ordem ( CabeçDoc. )")
    r = servico.executar_cotacao(_req(tipo="Exportação", regiao="Europa", pais="Alemanha"), "ENSAIO", None)
    assert r.estado == E.ENSAIO_CONCLUIDO and "confirmar_popup" in sap.chamadas
    assert sap.cotacao_cliente["codigo_postal"] == "1"


def test_centro_errado_para_antes_de_gravar(cfg, db, tmp_path):
    req = _req()
    servico, sap = _servico(cfg, db, linha_lida={"centro": "1002"})
    r = servico.executar_cotacao(req, "AUTOMATICO", _plano_pastas(cfg, tmp_path, req))
    assert r.estado == E.FALHA_RECUPERAVEL and "Nada foi gravado" in r.mensagem
    assert "gravar_cotacao_nova" not in sap.chamadas


def test_sem_acesso_ao_tipo_e_falha_definitiva(cfg, db):
    servico, _ = _servico(cfg, db, falhar_em={"iniciar_cotacao": ElementoNaoEncontrado("sem emissor")})
    assert servico.executar_cotacao(_req(), "ENSAIO", None).estado == E.FALHA_DEFINITIVA


def test_gravacao_sem_confirmacao_e_revisao_e_sem_pastas(cfg, db, tmp_path):
    criadas = []
    req = _req()
    servico, _ = _servico(cfg, db, status_apos_gravar_cotacao=StatusMessage("", ""))
    servico.criar_pastas = lambda *a: criadas.append(a)
    r = servico.executar_cotacao(req, "AUTOMATICO", _plano_pastas(cfg, tmp_path, req))
    assert r.estado == E.REVISAO_NECESSARIA and "NÃO crie de novo" in r.mensagem and criadas == []


def test_queda_ao_gravar_e_revisao(cfg, db, tmp_path):
    req = _req()
    servico, _ = _servico(cfg, db, falhar_em={"gravar_cotacao_nova": ResultadoIncerto("caiu")})
    assert servico.executar_cotacao(req, "AUTOMATICO", _plano_pastas(cfg, tmp_path, req)).estado == E.REVISAO_NECESSARIA


def test_pastas_que_falham_nao_desfazem_a_cotacao(cfg, db, tmp_path):
    def quebra(*a):
        raise PermissionError("acesso negado à rede")
    req = _req()
    servico, _ = _servico(cfg, db)
    servico.criar_pastas = quebra
    r = servico.executar_cotacao(req, "AUTOMATICO", _plano_pastas(cfg, tmp_path, req))
    assert r.estado == E.CONCLUIDO and r.numero and "acesso negado" in r.aviso_pastas


def test_mesmo_projeto_duas_vezes_e_bloqueado(cfg, db, tmp_path):
    req = _req()
    servico, _ = _servico(cfg, db)
    servico.criar_pastas = lambda plano, numero: plano.base
    servico.executar_cotacao(req, "AUTOMATICO", _plano_pastas(cfg, tmp_path, req))
    servico2, sap2 = _servico(cfg, db)
    r = servico2.executar_cotacao(req, "AUTOMATICO", _plano_pastas(cfg, tmp_path, req))
    assert r.estado == E.RECEBIDO and "Já existe cotação" in r.mensagem and sap2.chamadas == []


def test_criar_exige_pastas_conferidas(cfg, db):
    servico, sap = _servico(cfg, db)
    r = servico.executar_cotacao(_req(), "AUTOMATICO", None)
    assert r.estado == E.RECEBIDO and sap.chamadas == []


def test_gravacao_desabilitada(settings, db):
    servico, _ = _servico(settings, db)
    with pytest.raises(ValueError):
        servico.executar_cotacao(_req(), "AUTOMATICO", None)


# ---------------------------------------------------------------- controlador

def test_executor_roda_a_cotacao_em_segundo_plano(cfg, tmp_path):
    from controlador import Executor
    sap = FakeSap()
    executor = Executor(cfg, tmp_path / "h.db", fabrica_sap=lambda s, m: sap)
    executor.iniciar_cotacao(_req(produto_b=True), "ENSAIO", None)
    executor.aguardar(10)
    eventos = executor.drenar()
    fim = [e for e in eventos if e.tipo == "fim"]
    assert fim and fim[0].origem == "cotacao" and fim[0].resultado.estado == E.ENSAIO_CONCLUIDO
    assert all(e.origem == "cotacao" for e in eventos)


def test_resolver_cotacao_pendente(cfg, db, tmp_path):
    from controlador import linha_cotacao, resolver_cotacao
    req = _req()
    servico, _ = _servico(cfg, db, status_apos_gravar_cotacao=StatusMessage("", ""))
    r = servico.executar_cotacao(req, "AUTOMATICO", _plano_pastas(cfg, tmp_path, req))
    assert [c.id for c in db.pendentes()] == [r.cotacao_id]
    with pytest.raises(ValueError):
        resolver_cotacao(db, r.cotacao_id, criada=True, numero="abc")
    resolver_cotacao(db, r.cotacao_id, criada=True, numero="21800009")
    registro = db.obter(r.cotacao_id)
    assert registro.estado == E.CONCLUIDO and registro.numero == "21800009" and db.pendentes() == []
    assert linha_cotacao(registro)[1:4] == ("Usina Boa Vista", "Cogeração 2026", "21800009")


def test_modo_assistido_nao_existe_para_cotacao(cfg):
    from controlador import modos_cotacao_da_interface
    assert modos_cotacao_da_interface(cfg) == ("SIMULACAO", "ENSAIO", "AUTOMATICO")


def test_rede_inacessivel_para_antes_do_sap(settings, tmp_path):
    cfg = replace(settings.cotacao, raiz_produto_a=str(tmp_path / "nao_existe"), raiz_produto_b=str(tmp_path / "x"))
    with pytest.raises(OSError, match="não está acessível"):
        planejar_pastas(_req(), cfg, perguntar=lambda *a: False, ano=2026)


def test_filtro_por_cliente_enquanto_digita(cfg, db):
    from controlador import filtrar_cotacoes
    servico, _ = _servico(cfg, db)
    servico.executar_cotacao(_req(cliente="Usina Boa Vista", projeto="Cogeração"), "SIMULACAO", None)
    servico.executar_cotacao(_req(cliente="Açúcar Exemplo", projeto="Caldeira 3"), "SIMULACAO", None)
    todos = db.recentes()
    assert [c.cliente for c in filtrar_cotacoes(todos, "exem")] == ["Açúcar Exemplo"]
    assert [c.cliente for c in filtrar_cotacoes(todos, "acucar cald")] == ["Açúcar Exemplo"]   # sem acento, 2 palavras
    assert len(filtrar_cotacoes(todos, "")) == 2
    assert filtrar_cotacoes(todos, "21800001")                                              # pelo número


def test_exportacao_com_janela_desconhecida_para_antes_de_gravar(cfg, db):
    servico, sap = _servico(cfg, db, janela_exportacao="Bloqueio de crédito do cliente")
    r = servico.executar_cotacao(_req(tipo="Exportação", regiao="Europa", pais="Alemanha"), "ENSAIO", None)
    assert r.estado == E.FALHA_RECUPERAVEL and "confirmar_popup" not in sap.chamadas
