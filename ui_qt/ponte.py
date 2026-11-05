# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Comunicação entre as threads de trabalho e a tela.

As threads (Executor do controlador.py e a conferência de pastas na rede) NUNCA tocam em widgets:
colocam eventos numa fila. Um QTimer na thread da tela lê a fila e emite sinais Qt.
"""

from __future__ import annotations

import queue
import threading

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QMessageBox


class PonteExecutor(QObject):
    etapa = Signal(str, str, str, str)      # origem, chave, situacao, detalhe
    fim = Signal(object)                    # Evento (tipo fim | erro)
    sap = Signal(str, str)                  # situacao, detalhe

    def __init__(self, executor, parent=None):
        super().__init__(parent)
        self.executor = executor
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._drenar)
        self._timer.start()

    def _drenar(self) -> None:
        for evento in self.executor.drenar():
            try:
                if evento.tipo == "etapa":
                    self.etapa.emit(evento.origem, evento.etapa, evento.situacao, evento.detalhe)
                elif evento.tipo == "sap":
                    self.sap.emit(evento.situacao, evento.detalhe)
                elif evento.tipo in ("fim", "erro"):
                    self.fim.emit(evento)
            except Exception:  # noqa: BLE001 - um evento com problema não pode parar a tela
                import logging
                logging.getLogger("claim.ui_qt").exception("evento %s", evento.tipo)


class TarefaRede(QObject):
    """Trabalho lento na rede (pastas) fora da thread da tela. As perguntas voltam para a tela.

    trabalho(perguntar) roda numa thread; perguntar(titulo, texto) -> bool mostra a pergunta NA TELA
    e espera a resposta. ao_terminar(resultado) / ao_falhar(erro) rodam na thread da tela.
    """
    em_andamento: set = set()

    def __init__(self, janela, trabalho, ao_terminar, ao_falhar):
        super().__init__(janela)
        self._janela, self._ao_terminar, self._ao_falhar = janela, ao_terminar, ao_falhar
        self._fila: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._rodar, args=(trabalho,), daemon=True, name="rede")
        self._timer = QTimer(self)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._conferir)
        TarefaRede.em_andamento.add(self)
        self._thread.start()
        self._timer.start()

    @property
    def ativo(self) -> bool:
        return self._thread.is_alive()

    def perguntar(self, titulo: str, texto: str) -> bool:
        resposta: dict = {}
        pronto = threading.Event()
        self._fila.put(("pergunta", (titulo, texto, resposta, pronto)))
        pronto.wait()
        return bool(resposta.get("sim"))

    def _rodar(self, trabalho) -> None:
        com = False
        try:                                   # o atalho da pasta (WScript.Shell) é COM
            import pythoncom  # type: ignore
            pythoncom.CoInitialize()
            com = True
        except ImportError:
            pass
        try:
            self._fila.put(("ok", trabalho(self.perguntar)))
        except Exception as erro:  # noqa: BLE001 - volta para a tela como mensagem
            self._fila.put(("erro", erro))
        finally:
            if com:
                import pythoncom  # type: ignore
                pythoncom.CoUninitialize()

    def _conferir(self) -> None:
        while True:
            try:
                tipo, dado = self._fila.get_nowait()
            except queue.Empty:
                return
            if tipo == "pergunta":
                titulo, texto, resposta, pronto = dado
                try:
                    resposta["sim"] = QMessageBox.question(self._janela, titulo, texto) == QMessageBox.Yes
                finally:
                    pronto.set()
                continue
            self._timer.stop()
            TarefaRede.em_andamento.discard(self)
            (self._ao_terminar if tipo == "ok" else self._ao_falhar)(dado)
            self.deleteLater()
            return
