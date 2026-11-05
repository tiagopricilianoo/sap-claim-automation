# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Componentes reutilizáveis (cards, botões, campos, linha do tempo, indicadores)."""

from __future__ import annotations

import weakref
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QFileDialog, QFrame, QGraphicsDropShadowEffect, QGraphicsOpacityEffect,
                               QHBoxLayout, QLabel, QProgressBar, QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget)

from . import icones
from .tema import TONS, Tema

# Widgets com ícone que precisam ser redesenhados quando o tema muda.
_COM_ICONE: "weakref.WeakSet" = weakref.WeakSet()


def repolir(widget: QWidget) -> None:
    """Reaplica o QSS depois de mudar uma propriedade dinâmica (ex.: erro=true)."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def atualizar_icones() -> None:
    for w in list(_COM_ICONE):
        try:
            w.redesenhar_icone()
        except RuntimeError:          # widget já destruído pelo Qt
            pass


def rotulo(texto: str = "", nome: str = "", quebra: bool = False) -> QLabel:
    l = QLabel(texto)
    if nome:
        l.setObjectName(nome)
    l.setWordWrap(quebra)
    l.setTextInteractionFlags(Qt.TextSelectableByMouse if nome in ("Mono", "Valor") else Qt.NoTextInteraction)
    return l


def divisor() -> QFrame:
    f = QFrame()
    f.setObjectName("Divisor")
    return f


class Card(QFrame):
    def __init__(self, titulo: str = "", sub: str = "", sombra: bool = True, margem: int = 20, espaco: int = 12):
        super().__init__()
        self.setObjectName("Card")
        self.corpo = QVBoxLayout(self)
        self.corpo.setContentsMargins(margem, margem, margem, margem)
        self.corpo.setSpacing(espaco)
        self.cabecalho = QHBoxLayout()
        self.cabecalho.setSpacing(8)
        if titulo:
            textos = QVBoxLayout()
            textos.setSpacing(2)
            self.titulo = rotulo(titulo, "CardTitulo")
            textos.addWidget(self.titulo)
            if sub:
                self.sub = rotulo(sub, "CardSub", quebra=True)
                textos.addWidget(self.sub)
            textos.setAlignment(Qt.AlignTop)
            self.cabecalho.addLayout(textos, 1)
            self.corpo.addLayout(self.cabecalho, 0)
        if sombra:
            efeito = QGraphicsDropShadowEffect(self)
            efeito.setBlurRadius(18)
            efeito.setOffset(0, 2)
            cor = QColor(Tema.cor("sombra"))
            cor.setAlpha(14)
            efeito.setColor(cor)
            self.setGraphicsEffect(efeito)

    def add(self, widget, estica: int = 0):
        self.corpo.addWidget(widget, estica)
        return widget


class Badge(QLabel):
    def __init__(self, texto: str = "", tom: str = "neutro"):
        super().__init__(texto)
        self.setObjectName("Badge")
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.definir(texto, tom)

    def definir(self, texto: str, tom: str = "neutro") -> None:
        self.setText(texto)
        self.setVisible(bool(texto))
        self.setProperty("tom", tom if tom in TONS else "neutro")
        repolir(self)


class Botao(QPushButton):
    """variante: primario | secundario | perigo | sucesso | fantasma | grande."""
    COR_ICONE = {"primario": None, "grande": None, "sucesso": None, "secundario": "texto_2",
                 "perigo": "erro_texto", "fantasma": "azul_texto"}

    def __init__(self, texto: str, variante: str = "secundario", icone: str = "", ao_clicar=None):
        super().__init__(texto)
        self.setProperty("variante", variante)
        self.setCursor(Qt.PointingHandCursor)
        self._icone, self._variante = icone, variante
        if icone:
            self.setIconSize(QSize(16, 16))
            self.redesenhar_icone()
            _COM_ICONE.add(self)
        if ao_clicar:
            self.clicked.connect(ao_clicar)

    def redesenhar_icone(self) -> None:
        if not self._icone:
            return
        chave = self.COR_ICONE.get(self._variante)
        self.setIcon(icones.icone(self._icone, Tema.cor(chave) if chave else "#FFFFFF", 16))


class Segmentado(QFrame):
    """Escolha única entre poucas opções (tipo de claim, modo, tipo de cotação)."""
    mudou = Signal(str)

    def __init__(self, opcoes: list[str], permitir_vazio: bool = True):
        super().__init__()
        self.setObjectName("Segmentado")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self._botoes: dict[str, QPushButton] = {}
        for texto in opcoes:
            b = QPushButton(texto)
            b.setObjectName("Segmento")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, t=texto: self._clicou(t))
            lay.addWidget(b, 1)
            self._botoes[texto] = b
        self._valor = ""

    def _clicou(self, texto: str) -> None:
        self.set(texto)
        self.mudou.emit(texto)

    def set(self, texto: str) -> None:
        self._valor = texto if texto in self._botoes else ""
        for t, b in self._botoes.items():
            b.setChecked(t == self._valor)

    def get(self) -> str:
        return self._valor

    def setEnabled(self, ativo: bool) -> None:  # noqa: N802 - API Qt
        for b in self._botoes.values():
            b.setEnabled(ativo)


class Campo(QWidget):
    """Rótulo + controle + mensagem de erro logo abaixo (validação em tempo real)."""

    def __init__(self, titulo: str, controle: QWidget, obrigatorio: bool = True, dica: str = "",
                 direita: QWidget | None = None):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        topo = QHBoxLayout()
        topo.setSpacing(2)
        topo.addWidget(rotulo(titulo, "Rotulo"))
        if obrigatorio:
            topo.addWidget(rotulo("*", "Obrigatorio"))
        topo.addStretch(1)
        if direita is not None:
            topo.addWidget(direita)
        lay.addLayout(topo)
        lay.addWidget(controle)
        self.controle = controle
        self.dica = rotulo(dica, "Dica", quebra=True)
        self.dica.setVisible(bool(dica))
        lay.addWidget(self.dica)
        self.erro = rotulo("", "Erro", quebra=True)
        self.erro.setVisible(False)
        lay.addWidget(self.erro)

    def set_erro(self, mensagem: str) -> None:
        self.erro.setText(mensagem)
        self.erro.setVisible(bool(mensagem))
        if self.controle.property("erro") != bool(mensagem):
            self.controle.setProperty("erro", bool(mensagem))
            repolir(self.controle)

    def set_dica(self, texto: str, azul: bool = False) -> None:
        self.dica.setText(texto)
        self.dica.setObjectName("DicaAzul" if azul else "Dica")
        repolir(self.dica)
        self.dica.setVisible(bool(texto))


class Banner(QFrame):
    def __init__(self, tom: str = "info", titulo: str = "", texto: str = ""):
        super().__init__()
        self.setObjectName("Banner")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(12)
        self._icone = QLabel()
        self._icone.setFixedSize(20, 20)
        self._icone.setStyleSheet("background: transparent;")
        lay.addWidget(self._icone, 0, Qt.AlignTop)
        textos = QVBoxLayout()
        textos.setSpacing(2)
        self.titulo = rotulo("", "BannerTitulo", quebra=True)
        self.texto = rotulo("", "BannerTexto", quebra=True)
        self.texto.setTextInteractionFlags(Qt.TextSelectableByMouse)
        textos.addWidget(self.titulo)
        textos.addWidget(self.texto)
        lay.addLayout(textos, 1)
        self.acoes = QHBoxLayout()
        lay.addLayout(self.acoes)
        _COM_ICONE.add(self)
        self.definir(tom, titulo, texto)

    def definir(self, tom: str, titulo: str, texto: str = "") -> None:
        self._tom = tom if tom in TONS else "neutro"
        self.setProperty("tom", self._tom)
        self.titulo.setText(titulo)
        self.titulo.setVisible(bool(titulo))
        self.texto.setText(texto)
        self.texto.setVisible(bool(texto))
        repolir(self)
        for filho in (self.titulo, self.texto):
            repolir(filho)
        self.redesenhar_icone()

    def redesenhar_icone(self) -> None:
        nome = {"ok": "check", "erro": "alerta", "atencao": "pendencia", "info": "info"}.get(self._tom, "info")
        self._icone.setPixmap(icones.pixmap(nome, Tema.cor(TONS[self._tom][1]), 20))


class Indicador(QFrame):
    """Número grande do painel (dados reais do histórico)."""

    def __init__(self, titulo: str, icone: str, tom: str = "info"):
        super().__init__()
        self.setObjectName("Card")
        self._nome_icone, self._tom = icone, tom
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(6)
        topo = QHBoxLayout()
        topo.addWidget(rotulo(titulo, "CardSub"))
        topo.addStretch(1)
        self._icone = QLabel()
        self._icone.setFixedSize(30, 30)
        self._icone.setAlignment(Qt.AlignCenter)
        topo.addWidget(self._icone)
        lay.addLayout(topo)
        self.valor = rotulo("—", "Valor")
        lay.addWidget(self.valor)
        self.sub = rotulo("", "Dica")
        lay.addWidget(self.sub)
        _COM_ICONE.add(self)
        self.redesenhar_icone()

    def redesenhar_icone(self) -> None:
        fundo, texto, _ = TONS[self._tom]
        self._icone.setStyleSheet(f"background: {Tema.cor(fundo)}; border-radius: 8px;")
        self._icone.setPixmap(icones.pixmap(self._nome_icone, Tema.cor(texto), 16))

    def definir(self, valor, sub: str = "") -> None:
        self.valor.setText(str(valor))
        self.sub.setText(sub)


# ============================================================================ linha do tempo

class _Marcador(QWidget):
    """Círculo da etapa: aguardando (vazio), em andamento (azul), ok (verde), falha (vermelho)."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(26, 26)
        self.situacao = "aguardando"
        self.ativa = True

    def paintEvent(self, _evento):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(3, 3, 20, 20)
        cores = {"ativo": ("azul", "azul_suave"), "ok": ("ok", "ok"), "falha": ("erro", "erro"),
                 "atencao": ("atencao", "atencao")}
        if not self.ativa:
            p.setPen(QPen(QColor(Tema.cor("borda")), 1.5, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(r)
            return
        if self.situacao in ("ok", "falha", "atencao"):
            borda, fundo = cores[self.situacao]
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(Tema.cor(fundo)))
            p.drawEllipse(r)
            nome = {"ok": "check", "falha": "x", "atencao": "pendencia"}[self.situacao]
            p.drawPixmap(7, 7, icones.pixmap(nome, "#FFFFFF", 12))
        elif self.situacao == "ativo":
            p.setPen(QPen(QColor(Tema.cor("azul")), 2))
            p.setBrush(QColor(Tema.cor("azul_suave")))
            p.drawEllipse(r)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(Tema.cor("azul")))
            p.drawEllipse(QRectF(9, 9, 8, 8))
        else:
            p.setPen(QPen(QColor(Tema.cor("borda_forte")), 1.5))
            p.setBrush(QColor(Tema.cor("superficie")))
            p.drawEllipse(r)


class LinhaDoTempo(QWidget):
    """Etapas da automação com estado: aguardando, em andamento, concluída, atenção, falha."""

    def __init__(self, etapas: tuple[tuple[str, str], ...]):
        super().__init__()
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(0)
        self.barra = QProgressBar()
        self.barra.setTextVisible(False)
        self.barra.setRange(0, 1000)
        topo = QHBoxLayout()
        self.resumo = rotulo("Aguardando início", "Dica")
        topo.addWidget(self.resumo)
        topo.addStretch(1)
        self.percentual = rotulo("0%", "Dica")
        topo.addWidget(self.percentual)
        self._lay.addLayout(topo)
        self._lay.addSpacing(6)
        self._lay.addWidget(self.barra)
        self._lay.addSpacing(14)
        self.linhas: dict[str, tuple[_Marcador, QLabel, QLabel]] = {}
        for chave, titulo in etapas:
            linha = QHBoxLayout()
            linha.setSpacing(10)
            m = _Marcador()
            linha.addWidget(m, 0, Qt.AlignTop)
            textos = QVBoxLayout()
            textos.setSpacing(1)
            nome = rotulo(titulo)
            detalhe = rotulo("", "Dica", quebra=True)
            textos.addWidget(nome)
            textos.addWidget(detalhe)
            linha.addLayout(textos, 1)
            self._lay.addLayout(linha)
            self._lay.addSpacing(8)
            self.linhas[chave] = (m, nome, detalhe)
        self._ativas: list[str] = [c for c, _ in etapas]

    def preparar(self, ativas: list[str], motivo_inativa: str = "não faz parte deste modo") -> None:
        self._ativas = list(ativas)
        for chave, (m, nome, detalhe) in self.linhas.items():
            m.ativa, m.situacao = chave in ativas, "aguardando"
            m.update()
            self._pintar_nome(chave)
            detalhe.setText("" if m.ativa else motivo_inativa)
            detalhe.setVisible(not m.ativa)
        self.barra.setValue(0)
        self.percentual.setText("0%")
        self.resumo.setText("Aguardando início")

    def marcar(self, chave: str, situacao: str, detalhe: str = "") -> None:
        """situacao: ativo | ok | falha | atencao."""
        if chave not in self.linhas:
            return
        m, nome, rot = self.linhas[chave]
        m.situacao = situacao
        m.update()
        self._pintar_nome(chave)
        texto = {"ativo": "em andamento…", "falha": detalhe or "falhou"}.get(situacao, detalhe)
        rot.setText(texto[:140])
        rot.setVisible(bool(texto))
        if situacao == "ativo":
            self.resumo.setText(f"Em andamento: {nome.text()}")
        feitas = sum(1 for c in self._ativas if self.linhas[c][0].situacao == "ok")
        valor = int(1000 * feitas / max(1, len(self._ativas)))
        self._animar_barra(valor)
        self.percentual.setText(f"{valor // 10}%")
        if situacao == "falha":
            self.resumo.setText(f"Parou em: {nome.text()}")
        elif feitas == len(self._ativas):
            self.resumo.setText("Todas as etapas concluídas")

    def _animar_barra(self, valor: int) -> None:
        self._anim = QPropertyAnimation(self.barra, b"value", self)
        self._anim.setDuration(250)
        self._anim.setEndValue(valor)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.start()

    def _pintar_nome(self, chave: str) -> None:
        m, nome, _ = self.linhas[chave]
        if not m.ativa:
            cor, peso = "texto_3", 400
        else:
            cor = {"ativo": "azul_texto", "falha": "erro_texto", "atencao": "atencao_texto"}.get(m.situacao, "texto")
            peso = 600 if m.situacao in ("ativo", "falha", "atencao") else 400
        nome.setStyleSheet(f"color: {Tema.cor(cor)}; font-weight: {peso};")

    def redesenhar(self) -> None:
        for chave, (m, _, _) in self.linhas.items():
            m.update()
            self._pintar_nome(chave)


# ============================================================================ arquivo

class SeletorArquivo(QFrame):
    """Área para soltar o arquivo ou clicar em Selecionar; mostra nome e tamanho."""
    escolhido = Signal(str)

    def __init__(self, resumo_arquivo):
        super().__init__()
        self.setObjectName("SoltarArquivo")
        self.setAcceptDrops(True)
        self._resumo = resumo_arquivo
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 12, 12)
        lay.setSpacing(12)
        self._icone = QLabel()
        self._icone.setFixedSize(34, 34)
        self._icone.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._icone)
        textos = QVBoxLayout()
        textos.setSpacing(1)
        self.nome = rotulo("Arraste o arquivo para cá", "Rotulo")
        self.sub = rotulo("ou clique em Selecionar · PDF, ZIP, planilhas…", "Dica")
        textos.addWidget(self.nome)
        textos.addWidget(self.sub)
        lay.addLayout(textos, 1)
        self.botao = Botao("Selecionar…", "secundario", "upload", self._escolher)
        lay.addWidget(self.botao)
        self.caminho = ""
        _COM_ICONE.add(self)
        self.redesenhar_icone()

    def redesenhar_icone(self) -> None:
        self._icone.setStyleSheet(f"background: {Tema.cor('azul_suave')}; border-radius: 8px;")
        self._icone.setPixmap(icones.pixmap("anexo", Tema.cor("azul_texto"), 18))

    def _escolher(self) -> None:
        caminho, _ = QFileDialog.getOpenFileName(self, "Selecione o arquivo do claim")
        if caminho:
            self.definir(caminho)
            self.escolhido.emit(caminho)

    def definir(self, caminho: str) -> None:
        self.caminho = caminho
        if caminho:
            resumo = self._resumo(caminho) or Path(caminho).name
            nome, _, tamanho = resumo.partition(" · ")
            self.nome.setText(nome)
            self.sub.setText(f"{tamanho} · {Path(caminho).parent}" if tamanho else str(Path(caminho).parent))
            self.botao.setText("Trocar…")
        else:
            self.nome.setText("Arraste o arquivo para cá")
            self.sub.setText("ou clique em Selecionar · PDF, ZIP, planilhas…")
            self.botao.setText("Selecionar…")

    def sem_anexo(self, ativo: bool) -> None:
        self.setEnabled(not ativo)
        if ativo:
            self.nome.setText("Sem anexo")
            self.sub.setText("O documento ZDC não será criado para este claim")
        else:
            self.definir(self.caminho)

    def set_erro(self, erro: bool) -> None:
        self.setProperty("erro", erro)
        repolir(self)

    def dragEnterEvent(self, e):  # noqa: N802
        if self.isEnabled() and e.mimeData().hasUrls() and len(e.mimeData().urls()) == 1:
            e.acceptProposedAction()
            self.setProperty("ativo", True)
            repolir(self)

    def dragLeaveEvent(self, _e):  # noqa: N802
        self.setProperty("ativo", False)
        repolir(self)

    def dropEvent(self, e):  # noqa: N802
        self.setProperty("ativo", False)
        repolir(self)
        url = e.mimeData().urls()[0]
        if url.isLocalFile():
            self.definir(url.toLocalFile())
            self.escolhido.emit(url.toLocalFile())


class EstadoVazio(QWidget):
    def __init__(self, icone: str, titulo: str, texto: str = ""):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 36, 20, 36)
        lay.setSpacing(6)
        lay.setAlignment(Qt.AlignCenter)
        self._nome = icone
        self._icone = QLabel()
        self._icone.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._icone, 0, Qt.AlignCenter)
        t = rotulo(titulo, "CardTitulo")
        t.setAlignment(Qt.AlignCenter)
        lay.addWidget(t)
        if texto:
            d = rotulo(texto, "Dica", quebra=True)
            d.setAlignment(Qt.AlignCenter)
            lay.addWidget(d)
        _COM_ICONE.add(self)
        self.redesenhar_icone()

    def redesenhar_icone(self) -> None:
        self._icone.setPixmap(icones.pixmap(self._nome, Tema.cor("texto_3"), 32))


def aparecer(widget: QWidget, duracao: int = 160) -> None:
    """Transição suave entre telas (opacidade 0 -> 1). O efeito é removido no fim (desempenho)."""
    efeito = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(efeito)
    anim = QPropertyAnimation(efeito, b"opacity", widget)
    anim.setDuration(duracao)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.OutCubic)
    anim.finished.connect(lambda: widget.setGraphicsEffect(None))
    anim.start()
    widget._anim_aparecer = anim


def esvaziar(layout) -> None:
    """Tira e apaga todos os itens de um layout (sem deixar widget 'fantasma' na tela até o deleteLater)."""
    while layout.count():
        item = layout.takeAt(0)
        if item.widget() is not None:
            w = item.widget()
            w.hide()
            w.setParent(None)
            w.deleteLater()
        elif item.layout() is not None:
            esvaziar(item.layout())
