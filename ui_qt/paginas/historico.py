# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Histórico de claims e cotações: pesquisa, filtros por período e status, ordenação e eventos."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QPlainTextEdit, QStackedWidget, QVBoxLayout

from controlador import ROTULO_ESTADO, ROTULO_MODO, TOM_ESTADO
from pastas import nome_comparavel

from .. import icones
from ..componentes import Badge, Botao, Card, Segmentado, esvaziar, rotulo
from ..dados import GRUPOS, PERIODOS, Historico, dentro_do_periodo, linha_claim, linha_cot, operacao_claim
from ..tabela import Tabela
from ..tema import Tema
from .base import Pagina

COLUNAS_CLAIM = [("Data e horário", 140), ("Operação", 140), ("Ordem", 100), ("Item", 60), ("Modo", 100),
                 ("Nota", 110), ("Status", 190), ("Duração", 70)]
COLUNAS_COT = [("Data e horário", 140), ("Cliente", 170), ("Projeto", 160), ("Cotação", 100), ("Linhas", 150),
               ("Modo", 90), ("Status", 200), ("Tipo", 90)]


class PaginaHistorico(Pagina):
    titulo = "Histórico"
    subtitulo = "Tudo o que a automação fez neste computador"

    def __init__(self, janela):
        super().__init__(janela, rolagem=False)
        self.hist = Historico(janela.caminho_db)
        filtros = QHBoxLayout()
        filtros.setSpacing(10)
        opcoes = ["Claims"] + (["Cotações"] if self.cfg.cotacao else [])
        self.qual = Segmentado(opcoes)
        self.qual.set("Claims")
        self.qual.mudou.connect(lambda _: self._trocar())
        filtros.addWidget(self.qual)
        self.busca = QLineEdit()
        self.busca.setPlaceholderText("Pesquisar por ordem, item, nota, cliente, projeto…")
        self.busca.setClearButtonEnabled(True)
        self.busca.addAction(icones.icone("busca", Tema.cor("texto_3")), QLineEdit.LeadingPosition)
        self.busca.textChanged.connect(lambda _: self._filtrar())
        filtros.addWidget(self.busca, 1)
        self.periodo = QComboBox()
        self.periodo.addItems(list(PERIODOS))
        self.periodo.setCurrentText("Últimos 30 dias")
        self.periodo.currentIndexChanged.connect(lambda _: self._filtrar())
        filtros.addWidget(self.periodo)
        self.status = QComboBox()
        self.status.addItems(["Todos os status"] + list(GRUPOS))
        self.status.currentIndexChanged.connect(lambda _: self._filtrar())
        filtros.addWidget(self.status)
        filtros.addWidget(Botao("Atualizar", "secundario", "atualizar", self.ao_mostrar))
        self.lay.addLayout(filtros)

        corpo = QHBoxLayout()
        corpo.setSpacing(18)
        self.pilha = QStackedWidget()
        self.t_claim = Tabela(COLUNAS_CLAIM, 6, ("historico", "Nenhuma execução encontrada",
                                                 "Mude o período ou o filtro."))
        self.t_cot = Tabela(COLUNAS_COT, 6, ("cotacao", "Nenhuma cotação encontrada", "Mude o período ou o filtro."))
        self.pilha.addWidget(self.t_claim)
        self.pilha.addWidget(self.t_cot)
        self.t_claim.selecionou.connect(self._detalhar)
        self.t_cot.selecionou.connect(self._detalhar)
        self.t_cot.duplo_clique.connect(lambda c: self._claim_da_cotacao(c))
        corpo.addWidget(self.pilha, 1)

        self.painel = Card("Detalhes", "Selecione uma linha")
        self.painel.setFixedWidth(330)
        self.selo = Badge()
        self.painel.cabecalho.addWidget(self.selo, 0, Qt.AlignTop)
        self.campos = QVBoxLayout()
        self.campos.setSpacing(6)
        self.painel.corpo.addLayout(self.campos)
        self.painel.add(rotulo("Eventos da execução", "Rotulo"))
        self.eventos = QPlainTextEdit()
        self.eventos.setObjectName("Mono")
        self.eventos.setReadOnly(True)
        self.painel.add(self.eventos, 1)
        self.acoes = QHBoxLayout()
        self.btn_claim = Botao("Criar claim desta cotação", "primario", "mais",
                               lambda: self._claim_da_cotacao(self.t_cot.selecionado()))
        self.acoes.addWidget(self.btn_claim)
        self.painel.corpo.addLayout(self.acoes)
        self.btn_claim.setVisible(False)
        corpo.addWidget(self.painel)
        self.lay.addLayout(corpo, 1)
        self._claims, self._cots = [], []

    def ao_mostrar(self) -> None:
        try:
            self._claims = self.hist.claims()
            self._cots = self.hist.cotacoes() if self.cfg.cotacao else []
        except Exception as erro:  # noqa: BLE001
            from .. import dialogos
            dialogos.erro(self, "Histórico", f"Não foi possível ler o histórico:\n{erro}")
            return
        self.t_claim.definir([linha_claim(e) for e in self._claims])
        self.t_cot.definir([linha_cot(c) for c in self._cots])
        self._filtrar()

    def _trocar(self) -> None:
        self.pilha.setCurrentWidget(self.t_claim if self.qual.get() == "Claims" else self.t_cot)
        self._detalhar(self.pilha.currentWidget().selecionado())

    def _filtrar(self) -> None:
        palavras = nome_comparavel(self.busca.text()).split()
        periodo, status = self.periodo.currentText(), self.status.currentText()
        grupo = GRUPOS.get(status)

        def aceita(dado) -> bool:
            if dado is None:
                return False
            if not dentro_do_periodo(dado.criado_em, periodo):
                return False
            if grupo is not None and dado.estado not in grupo:
                return False
            if not palavras:
                return True
            campos = [getattr(dado, n, "") or "" for n in ("id", "ordem", "item", "numero_nota", "tipo", "cliente",
                                                           "projeto", "numero", "pais", "regiao")]
            alvo = nome_comparavel(" ".join(str(c) for c in campos))
            return all(p in alvo for p in palavras)

        self.t_claim.aplicar_filtro(aceita)
        self.t_cot.aplicar_filtro(aceita)

    def _limpar_campos(self) -> None:
        esvaziar(self.campos)

    def _campo(self, nome: str, valor: str) -> None:
        linha = QHBoxLayout()
        linha.addWidget(rotulo(nome, "Dica"))
        linha.addStretch(1)
        v = rotulo(valor or "—")
        v.setTextInteractionFlags(Qt.TextSelectableByMouse)
        linha.addWidget(v)
        self.campos.addLayout(linha)

    def _detalhar(self, dado) -> None:
        self._limpar_campos()
        self.btn_claim.setVisible(False)
        if dado is None:
            self.selo.definir("")
            self.painel.sub.setText("Selecione uma linha")
            self.eventos.clear()
            return
        self.selo.definir(ROTULO_ESTADO.get(dado.estado, dado.estado.value), TOM_ESTADO.get(dado.estado, "neutro"))
        if hasattr(dado, "numero_nota"):
            self.painel.sub.setText(dado.id)
            self._campo("Operação", operacao_claim(dado))
            self._campo("Tipo", dado.tipo)
            self._campo("Ordem / item", f"{dado.ordem} / {dado.item or 'nova'}")
            self._campo("Modo", ROTULO_MODO.get(dado.modo, dado.modo))
            self._campo("Nota", dado.numero_nota or "")
            self._campo("Documento ZDC", dado.documento_dms or "")
            self._campo("Anexo", dado.arquivo_nome or "")
            self._campo("Usuário SAP", dado.sap_usuario or "")
            eventos = self.hist.eventos_claim(dado.id)
        else:
            self.painel.sub.setText(dado.id)
            self._campo("Cliente", dado.cliente or "")
            self._campo("Projeto", dado.projeto)
            self._campo("Cotação", dado.numero or "")
            self._campo("Modo", ROTULO_MODO.get(dado.modo, dado.modo))
            self._campo("Pasta", "sim" if dado.pasta else "")
            eventos = self.hist.eventos_cotacao(dado.id)
            self.btn_claim.setVisible(bool(dado.numero and dado.lista_linhas))
        linhas = []
        nomes = {e.value: r for e, r in ROTULO_ESTADO.items()}
        for momento, tipo, de, para, detalhe in eventos:
            hora = datetime.fromisoformat(momento).strftime("%H:%M:%S")
            mudanca = f"→ {nomes.get(para, para)}" if para else tipo.replace("_", " ").capitalize()
            linhas.append(f"{hora}  {mudanca}" + (f"\n          {detalhe}" if detalhe else ""))
        self.eventos.setPlainText("\n".join(linhas) or "Sem eventos registrados.")

    def _claim_da_cotacao(self, registro) -> None:
        from .. import dialogos
        if registro is None:
            dialogos.informar(self, "Cotações", "Selecione uma cotação na lista.")
            return
        if not registro.numero or not registro.lista_linhas:
            dialogos.informar(self, "Cotações", "Esta cotação não tem número/linhas registrados.")
            return
        linha = registro.lista_linhas[0]
        if len(registro.lista_linhas) > 1:
            opcoes = [f"{l['item']} · {l['equipamento']}" for l in registro.lista_linhas]
            escolha = dialogos.escolher(self, "Criar claim", "Qual item da cotação?", opcoes)
            if escolha is None:
                return
            linha = registro.lista_linhas[opcoes.index(escolha)]
        self.janela.pagina_claim.preparar_claim(registro.numero, linha["item"], linha["rota"])
