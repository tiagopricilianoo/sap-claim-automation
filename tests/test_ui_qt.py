# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Interface PySide6 (versão de teste): monta, segue as mesmas regras e não congela.

Roda sem tela (QT_QPA_PLATFORM=offscreen) e sempre com o SAP simulado. Sem PySide6 instalado, pula."""

import os
import sys
import time
from dataclasses import replace

import pytest

from controlador import Executor
from models import ClaimRequest
from sap_fake import FakeSap
from state import Estado as E
from storage import Storage


def _app():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv[:1])
    QSettings("AutomacaoComercial", "InterfaceQtTestes").clear()
    return app


class _Dialogos:
    """Troca os diálogos por respostas fixas (sem janela modal travando o teste)."""

    def __init__(self, resposta=True, texto="100065700"):
        from ui_qt import dialogos
        self.d, self.vistos = dialogos, []
        self.antigos = {n: getattr(dialogos, n) for n in ("confirmar", "ok_cancelar", "informar", "avisar", "erro",
                                                         "pedir_texto", "sim_nao_cancelar", "escolher")}
        r = lambda nome, valor: (lambda *a, **k: (self.vistos.append((nome, a[1:] if len(a) > 1 else a)), valor)[1])
        for nome in ("confirmar", "ok_cancelar"):
            setattr(dialogos, nome, r(nome, resposta))
        for nome in ("informar", "avisar", "erro"):
            setattr(dialogos, nome, r(nome, None))
        dialogos.pedir_texto = r("pedir_texto", texto)
        dialogos.sim_nao_cancelar = r("sim_nao_cancelar", True)
        dialogos.escolher = r("escolher", None)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        for n, f in self.antigos.items():
            setattr(self.d, n, f)


def _janela(settings, tmp_path, **kw):
    _app()
    from ui_qt.janela import JanelaPrincipal
    cfg = replace(settings, pasta_dados=tmp_path, **kw)
    ex = Executor(cfg, tmp_path / "historico.db", fabrica_sap=lambda c, m: FakeSap())
    j = JanelaPrincipal(cfg, ex)
    from PySide6.QtWidgets import QApplication
    fim = time.time() + 0.5           # deixa a verificação automática do SAP (300 ms) começar e terminar
    while time.time() < fim:
        QApplication.processEvents()
        time.sleep(0.02)
    _esperar(ex)
    j.preferencias = __import__("PySide6.QtCore", fromlist=["QSettings"]).QSettings("AutomacaoComercial",
                                                                                     "InterfaceQtTestes")
    return j, ex


def _esperar(ex, segundos=20):
    from PySide6.QtWidgets import QApplication
    fim = time.time() + segundos
    while time.time() < fim:
        QApplication.processEvents()
        if not ex.ocupado:
            break
        time.sleep(0.02)
    for _ in range(20):               # o QTimer da ponte entrega o evento final
        QApplication.processEvents()
        time.sleep(0.01)
    # A verificação automática do SAP (300 ms depois de abrir) pode começar durante a espera acima;
    # num PC mais lento ela ainda está rodando no próximo clique, e a tela responde "Aguarde".
    while ex.ocupado and time.time() < fim + segundos:
        QApplication.processEvents()
        time.sleep(0.02)
    for _ in range(10):
        QApplication.processEvents()
        time.sleep(0.01)


def _preencher(c, arquivo, ordem="1234567", item="10"):
    c.tipo._clicou(list(c.rotas)[0])
    c.ordem.setText(ordem)
    c.item.setText(item)
    c.descricao.setText("Vibração no mancal")
    c.texto.setPlainText("Detalhes")
    c.arquivo.definir(str(arquivo))
    for campo in ("ordem", "item", "descricao", "arquivo"):
        c._mudou(campo)


# ------------------------------------------------------------------ montagem e modos

def test_ui_qt_monta_nos_dois_temas(settings, tmp_path):
    j, _ = _janela(settings, tmp_path)
    for chave in j.paginas:
        j.ir(chave)
    j.aplicar_tema("escuro")
    j.aplicar_tema("claro")
    assert set(j.paginas) >= {"painel", "claim", "execucao", "historico", "pendencias", "configuracoes"}


def test_ui_qt_modos_que_gravam_so_com_habilitacao(settings, tmp_path):
    j, _ = _janela(settings, tmp_path, automatico_habilitado=False)
    assert set(j.pagina_claim.rotulo_modo) == {"SIMULACAO", "ENSAIO"}
    j2, _ = _janela(settings, tmp_path, automatico_habilitado=True)
    assert set(j2.pagina_claim.rotulo_modo) == {"SIMULACAO", "ENSAIO", "ASSISTIDO", "AUTOMATICO"}


def test_ui_qt_producao_sem_seletor_de_modo(settings, tmp_path):
    j, _ = _janela(settings, tmp_path, modo="AUTOMATICO", automatico_habilitado=True)
    assert j.producao and not hasattr(j.pagina_claim, "modo")
    assert j.pagina_claim._modo_escolhido() == "AUTOMATICO"
    assert j.pagina_claim.btn_executar.text() == "Criar claim"


# ------------------------------------------------------------------ claim

def test_ui_qt_dados_invalidos_nao_iniciam(settings, tmp_path):
    j, ex = _janela(settings, tmp_path)
    with _Dialogos():
        j.pagina_claim._executar()
    assert not ex.ocupado
    assert "Corrija" in j.pagina_claim.msg_resultado.text()
    assert j.pagina_claim.c_ordem.erro.text()                        # erro ao lado do campo


def test_ui_qt_claim_simulado_completo_e_formulario_limpo(settings, tmp_path, arquivo_pdf):
    j, ex = _janela(settings, tmp_path)
    c = j.pagina_claim
    _preencher(c, arquivo_pdf)
    with _Dialogos():
        c._executar()
        assert not c.descricao.isEnabled()          # formulário travado durante a execução
        _esperar(ex)
    db = Storage(tmp_path / "historico.db")
    ultima = db.recentes(1)[0]
    db.close()
    assert ultima.estado == E.CONCLUIDO and ultima.numero_nota
    assert c.descricao.text() == "" and c.descricao.isEnabled()     # pronto para o próximo, sem repetir
    assert c.ordem.text() == "1234567" and c.tipo.get() == ""
    assert j.pagina_execucao.tempo_claim.percentual.text() == "100%"


def test_ui_qt_segundo_clique_mesma_ordem_item_e_bloqueado(settings, tmp_path, arquivo_pdf):
    # Modo Completo (grava) com o SAP simulado: a duplicidade bloqueia só nos modos que gravam.
    j, ex = _janela(settings, tmp_path, automatico_habilitado=True)
    c = j.pagina_claim
    c.modo.set("Completo")
    with _Dialogos():
        for _ in range(2):
            _preencher(c, arquivo_pdf)
            c._executar()
            _esperar(ex)
    db = Storage(tmp_path / "historico.db")
    estados = [e.estado for e in db.recentes(5)]
    db.close()
    assert estados.count(E.CONCLUIDO) == 1 and estados[0] == E.RECEBIDO      # duplicidade barrada pelo serviço


def test_ui_qt_execucao_nao_trava_a_tela(settings, tmp_path, arquivo_pdf):
    """Durante a execução a fila de eventos continua andando (a thread de trabalho não toca na tela)."""
    from PySide6.QtWidgets import QApplication
    j, _ = _janela(settings, tmp_path)
    ex = Executor(j.cfg, tmp_path / "historico.db", fabrica_sap=lambda c, m: FakeSap(atraso_s=0.05))
    j.executor = ex
    j.ponte.executor = ex
    c = j.pagina_claim
    _preencher(c, arquivo_pdf)
    with _Dialogos():
        c._executar()
        inicio, voltas = time.time(), 0
        while ex.ocupado and time.time() - inicio < 20:
            QApplication.processEvents()
            voltas += 1
        _esperar(ex)
    assert voltas > 50


# ------------------------------------------------------------------ pendências

def test_ui_qt_pendencia_criado_passa_pelo_controlador(settings, tmp_path, request_valido):
    j, _ = _janela(settings, tmp_path)
    db = Storage(tmp_path / "historico.db")
    eid = db.criar_execucao(request_valido, "AUTOMATICO")
    for e in (E.VALIDANDO, E.PRONTO_PARA_EXECUCAO, E.EXECUTANDO, E.AGUARDANDO_CONFIRMACAO):
        db.transitar(eid, e)
    db.close()
    p = j.pagina_pendencias
    j.ir("pendencias")
    p.t_claim.vista.selectRow(0)
    with _Dialogos(texto=request_valido.ordem):                    # número da ordem: o controlador recusa
        p._resolver(True)
    db = Storage(tmp_path / "historico.db")
    assert db.obter(eid).estado == E.AGUARDANDO_CONFIRMACAO
    db.close()
    with _Dialogos(texto="100065700"):
        p._resolver(True)
    db = Storage(tmp_path / "historico.db")
    ex = db.obter(eid)
    db.close()
    assert (ex.estado, ex.numero_nota) == (E.CONCLUIDO, "100065700")


def test_ui_qt_pendencia_recusada_com_execucao_em_andamento(settings, tmp_path, request_valido):
    j, ex = _janela(settings, tmp_path)
    db = Storage(tmp_path / "historico.db")
    eid = db.criar_execucao(request_valido, "AUTOMATICO")
    for e in (E.VALIDANDO, E.PRONTO_PARA_EXECUCAO, E.EXECUTANDO, E.REVISAO_NECESSARIA):
        db.transitar(eid, e)
    db.close()
    j.ir("pendencias")
    j.pagina_pendencias.t_claim.vista.selectRow(0)
    ex._thread = type("T", (), {"is_alive": lambda self: True})()        # finge execução rodando
    try:
        with _Dialogos() as d:
            j.pagina_pendencias._resolver(False)
    finally:
        ex._thread = None
    db = Storage(tmp_path / "historico.db")
    assert db.obter(eid).estado == E.REVISAO_NECESSARIA
    db.close()
    assert d.vistos[0][0] == "informar"


# ------------------------------------------------------------------ painel e fechamento

def test_ui_qt_painel_com_dados_reais(settings, tmp_path, request_valido):
    j, _ = _janela(settings, tmp_path)
    from ui_qt.dados import Historico
    db = Storage(tmp_path / "historico.db")
    sim = db.criar_execucao(request_valido, "SIMULACAO")
    for e in (E.VALIDANDO, E.PRONTO_PARA_EXECUCAO, E.EXECUTANDO, E.AGUARDANDO_CONFIRMACAO, E.CONCLUIDO):
        db.transitar(sim, e)
    db.close()
    n = Historico(tmp_path / "historico.db").indicadores()
    assert n["operacoes"] == 1 and n["claims_concluidos"] == 0          # simulação não conta como claim
    j.ir("painel")
    assert j.pagina_painel.i_operacoes.valor.text() == "1"


def test_ui_qt_fechar_com_execucao_espera(settings, tmp_path):
    from PySide6.QtGui import QCloseEvent
    j, ex = _janela(settings, tmp_path)
    ex._thread = type("T", (), {"is_alive": lambda self: True})()
    try:
        with _Dialogos():
            evento = QCloseEvent()
            j.closeEvent(evento)
        assert not evento.isAccepted() and j.fechando                   # não mata a thread no meio
    finally:
        ex._thread = None


def test_ui_qt_tarefa_de_rede_pergunta_na_tela(settings, tmp_path):
    from PySide6.QtWidgets import QApplication, QMessageBox
    j, _ = _janela(settings, tmp_path)
    from ui_qt.ponte import TarefaRede
    original = QMessageBox.question
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    resultado = {}
    try:
        TarefaRede(j, lambda perguntar: perguntar("t", "x"), lambda r: resultado.update(ok=r),
                   lambda e: resultado.update(erro=e))
        fim = time.time() + 5
        while not resultado and time.time() < fim:
            QApplication.processEvents()
            time.sleep(0.01)
    finally:
        QMessageBox.question = original
    assert resultado == {"ok": True}


def test_ui_qt_dialogo_de_atualizacao_baixa_sem_travar(settings, tmp_path):
    import time as _t
    from PySide6.QtWidgets import QApplication
    import atualizacao_python as ap
    from test_atualizacao_python import _cenario
    j, _ = _janela(settings, tmp_path / "dados")
    from ui_qt.atualizacao import DialogoAtualizacao
    l = _cenario(tmp_path / "rede")
    d = DialogoAtualizacao(j, l)
    d._baixar()
    fim = _t.time() + 10
    while d._timer.isActive() and _t.time() < fim:
        QApplication.processEvents()
        _t.sleep(0.01)
    assert ap.pronto_para_trocar(l) and d.b_principal.text() == "Reiniciar agora"
