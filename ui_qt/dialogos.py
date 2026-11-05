# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Diálogos padronizados (mesmo texto e mesmas decisões da interface anterior)."""

from __future__ import annotations

from PySide6.QtWidgets import QInputDialog, QMessageBox


def informar(pai, titulo: str, texto: str) -> None:
    QMessageBox.information(pai, titulo, texto)


def avisar(pai, titulo: str, texto: str) -> None:
    QMessageBox.warning(pai, titulo, texto)


def erro(pai, titulo: str, texto: str) -> None:
    QMessageBox.critical(pai, titulo, texto)


def confirmar(pai, titulo: str, texto: str, padrao_nao: bool = False, alerta: bool = True) -> bool:
    caixa = QMessageBox(QMessageBox.Warning if alerta else QMessageBox.Question, titulo, texto,
                        QMessageBox.Yes | QMessageBox.No, pai)
    caixa.button(QMessageBox.Yes).setText("Sim")
    caixa.button(QMessageBox.No).setText("Não")
    caixa.setDefaultButton(QMessageBox.No if padrao_nao else QMessageBox.Yes)
    return caixa.exec() == QMessageBox.Yes


def ok_cancelar(pai, titulo: str, texto: str) -> bool:
    caixa = QMessageBox(QMessageBox.Information, titulo, texto, QMessageBox.Ok | QMessageBox.Cancel, pai)
    caixa.button(QMessageBox.Cancel).setText("Cancelar")
    return caixa.exec() == QMessageBox.Ok


def sim_nao_cancelar(pai, titulo: str, texto: str) -> bool | None:
    caixa = QMessageBox(QMessageBox.Question, titulo, texto,
                        QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, pai)
    caixa.button(QMessageBox.Yes).setText("Sim")
    caixa.button(QMessageBox.No).setText("Não")
    caixa.button(QMessageBox.Cancel).setText("Cancelar")
    resposta = caixa.exec()
    if resposta == QMessageBox.Yes:
        return True
    if resposta == QMessageBox.No:
        return False
    return None


def pedir_texto(pai, titulo: str, texto: str) -> str | None:
    valor, ok = QInputDialog.getText(pai, titulo, texto)
    return valor if ok else None


def escolher(pai, titulo: str, texto: str, opcoes: list[str]) -> str | None:
    valor, ok = QInputDialog.getItem(pai, titulo, texto, opcoes, 0, False)
    return valor if ok else None
