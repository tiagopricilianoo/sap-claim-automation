# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Base das páginas: título, subtítulo e área com rolagem."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from ..componentes import rotulo


class Pagina(QWidget):
    titulo = ""
    subtitulo = ""

    def __init__(self, janela, rolagem: bool = True):
        super().__init__()
        self.janela = janela
        self.cfg = janela.cfg
        self.setObjectName("Pagina")
        externo = QVBoxLayout(self)
        externo.setContentsMargins(0, 0, 0, 0)
        externo.setSpacing(0)
        conteudo = QWidget()
        conteudo.setObjectName("Pagina")
        self.lay = QVBoxLayout(conteudo)
        self.lay.setContentsMargins(32, 8, 32, 28)
        self.lay.setSpacing(18)
        if rolagem:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QScrollArea.NoFrame)
            area.setWidget(conteudo)
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            externo.addWidget(area)
        else:
            externo.addWidget(conteudo)

    def colunas(self, esquerda: int = 3, direita: int = 2):
        """Duas colunas (formulário | painel)."""
        linha = QHBoxLayout()
        linha.setSpacing(18)
        a, b = QVBoxLayout(), QVBoxLayout()
        a.setSpacing(18)
        b.setSpacing(18)
        linha.addLayout(a, esquerda)
        linha.addLayout(b, direita)
        self.lay.addLayout(linha)
        return a, b

    def ao_mostrar(self) -> None:
        """Chamado quando a página aparece (atualizar dados)."""

    def ao_mudar_tema(self) -> None:
        """Componentes que se pintam sozinhos redesenham aqui."""
