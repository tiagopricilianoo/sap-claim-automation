# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Interface nova (PySide6) — VERSÃO DE TESTE. A interface oficial continua sendo ui.py.

Uso:  python app_qt.py
"""

from __future__ import annotations

import logging
import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication, QMessageBox

    from config import ConfigError, load_settings
    from instancia import InstanciaUnica
    from logger_config import configurar_logs

    app = QApplication(sys.argv)
    app.setApplicationName("Automação Comercial")
    try:
        settings = load_settings()
    except ConfigError as erro:
        QMessageBox.critical(None, "Configuração", f"Erro no settings.ini:\n\n{erro}")
        return 1
    configurar_logs(settings.pasta_dados)
    trava = InstanciaUnica(settings.pasta_dados)
    if not trava.adquirir():
        QMessageBox.information(None, "Automação Comercial", "O programa já está aberto neste computador.\n\n"
                                "Use a janela que já está aberta (veja na barra de tarefas).")
        return 0

    def erro_inesperado(tipo, valor, rastro):
        """Sem console (atalho), um erro da tela não pode sumir em silêncio."""
        logging.getLogger("claim.ui_qt").error("Erro inesperado na interface", exc_info=(tipo, valor, rastro))
        QMessageBox.critical(None, "Erro inesperado", f"{valor}\n\nO detalhe foi registrado no log. Se repetir, "
                             "avise o responsável pela ferramenta.")

    sys.excepthook = erro_inesperado
    try:
        from ui_qt.janela import JanelaPrincipal
        janela = JanelaPrincipal(settings)
        janela.show()
        return app.exec()
    finally:
        trava.liberar()


if __name__ == "__main__":
    sys.exit(main())
