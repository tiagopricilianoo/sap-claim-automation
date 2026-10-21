# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
import pytest

from claim_service import ClaimService
from models import ClaimRequest
from sap_fake import FakeSap
from sap_gateway import ElementoNaoEncontrado, SessaoIndisponivel, SessionInfo, StatusMessage
from state import Estado as E
from storage import Storage


@pytest.fixture
def db(tmp_path):
    s = Storage(tmp_path / "h.db")
    yield s
    s.close()


def _servico(settings, db, **fake):
    sap = FakeSap(**fake)
    return ClaimService(settings, sap, db), sap


def test_ensaio_feliz_nao_grava_nada(settings, db, request_valido):
    servico, sap = _servico(settings, db, popups_apos_enter=["O cliente CLIENTE X tem bloqueio de registro"])
    r = servico.ensaio(request_valido)
    assert r.estado == E.ENSAIO_CONCLUIDO
    assert r.avisos == ["O cliente CLIENTE X tem bloqueio de registro"]
    assert sap.gravacoes == []
    assert "criar_documento" not in sap.chamadas and "gravar_nota" not in sap.chamadas
    tipos = [e.tipo for e in db.eventos(r.execucao_id)]
    assert "AVISO_ACEITO" in tipos
    assert db.obter(r.execucao_id).sap_usuario == "USUARIO1"


def test_dados_invalidos_nem_tocam_no_sap(settings, db):
    servico, sap = _servico(settings, db)
    req = ClaimRequest.from_form(tipo="", descricao="", texto_livre="", ordem="x", item="", arquivo="")
    r = servico.ensaio(req)
    assert r.estado == E.RECEBIDO and r.problemas
    assert sap.chamadas == []


def test_janela_desconhecida_para_sem_confirmar(settings, db, request_valido):
    servico, sap = _servico(settings, db, popups_apos_enter=["Pedido bloqueado para faturamento"])
    r = servico.ensaio(request_valido)
    assert r.estado == E.FALHA_RECUPERAVEL
    assert "confirmar_popup" not in sap.chamadas
    assert "JANELA_DESCONHECIDA" in [e.tipo for e in db.eventos(r.execucao_id)]


def test_erro_na_barra_de_status(settings, db, request_valido):
    servico, _ = _servico(settings, db, status_apos_enter=StatusMessage("E", "Ordem 1234567 não existe"))
    r = servico.ensaio(request_valido)
    assert r.estado == E.FALHA_RECUPERAVEL and "não existe" in r.mensagem


def test_aviso_w_desconhecido_para(settings, db, request_valido):
    servico, _ = _servico(settings, db, status_apos_enter=StatusMessage("W", "Data no passado"))
    assert servico.ensaio(request_valido).estado == E.FALHA_RECUPERAVEL


def test_sucesso_s_na_barra_continua(settings, db, request_valido):
    servico, _ = _servico(settings, db, status_apos_enter=StatusMessage("S", "Dados verificados"))
    assert servico.ensaio(request_valido).estado == E.ENSAIO_CONCLUIDO


def test_campo_nao_encontrado_e_definitivo(settings, db, request_valido):
    servico, _ = _servico(settings, db, falhar_em={"preencher_nota": ElementoNaoEncontrado("x", etapa="descrição")})
    r = servico.ensaio(request_valido)
    assert r.estado == E.FALHA_DEFINITIVA
    assert db.obter(r.execucao_id).etapa_falha == "descrição"


def test_sap_fechado_e_recuperavel(settings, db, request_valido):
    servico, _ = _servico(settings, db, sessao_info=None)
    assert servico.ensaio(request_valido).estado == E.FALHA_RECUPERAVEL


def test_sistema_errado_bloqueia(settings, db, request_valido):
    outra = SessionInfo("EQ0", "100", "USUARIO1", "PT", "SESSION_MANAGER", False)
    servico, sap = _servico(settings, db, sessao_info=outra)
    assert servico.ensaio(request_valido).estado == E.FALHA_RECUPERAVEL
    assert "abrir_criacao" not in sap.chamadas


def test_ensaio_inclui_atividades_da_rota(settings, db, request_valido):
    from dataclasses import replace
    req = replace(request_valido, tipo="PRODUTO_B_CUSTO")
    servico, sap = _servico(settings, db)
    r = servico.ensaio(req)
    assert r.estado == E.ENSAIO_CONCLUIDO
    assert [a.no for a in sap.atividades_recebidas] == ["000000000660", "000000000683", "000000000687", "000000000689", "000000000648"]
    assert [a.responsavel for a in sap.atividades_recebidas] == ["", "USUARIO_IND", "USUARIO_SUP", "USUARIO_CUS", "USUARIO1"]
    assert len(r.grade) == 5 and r.conferencias == []
    assert sap.gravacoes == [] and "criar_documento" not in sap.chamadas


def test_texto_diferente_na_grade_vira_conferencia(settings, db, request_valido):
    grade = [{"DESC_ATIV": "ANALISE TECNICA", "SUB_GRUPO": "GRP-ENG", "RESP": "GRP"},
             {"DESC_ATIV": "PRODUTO A", "SUB_GRUPO": "GRP-COM", "RESP": "OUTRO"}]
    servico, _ = _servico(settings, db, grade=grade)
    r = servico.ensaio(request_valido)
    assert r.estado == E.ENSAIO_CONCLUIDO
    assert r.conferencias == ["Linha 2: responsável 'USUARIO1' não encontrado na grade"]


def test_grade_com_linhas_a_menos_e_erro(settings, db, request_valido):
    servico, _ = _servico(settings, db, grade=[{"DESC_ATIV": "ANALISE TECNICA"}])
    assert servico.ensaio(request_valido).estado == E.FALHA_RECUPERAVEL


def test_ensaio_repetido_so_registra_aviso(settings, db, request_valido):
    servico, _ = _servico(settings, db)
    servico.ensaio(request_valido)
    r = servico.ensaio(request_valido)
    assert r.estado == E.ENSAIO_CONCLUIDO


# ====================================================================== Entrega 6: modos que gravam

from dataclasses import replace  # noqa: E402

from sap_gateway import ResultadoIncerto  # noqa: E402


@pytest.fixture
def cfg_gravacao(settings):
    return replace(settings, automatico_habilitado=True)


def test_gravacao_desabilitada_por_padrao(settings, db, request_valido):
    servico, sap = _servico(settings, db)
    for modo in ("ASSISTIDO", "AUTOMATICO"):
        with pytest.raises(ValueError, match="automatico_habilitado"):
            servico.executar(request_valido, modo)
    assert sap.chamadas == []


def test_automatico_feliz(cfg_gravacao, db, request_valido):
    servico, sap = _servico(cfg_gravacao, db)
    r = servico.executar(request_valido, "AUTOMATICO")
    assert r.estado == E.CONCLUIDO
    assert (r.documento_dms, r.numero_nota) == ("20000263669", "100063949")
    assert sap.gravacoes == ["DOCUMENTO ZDC 20000263669", "NOTA 100063949"]
    assert sap.chamadas.count("gravar_nota") == 1 and sap.chamadas[-1] == "encerrar"
    ex = db.obter(r.execucao_id)
    assert (ex.documento_dms, ex.numero_nota, ex.estado) == ("20000263669", "100063949", E.CONCLUIDO)


def test_ordem_das_etapas_no_sap(cfg_gravacao, db, request_valido):
    servico, sap = _servico(cfg_gravacao, db)
    servico.executar(request_valido, "AUTOMATICO")
    passos = ("enter", "criar_documento", "selecionar_atividades", "por_em_processamento", "gravar_nota")
    ordem = [c for c in sap.chamadas if c in passos]
    assert ordem == list(passos)


def test_assistido_para_antes_de_gravar_o_claim(cfg_gravacao, db, request_valido):
    servico, sap = _servico(cfg_gravacao, db)
    r = servico.executar(request_valido, "ASSISTIDO")
    assert r.estado == E.REVISAO_NECESSARIA and r.documento_dms == "20000263669"
    assert "gravar_nota" not in sap.chamadas and "encerrar" not in sap.chamadas
    assert sap.gravacoes == ["DOCUMENTO ZDC 20000263669"]


def test_queda_na_gravacao_vira_revisao_e_nao_repete(cfg_gravacao, db, request_valido):
    servico, sap = _servico(cfg_gravacao, db, falhar_em={"gravar_nota": ResultadoIncerto("conexão caiu")})
    r = servico.executar(request_valido, "AUTOMATICO")
    assert r.estado == E.REVISAO_NECESSARIA
    assert sap.chamadas.count("gravar_nota") == 1
    assert "NÃO crie de novo" in r.mensagem and "20000263669" in r.mensagem
    transicoes = [e.para_estado for e in db.eventos(r.execucao_id) if e.tipo == "TRANSICAO"]
    assert transicoes[-2:] == ["AGUARDANDO_CONFIRMACAO", "REVISAO_NECESSARIA"]


def test_resposta_sem_numero_vira_revisao(cfg_gravacao, db, request_valido):
    servico, _ = _servico(cfg_gravacao, db, status_apos_gravar=StatusMessage("S", "Dados gravados"))
    assert servico.executar(request_valido, "AUTOMATICO").estado == E.REVISAO_NECESSARIA


def test_erro_na_gravacao_vira_revisao(cfg_gravacao, db, request_valido):
    servico, _ = _servico(cfg_gravacao, db, status_apos_gravar=StatusMessage("E", "Campo obrigatório"))
    assert servico.executar(request_valido, "AUTOMATICO").estado == E.REVISAO_NECESSARIA


def test_falha_nas_atividades_depois_do_documento_e_revisao(cfg_gravacao, db, request_valido):
    servico, sap = _servico(cfg_gravacao, db,
                            falhar_em={"selecionar_atividades": ElementoNaoEncontrado("nó", etapa="árvore")})
    r = servico.executar(request_valido, "AUTOMATICO")
    assert r.estado == E.REVISAO_NECESSARIA
    assert db.obter(r.execucao_id).documento_dms == "20000263669"
    assert "gravar_nota" not in sap.chamadas


def test_documento_incerto_e_revisao(cfg_gravacao, db, request_valido):
    servico, sap = _servico(cfg_gravacao, db,
                            falhar_em={"criar_documento": ResultadoIncerto("sem resposta", etapa="gravar documento")})
    r = servico.executar(request_valido, "AUTOMATICO")
    assert r.estado == E.REVISAO_NECESSARIA and "possivelmente criado" in r.mensagem


def test_falha_no_documento_antes_de_gravar_nao_e_revisao(cfg_gravacao, db, request_valido):
    servico, _ = _servico(cfg_gravacao, db,
                          falhar_em={"criar_documento": ElementoNaoEncontrado("DY_PATH", etapa="pasta do arquivo")})
    assert servico.executar(request_valido, "AUTOMATICO").estado == E.FALHA_DEFINITIVA


def test_duplicidade_bloqueia_modo_que_grava(cfg_gravacao, db, request_valido):
    servico, _ = _servico(cfg_gravacao, db)
    assert servico.executar(request_valido, "AUTOMATICO").estado == E.CONCLUIDO
    servico2, sap2 = _servico(cfg_gravacao, db)
    r = servico2.executar(request_valido, "AUTOMATICO")
    assert r.estado == E.RECEBIDO and "100063949" in r.mensagem
    assert sap2.chamadas == []


def test_interromper_antes_de_gravar_nao_grava(cfg_gravacao, db, request_valido):
    import threading
    parar = threading.Event()

    class SapQueParaNasAtividades(FakeSap):
        def selecionar_atividades(self, atividades, raiz):
            linhas = super().selecionar_atividades(atividades, raiz)
            parar.set()                 # usuário clica em Interromper durante as atividades
            return linhas

    sap = SapQueParaNasAtividades()
    r = ClaimService(cfg_gravacao, sap, db, cancelar=parar).executar(request_valido, "AUTOMATICO")
    assert r.estado == E.REVISAO_NECESSARIA and "Interrompido" in r.mensagem
    assert "gravar_nota" not in sap.chamadas


def test_simulacao_faz_o_fluxo_completo_sem_habilitar(settings, db, request_valido):
    servico, sap = _servico(settings, db)
    r = servico.executar(request_valido, "SIMULACAO")
    assert r.estado == E.CONCLUIDO and "criar_documento" in sap.chamadas


def test_conferencia_divergente_bloqueia_gravacao(cfg_gravacao, db, request_valido):
    grade = [{"DS_ATIVIDADE": "ITEM AUXILIAR 2", "SUB_GRUPO": "GRP-ENG", "RESP": "GRUPO-ENG"},
             {"DS_ATIVIDADE": "PRODUTO A", "SUB_GRUPO": "GRP-COM", "RESP": "USUARIO1"}]
    servico, sap = _servico(cfg_gravacao, db, grade=grade)
    r = servico.executar(request_valido, "AUTOMATICO")
    assert r.estado == E.REVISAO_NECESSARIA           # documento ZDC já existia
    assert "gravar_nota" not in sap.chamadas


def test_processamento_em_todos_os_modos(cfg_gravacao, db, request_valido):
    for modo in ("ENSAIO", "ASSISTIDO"):
        servico, sap = _servico(cfg_gravacao, db)
        servico.executar(replace(request_valido, item=str(len(modo))), modo)
        assert sap.chamadas.count("por_em_processamento") == 1, modo
        assert "gravar_nota" not in sap.chamadas


def test_falha_na_bandeira_nao_grava_o_claim(cfg_gravacao, db, request_valido):
    from sap_gateway import ValorRejeitado
    servico, sap = _servico(cfg_gravacao, db,
                            falhar_em={"por_em_processamento": ValorRejeitado("bloqueado", etapa="pôr em processamento")})
    r = servico.executar(request_valido, "AUTOMATICO")
    assert r.estado == E.REVISAO_NECESSARIA          # o documento ZDC já existia
    assert "gravar_nota" not in sap.chamadas
