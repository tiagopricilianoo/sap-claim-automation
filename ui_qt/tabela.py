# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Tabela profissional: ordenação, filtro, coluna de status como badge e estado vazio."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QRectF, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHeaderView, QStackedLayout, QStyle, QStyledItemDelegate,
                               QTableView, QVBoxLayout)

from .componentes import EstadoVazio
from .tema import FONTE, TONS, Tema

PAPEL_ID = Qt.UserRole + 1
PAPEL_TOM = Qt.UserRole + 2
PAPEL_ORDEM = Qt.UserRole + 3
PAPEL_DADO = Qt.UserRole + 4


class _DelegadoStatus(QStyledItemDelegate):
    def sizeHint(self, opcao, indice):  # noqa: N802 - largura do texto + o "comprimido" do badge
        tamanho = super().sizeHint(opcao, indice)
        tamanho.setWidth(tamanho.width() + 36)
        return tamanho

    def paint(self, pintor: QPainter, opcao, indice: QModelIndex) -> None:
        self.initStyleOption(opcao, indice)
        texto = indice.data(Qt.DisplayRole) or ""
        tom = indice.data(PAPEL_TOM) or "neutro"
        fundo, cor, _ = TONS.get(tom, TONS["neutro"])
        pintor.save()
        estilo = opcao.widget.style() if opcao.widget else None
        opcao.text = ""
        if estilo:
            estilo.drawControl(QStyle.ControlElement.CE_ItemViewItem, opcao, pintor, opcao.widget)
        fonte = QFont(FONTE)
        fonte.setPixelSize(11)
        fonte.setWeight(QFont.DemiBold)
        pintor.setFont(fonte)
        largura = pintor.fontMetrics().horizontalAdvance(texto) + 20
        r = opcao.rect
        caixa = QRectF(r.x() + 10, r.center().y() - 10, min(largura, r.width() - 14), 20)
        pintor.setRenderHint(QPainter.Antialiasing)
        pintor.setPen(Qt.NoPen)
        pintor.setBrush(QColor(Tema.cor(fundo)))
        pintor.drawRoundedRect(caixa, 10, 10)
        pintor.setPen(QColor(Tema.cor(cor)))
        pintor.drawText(caixa, Qt.AlignCenter, texto)
        pintor.restore()


class _Filtro(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.funcao = None
        self.setSortRole(PAPEL_ORDEM)

    def filterAcceptsRow(self, linha: int, pai: QModelIndex) -> bool:  # noqa: N802
        if self.funcao is None:
            return True
        dado = self.sourceModel().index(linha, 0, pai).data(PAPEL_DADO)
        return self.funcao(dado)


class Tabela(QFrame):
    selecionou = Signal(object)        # dado da linha (ou None)
    duplo_clique = Signal(object)

    def __init__(self, colunas: list[tuple[str, int]], coluna_status: int = -1, vazio=("historico", "Nada por aqui",
                                                                                        "")):
        super().__init__()
        self.setObjectName("Card")
        externo = QVBoxLayout(self)
        externo.setContentsMargins(1, 1, 1, 1)
        self._pilha = QStackedLayout()
        externo.addLayout(self._pilha)
        self.modelo = QStandardItemModel(0, len(colunas))
        self.modelo.setHorizontalHeaderLabels([c for c, _ in colunas])
        self.filtro = _Filtro()
        self.filtro.setSourceModel(self.modelo)
        self.vista = QTableView()
        self.vista.setModel(self.filtro)
        self.vista.setSortingEnabled(True)
        self.vista.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.vista.setSelectionMode(QAbstractItemView.SingleSelection)
        self.vista.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.vista.verticalHeader().setVisible(False)
        self.vista.verticalHeader().setDefaultSectionSize(44)
        self.vista.setShowGrid(False)
        self.vista.setWordWrap(False)
        self.vista.setFocusPolicy(Qt.StrongFocus)
        cab = self.vista.horizontalHeader()
        cab.setHighlightSections(False)
        cab.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for i, (_, largura) in enumerate(colunas):
            if largura > 0:
                self.vista.setColumnWidth(i, largura)
        cab.setStretchLastSection(True)
        cab.setSectionResizeMode(QHeaderView.Interactive)
        self._coluna_status = coluna_status
        if coluna_status >= 0:
            self._delegado = _DelegadoStatus(self.vista)
            self.vista.setItemDelegateForColumn(coluna_status, self._delegado)
        self.vista.selectionModel().selectionChanged.connect(lambda *_: self.selecionou.emit(self.selecionado()))
        self.vista.doubleClicked.connect(lambda _: self.duplo_clique.emit(self.selecionado()))
        self._pilha.addWidget(self.vista)
        self.vazio = EstadoVazio(*vazio)
        self._pilha.addWidget(self.vazio)

    def definir(self, linhas: list[dict]) -> None:
        """linhas: {valores: [...], ordem: [...] (opcional), tom: str, dado: objeto}."""
        selecionado = self.selecionado()
        id_antes = getattr(selecionado, "id", None)
        self.vista.setSortingEnabled(False)
        self.modelo.removeRows(0, self.modelo.rowCount())
        for linha in linhas:
            itens = []
            for i, valor in enumerate(linha["valores"]):
                item = QStandardItem(str(valor))
                item.setData((linha.get("ordem") or linha["valores"])[i], PAPEL_ORDEM)
                item.setData(linha.get("tom", "neutro"), PAPEL_TOM)
                item.setData(linha.get("dado"), PAPEL_DADO)
                item.setToolTip(str(valor))
                itens.append(item)
            self.modelo.appendRow(itens)
        self.vista.setSortingEnabled(True)
        # Colunas no tamanho do conteúdo (datas e números nunca cortados); status com folga para o badge.
        cab = self.vista.horizontalHeader()
        for i in range(self.modelo.columnCount() - 1):
            cab.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self.atualizar_vazio()
        if id_antes is not None:
            for r in range(self.filtro.rowCount()):
                if getattr(self.filtro.index(r, 0).data(PAPEL_DADO), "id", None) == id_antes:
                    self.vista.selectRow(r)
                    break

    def aplicar_filtro(self, funcao) -> None:
        self.filtro.funcao = funcao
        self.filtro.invalidateFilter()
        self.atualizar_vazio()

    def atualizar_vazio(self) -> None:
        self._pilha.setCurrentWidget(self.vista if self.filtro.rowCount() else self.vazio)

    def selecionado(self):
        indices = self.vista.selectionModel().selectedRows() if self.vista.selectionModel() else []
        return indices[0].data(PAPEL_DADO) if indices else None

    def ordenar(self, coluna: int, decrescente: bool = True) -> None:
        self.vista.sortByColumn(coluna, Qt.DescendingOrder if decrescente else Qt.AscendingOrder)
