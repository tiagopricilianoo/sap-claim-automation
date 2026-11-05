# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Janela principal: barra lateral, topo com o estado do SAP e as páginas."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow,
                               QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from config import Settings
from controlador import ROTULO_ESTADO, Executor

from . import dialogos, icones
from .componentes import Botao, aparecer, atualizar_icones, repolir, rotulo
from .dados import Historico
from .paginas.claim import PaginaClaim
from .paginas.configuracoes import PaginaConfiguracoes, versao_instalada
from .paginas.cotacao import PaginaCotacao
from .paginas.execucao import PaginaExecucao
from .paginas.historico import PaginaHistorico
from .paginas.painel import PaginaPainel
from .paginas.pendencias import PaginaPendencias
from .ponte import PonteExecutor, TarefaRede
from .tema import PALETAS, Tema, qss

log = logging.getLogger("claim.ui_qt")
RAIZ = Path(__file__).resolve().parent.parent

MENU = (  # chave, rótulo, ícone, seção
    ("painel", "Painel", "painel", "Início"),
    ("claim", "Novo claim", "claim", "Criar"),
    ("cotacao", "Nova cotação", "cotacao", "Criar"),
    ("execucao", "Execução", "execucao", "Acompanhar"),
    ("historico", "Histórico", "historico", "Acompanhar"),
    ("pendencias", "Pendências", "pendencia", "Acompanhar"),
    ("configuracoes", "Configurações", "config", "Sistema"),
)


class ItemMenu(QPushButton):
    def __init__(self, texto: str, icone: str):
        super().__init__(texto)
        self.setObjectName("ItemMenu")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setIconSize(QSize(18, 18))
        self._icone = icone
        self.contador = QLabel(self)
        self.contador.setObjectName("Contador")
        self.contador.setAlignment(Qt.AlignCenter)
        self.contador.setVisible(False)
        self.toggled.connect(lambda _: self.redesenhar_icone())
        self.redesenhar_icone()

    def redesenhar_icone(self) -> None:
        self.setIcon(icones.icone(self._icone, Tema.cor("azul_texto" if self.isChecked() else "texto_2"), 18))

    def definir_contador(self, n: int) -> None:
        self.contador.setText(str(n))
        self.contador.setVisible(n > 0)
        self.contador.adjustSize()
        self._posicionar()

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        self._posicionar()

    def _posicionar(self) -> None:
        self.contador.move(self.width() - self.contador.width() - 10, (self.height() - self.contador.height()) // 2)


class JanelaPrincipal(QMainWindow):
    def __init__(self, settings: Settings, executor: Executor | None = None):
        super().__init__()
        self.cfg = settings
        # Produção: modo AUTOMATICO no settings.ini. Sem seletor de modo e sem confirmação a cada claim.
        self.producao = settings.modo == "AUTOMATICO"
        self.caminho_db = settings.pasta_dados / "historico.db"
        self.executor = executor or Executor(settings, self.caminho_db)
        self.ponte = PonteExecutor(self.executor, self)
        self.preferencias = QSettings("AutomacaoComercial", "InterfaceQt")
        self.tema_atual = str(self.preferencias.value("tema", "claro"))
        self.usuario_sap = ""
        self.fechando = False
        self._pode_fechar = False
        self._ultimo_fim = None
        self._espera = 0

        self.setWindowTitle("Automação Comercial · Cotações e Claims")
        self.resize(1360, 860)
        self.setMinimumSize(1120, 720)
        logo = RAIZ / "assets" / "logo_80.png"
        if logo.exists():
            self.setWindowIcon(QIcon(str(logo)))
        self._aplicar_qss()

        raiz = QWidget()
        raiz.setObjectName("Raiz")
        self.setCentralWidget(raiz)
        lay = QHBoxLayout(raiz)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._sidebar())

        direita = QVBoxLayout()
        direita.setContentsMargins(0, 0, 0, 0)
        direita.setSpacing(0)
        direita.addWidget(self._topo())
        self.pilha = QStackedWidget()
        direita.addWidget(self.pilha, 1)
        lay.addLayout(direita, 1)

        self.paginas: dict[str, QWidget] = {}
        self.pagina_painel = self._add("painel", PaginaPainel(self))
        self.pagina_claim = self._add("claim", PaginaClaim(self))
        self.pagina_cotacao = self._add("cotacao", PaginaCotacao(self)) if settings.cotacao else None
        self.pagina_execucao = self._add("execucao", PaginaExecucao(self))
        self.pagina_historico = self._add("historico", PaginaHistorico(self))
        self.pagina_pendencias = self._add("pendencias", PaginaPendencias(self))
        self.pagina_config = self._add("configuracoes", PaginaConfiguracoes(self))

        self.ponte.etapa.connect(self._etapa)
        self.ponte.fim.connect(self._fim)
        self.ponte.sap.connect(self._sap)
        self.ir("painel")
        self.atualizar_dados()
        QTimer.singleShot(300, self.verificar_sap)
        QTimer.singleShot(2500, self._verificar_atualizacao)

    # ------------------------------------------------------------------ montagem

    def _aplicar_qss(self) -> None:
        Tema.atual = PALETAS.get(self.tema_atual, PALETAS["claro"])
        pasta = Path(self.cfg.pasta_dados)
        try:
            pasta.mkdir(parents=True, exist_ok=True)
            check = icones.salvar_png("check", "#FFFFFF", pasta / "ui_check.png")
        except OSError:
            check = ""
        QApplication.instance().setStyleSheet(qss(Tema.atual, check))

    def _sidebar(self) -> QWidget:
        barra = QFrame()
        barra.setObjectName("Sidebar")
        barra.setFixedWidth(240)
        lay = QVBoxLayout(barra)
        lay.setContentsMargins(14, 18, 14, 16)
        lay.setSpacing(2)
        marca = QHBoxLayout()
        marca.setSpacing(10)
        logo = RAIZ / "assets" / "logo_80.png"
        if logo.exists():
            imagem = QLabel()
            pm = QPixmap(str(logo)).scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            pm.setDevicePixelRatio(2.0)
            imagem.setPixmap(pm)
            marca.addWidget(imagem)
        textos = QVBoxLayout()
        textos.setSpacing(0)
        textos.addWidget(rotulo("Automação", "MarcaTitulo"))
        textos.addWidget(rotulo(f"Comercial · {versao_instalada()}", "MarcaSub"))
        marca.addLayout(textos, 1)
        lay.addLayout(marca)
        lay.addSpacing(12)

        self.menu: dict[str, ItemMenu] = {}
        grupo = QButtonGroup(self)
        grupo.setExclusive(True)
        secao = ""
        for chave, texto, icone, sec in MENU:
            if chave == "cotacao" and not self.cfg.cotacao:
                continue
            if sec != secao:
                lay.addWidget(rotulo(sec.upper(), "SecaoMenu"))
                secao = sec
            item = ItemMenu(texto, icone)
            item.clicked.connect(lambda _=False, c=chave: self.ir(c))
            grupo.addButton(item)
            lay.addWidget(item)
            self.menu[chave] = item
        lay.addStretch(1)
        self.btn_tema = Botao("", "fantasma", "lua" if self.tema_atual == "claro" else "sol", self._alternar_tema)
        self.btn_tema.setText("Tema escuro" if self.tema_atual == "claro" else "Tema claro")
        lay.addWidget(self.btn_tema)
        return barra

    def _topo(self) -> QWidget:
        topo = QWidget()
        topo.setObjectName("Topo")
        lay = QHBoxLayout(topo)
        lay.setContentsMargins(32, 22, 32, 10)
        textos = QVBoxLayout()
        textos.setSpacing(2)
        self.titulo = rotulo("", "TituloPagina")
        self.subtitulo = rotulo("", "SubtituloPagina")
        textos.addWidget(self.titulo)
        textos.addWidget(self.subtitulo)
        lay.addLayout(textos, 1)
        self.chip_sap = QLabel("SAP: verificando…")
        self.chip_sap.setObjectName("ChipSap")
        self.chip_sap.setProperty("tom", "neutro")
        lay.addWidget(self.chip_sap, 0, Qt.AlignVCenter)
        lay.addWidget(Botao("Verificar", "secundario", "atualizar", self.verificar_sap), 0, Qt.AlignVCenter)
        return topo

    def _add(self, chave: str, pagina) -> QWidget:
        self.paginas[chave] = pagina
        self.pilha.addWidget(pagina)
        return pagina

    # ------------------------------------------------------------------ navegação e dados

    def ir(self, chave: str) -> None:
        pagina = self.paginas.get(chave)
        if pagina is None:
            return
        if chave in self.menu:
            self.menu[chave].setChecked(True)
        self.titulo.setText(pagina.titulo)
        self.subtitulo.setText(pagina.subtitulo)
        self.titulo.setVisible(chave != "painel")
        self.subtitulo.setVisible(bool(pagina.subtitulo) and chave != "painel")
        if self.pilha.currentWidget() is not pagina:
            self.pilha.setCurrentWidget(pagina)
            aparecer(pagina)
        try:
            pagina.ao_mostrar()
        except Exception:  # noqa: BLE001
            log.exception("ao mostrar %s", chave)

    def atualizar_dados(self) -> None:
        hist = Historico(self.caminho_db)
        try:
            n_claim = len(hist.pendencias_claim())
            n_cot = len(hist.pendencias_cotacao()) if self.cfg.cotacao else 0
        except Exception as erro:  # noqa: BLE001
            dialogos.erro(self, "Histórico", f"Não foi possível ler o histórico:\n{erro}")
            return
        self.menu["pendencias"].definir_contador(n_claim + n_cot)
        self.pagina_claim.mostrar_pendencias(n_claim)
        if self.pagina_cotacao is not None:
            self.pagina_cotacao.mostrar_pendentes(n_cot)
        atual = self.pilha.currentWidget()
        if atual in (self.pagina_painel, self.pagina_historico, self.pagina_pendencias):
            atual.ao_mostrar()

    # ------------------------------------------------------------------ tema

    def _alternar_tema(self) -> None:
        self.aplicar_tema("escuro" if self.tema_atual == "claro" else "claro")

    def aplicar_tema(self, tema: str) -> None:
        self.tema_atual = tema
        self.preferencias.setValue("tema", tema)
        self._aplicar_qss()
        atualizar_icones()
        for item in self.menu.values():
            item.redesenhar_icone()
        self.btn_tema._icone = "lua" if tema == "claro" else "sol"
        self.btn_tema.setText("Tema escuro" if tema == "claro" else "Tema claro")
        self.btn_tema.redesenhar_icone()
        self.pagina_config.tema.set("Escuro" if tema == "escuro" else "Claro")
        for pagina in self.paginas.values():
            pagina.ao_mudar_tema()
            for tempo in pagina.findChildren(QWidget):
                if hasattr(tempo, "redesenhar") and callable(tempo.redesenhar):
                    tempo.redesenhar()
            pagina.update()

    # ------------------------------------------------------------------ SAP e eventos

    def verificar_sap(self) -> None:
        if self.executor.ocupado:
            dialogos.informar(self, "Verificar SAP", "Aguarde a execução em andamento terminar.")
            return
        self._chip("neutro", "SAP: verificando…")
        self.pagina_painel.sap("verificando", "")
        try:
            self.executor.verificar_sap()
        except RuntimeError as exc:
            dialogos.informar(self, "Verificar SAP", str(exc))

    def _chip(self, tom: str, texto: str) -> None:
        self.chip_sap.setText(texto)
        self.chip_sap.setProperty("tom", tom)
        repolir(self.chip_sap)

    def _sap(self, situacao: str, detalhe: str) -> None:
        if situacao == "ok":
            self._chip("ok", f"●  SAP conectado · {detalhe}")
            partes = detalhe.split("·")
            self.usuario_sap = partes[-1].strip() if len(partes) > 1 else ""
        else:
            self._chip("erro", "●  SAP indisponível")
        self.pagina_painel.sap(situacao, detalhe)
        if self.pilha.currentWidget() is self.pagina_painel:
            self.pagina_painel.ao_mostrar()

    def _etapa(self, origem: str, chave: str, situacao: str, detalhe: str) -> None:
        if origem == "cotacao" and self.pagina_cotacao is not None:
            self.pagina_cotacao.marcar_etapa(chave, situacao, detalhe)
        elif origem == "claim":
            self.pagina_claim.marcar_etapa(chave, situacao, detalhe)
        self.pagina_execucao.marcar(origem, chave, situacao, detalhe)

    def _fim(self, evento) -> None:
        r = evento.resultado
        self._ultimo_fim = (getattr(r, "estado", None), getattr(r, "mensagem", None) or evento.detalhe)
        self.pagina_execucao.terminou(evento)
        if evento.origem == "cotacao" and self.pagina_cotacao is not None:
            self.pagina_cotacao.terminou(evento)
        else:
            self.pagina_claim.terminou(evento)
        self.atualizar_dados()

    # ------------------------------------------------------------------ encerramento

    def _ocupado(self) -> bool:
        return self.executor.ocupado or any(t.ativo for t in TarefaRede.em_andamento)

    def closeEvent(self, evento):  # noqa: N802
        if self._pode_fechar:
            evento.accept()
            return
        if self.fechando:
            evento.ignore()
            return
        if self._ocupado() and not dialogos.confirmar(
                self, "Execução em andamento",
                "Há uma execução (ou criação de pastas) em andamento. Deseja interromper e fechar?"):
            evento.ignore()
            return
        self.executor.interromper()
        if self._ocupado():
            # Matar a thread no meio de uma chamada ao SAP (ou da criação das pastas) deixaria o documento
            # sem registro no histórico. A parada é atendida no fim da etapa atual.
            evento.ignore()
            self.fechando = True
            self.setWindowTitle("Automação Comercial  ·  fechando: terminando a etapa atual…")
            dialogos.informar(self, "Fechando", "A execução vai parar no fim da etapa atual (pode levar alguns "
                              "segundos). O resultado aparece antes de o programa fechar.")
            self._ultimo_fim = None
            self._espera = 0
            self._fechar_quando_livre()
            return
        self._encerrar()
        evento.accept()

    def _fechar_quando_livre(self) -> None:
        self._espera += 1
        if self._ocupado():
            if self._espera % 600 == 0 and dialogos.confirmar(   # a cada ~2 minutos
                    self, "SAP sem resposta", "A etapa atual ainda não terminou (o SAP ou a rede podem estar "
                    "travados).\n\nFechar mesmo assim? Depois confira no SAP e resolva a execução em Pendências.",
                    padrao_nao=True):
                self._pode_fechar = True
                self.close()
                return
            QTimer.singleShot(200, self._fechar_quando_livre)
            return
        if self._ultimo_fim is None and self._espera < 25:      # o evento final ainda na fila
            QTimer.singleShot(200, self._fechar_quando_livre)
            return
        if self._ultimo_fim is not None:
            estado, mensagem = self._ultimo_fim
            titulo = ROTULO_ESTADO.get(estado, getattr(estado, "value", "Resultado")) if estado else "Resultado"
            dialogos.informar(self, f"Antes de fechar: {titulo}", mensagem or "Execução encerrada.")
        self._encerrar()
        self._pode_fechar = True
        self.close()

    def _verificar_atualizacao(self) -> None:
        try:
            from .atualizacao import verificar
            verificar(self)
        except Exception:  # noqa: BLE001 - nunca atrapalha o uso
            log.exception("verificar atualização")

    def fechar_para_atualizar(self) -> None:
        """Fecha para o script trocar o Python (só sem execução em andamento)."""
        self._encerrar()
        self._pode_fechar = True
        self.close()

    def _encerrar(self) -> None:
        try:
            self.executor.fechar_janela_mantida()
        except Exception:  # noqa: BLE001 - fechando
            log.exception("fechar janela mantida")
