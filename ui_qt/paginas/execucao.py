# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Acompanhamento da execução em andamento (ou da última): linha do tempo, registro e resultado."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPlainTextEdit, QStackedWidget

from claim_service import ETAPAS, etapas_do_modo
from controlador import ROTULO_ESTADO, ROTULO_MODO, TOM_ESTADO
from cotacao_service import ETAPAS_COTACAO, etapas_cotacao_do_modo

from ..componentes import Badge, Banner, Card, EstadoVazio, LinhaDoTempo, rotulo
from .base import Pagina


class PaginaExecucao(Pagina):
    titulo = "Execução"
    subtitulo = "Acompanhe cada etapa da automação em tempo real"

    def __init__(self, janela):
        super().__init__(janela)
        self.vazio = EstadoVazio("execucao", "Nenhuma execução nesta sessão",
                                 "Quando um claim ou uma cotação começar, as etapas aparecem aqui.")
        self.card_vazio = Card(sombra=True)
        self.card_vazio.add(self.vazio)
        self.lay.addWidget(self.card_vazio)

        esquerda, direita = self.colunas(1, 1)
        self.card_tempo = Card("Etapas")
        self.operacao = rotulo("", "CardSub")
        self.card_tempo.corpo.insertWidget(1, self.operacao)
        self.selo = Badge()
        self.card_tempo.cabecalho.addWidget(self.selo, 0, Qt.AlignTop)
        self.pilha = QStackedWidget()
        self.tempo_claim = LinhaDoTempo(ETAPAS)
        self.tempo_cotacao = LinhaDoTempo(ETAPAS_COTACAO)
        self.pilha.addWidget(self.tempo_claim)
        self.pilha.addWidget(self.tempo_cotacao)
        self.card_tempo.add(self.pilha)
        esquerda.addWidget(self.card_tempo)
        esquerda.addStretch(1)

        self.resultado = Banner("info", "Em andamento", "")
        self.resultado.setVisible(False)
        direita.addWidget(self.resultado)
        card_log = Card("Registro", "Mensagens da automação nesta execução")
        self.registro = QPlainTextEdit()
        self.registro.setObjectName("Mono")
        self.registro.setReadOnly(True)
        self.registro.setMinimumHeight(320)
        card_log.add(self.registro)
        direita.addWidget(card_log)
        direita.addStretch(1)
        self._origem = ""
        self._mostrar_conteudo(False)

    def _mostrar_conteudo(self, ativo: bool) -> None:
        self.card_vazio.setVisible(not ativo)
        self.card_tempo.setVisible(ativo)
        self.registro.parentWidget().setVisible(ativo)
        if not ativo:
            self.resultado.setVisible(False)

    def iniciar(self, origem: str, modo: str, linha_nova: bool, descricao: str) -> None:
        self._origem = origem
        self._mostrar_conteudo(True)
        if origem == "claim":
            ativas = [c for c, _ in etapas_do_modo(modo, linha_nova)]
            self.pilha.setCurrentWidget(self.tempo_claim)
            self.tempo_claim.preparar(ativas, f"não faz parte do modo {ROTULO_MODO.get(modo, modo)}")
        else:
            ativas = [c for c, _ in etapas_cotacao_do_modo(modo)]
            self.pilha.setCurrentWidget(self.tempo_cotacao)
            self.tempo_cotacao.preparar(ativas, "não faz parte do ensaio")
        self.operacao.setText(f"{descricao} · modo {ROTULO_MODO.get(modo, modo)}")
        self.selo.definir("Em andamento", "info")
        self.resultado.setVisible(False)
        self.registro.clear()
        self._log(f"Início: {descricao}")

    def _log(self, texto: str) -> None:
        self.registro.appendPlainText(f"{datetime.now():%H:%M:%S}  {texto}")

    def marcar(self, origem: str, chave: str, situacao: str, detalhe: str) -> None:
        if origem != self._origem:
            return
        tempo = self.tempo_claim if origem == "claim" else self.tempo_cotacao
        tempo.marcar(chave, situacao, detalhe)
        etapas = dict(ETAPAS if origem == "claim" else ETAPAS_COTACAO)
        nome = etapas.get(chave, chave)
        texto = {"ativo": "iniciada", "ok": "concluída", "falha": "FALHOU"}.get(situacao, situacao)
        self._log(f"{nome}: {texto}" + (f" · {detalhe}" if detalhe and situacao != "ativo" else ""))

    def terminou(self, evento) -> None:
        if evento.origem != self._origem and self._origem:
            return
        r = evento.resultado
        if r is None:
            self.selo.definir("Erro inesperado", "erro")
            self.resultado.definir("erro", "Erro inesperado", evento.detalhe)
            self._log(f"Erro inesperado: {evento.detalhe}")
        else:
            tom = TOM_ESTADO.get(r.estado, "atencao")
            rotulo_estado = ROTULO_ESTADO.get(r.estado, r.estado.value)
            self.selo.definir(rotulo_estado, tom)
            self.resultado.definir(tom if tom != "neutro" else "info", rotulo_estado, r.mensagem)
            self._log(f"Fim: {rotulo_estado} · {r.mensagem}")
        self.resultado.setVisible(True)

    def ao_mudar_tema(self) -> None:
        self.tempo_claim.redesenhar()
        self.tempo_cotacao.redesenhar()
