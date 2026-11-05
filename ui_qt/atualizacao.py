# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Aviso de atualização do Python do programa: perguntar, baixar com barra e reiniciar."""

from __future__ import annotations

import logging
import queue
import threading

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout

import atualizacao_python as ap

from .componentes import Botao, rotulo

log = logging.getLogger("claim.ui_qt.atualizacao")


class DialogoAtualizacao(QDialog):
    def __init__(self, janela, locais: ap.Locais):
        super().__init__(janela)
        self.janela, self.l = janela, locais
        self.setWindowTitle("Atualização disponível")
        self.setModal(True)
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 20)
        lay.setSpacing(12)
        self.titulo = rotulo("Há uma nova atualização disponível", "CardTitulo")
        self.texto = rotulo("Deseja baixar? Você pode continuar usando o programa normalmente depois; "
                            "a nova versão entra quando o programa reiniciar.", "Dica", quebra=True)
        lay.addWidget(self.titulo)
        lay.addWidget(self.texto)
        self.barra = QProgressBar()
        self.barra.setRange(0, 1000)
        self.barra.setTextVisible(False)
        self.barra.setVisible(False)
        lay.addWidget(self.barra)
        self.detalhe = rotulo("", "Dica")
        self.detalhe.setVisible(False)
        lay.addWidget(self.detalhe)
        botoes = QHBoxLayout()
        botoes.addStretch(1)
        self.b_secundario = Botao("Atualizar depois", "secundario", "", self.reject)
        self.b_principal = Botao("Baixar agora", "primario", "upload", self._baixar)
        botoes.addWidget(self.b_secundario)
        botoes.addWidget(self.b_principal)
        lay.addLayout(botoes)
        self._fila: queue.Queue = queue.Queue()
        self._cancelar = threading.Event()
        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._conferir)
        self._baixando = False

    # ------------------------------------------------------------------ baixar

    def _baixar(self) -> None:
        self._baixando = True
        self.titulo.setText("Baixando a atualização…")
        self.texto.setText("Copiando do servidor. Pode levar alguns minutos.")
        self.barra.setVisible(True)
        self.detalhe.setVisible(True)
        self.b_principal.setVisible(False)
        self.b_secundario.setText("Cancelar")
        self.b_secundario.clicked.disconnect()
        self.b_secundario.clicked.connect(self._cancelar.set)

        def trabalho():
            try:
                ok = ap.baixar(self.l, lambda f, t: self._fila.put(("progresso", (f, t))), self._cancelar.is_set)
                self._fila.put(("fim", ok))
            except Exception as erro:  # noqa: BLE001
                log.exception("Falha ao baixar o Python novo")
                self._fila.put(("erro", erro))

        threading.Thread(target=trabalho, daemon=True, name="baixar-python").start()
        self._timer.start()

    def _conferir(self) -> None:
        while True:
            try:
                tipo, dado = self._fila.get_nowait()
            except queue.Empty:
                return
            if tipo == "progresso":
                feito, total = dado
                self.barra.setValue(int(1000 * feito / max(1, total)))
                self.detalhe.setText(f"{feito / 1048576:.0f} de {total / 1048576:.0f} MB")
                continue
            self._timer.stop()
            self._baixando = False
            if tipo == "erro":
                self._mostrar_fim("Não foi possível baixar", f"{dado}\n\nO programa continua como está.", False)
            elif dado:
                self._mostrar_fim("Atualização pronta", "Reinicie o programa para usar a nova versão.", True)
            else:
                self.reject()

    def _mostrar_fim(self, titulo: str, texto: str, ok: bool) -> None:
        self.titulo.setText(titulo)
        self.texto.setText(texto)
        self.barra.setVisible(ok)
        self.detalhe.setVisible(False)
        self.b_secundario.clicked.disconnect()
        self.b_secundario.setText("Na próxima vez" if ok else "Fechar")
        self.b_secundario.clicked.connect(self.reject)
        if ok:
            self.b_principal.setText("Reiniciar agora")
            self.b_principal.clicked.disconnect()
            self.b_principal.clicked.connect(self._reiniciar)
            self.b_principal.setVisible(True)

    def _reiniciar(self) -> None:
        if self.janela.executor.ocupado:
            self.texto.setText("Há uma execução em andamento. Reinicie quando ela terminar (ou na próxima vez).")
            return
        try:
            ap.reiniciar_com_python_novo(self.l)
        except Exception as erro:  # noqa: BLE001
            self.texto.setText(f"Não foi possível reiniciar agora ({erro}). A troca acontece na próxima abertura.")
            return
        self.accept()
        self.janela.fechar_para_atualizar()

    def reject(self) -> None:  # noqa: D401 - fechar no meio do download = cancelar
        if self._baixando:
            self._cancelar.set()
            return
        super().reject()


def verificar(janela) -> None:
    """Confere em segundo plano (rede) e, havendo Python novo no servidor, pergunta."""
    from .ponte import TarefaRede
    l = ap.locais()
    if l is None:
        return

    def terminou(disponivel: bool) -> None:
        if disponivel and not janela.executor.ocupado and not janela.fechando:
            DialogoAtualizacao(janela, l).exec()

    TarefaRede(janela, lambda _perguntar: ap.disponivel(l) and not ap.pronto_para_trocar(l), terminou,
               lambda erro: log.warning("Verificação de atualização falhou: %s", erro))
