# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Painel inicial: saudação, conexão com o SAP, números reais do histórico e últimas atividades."""

from __future__ import annotations

import getpass
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from controlador import ROTULO_ESTADO, TOM_ESTADO

from ..componentes import Badge, Botao, Card, EstadoVazio, Indicador, divisor, esvaziar, rotulo
from ..dados import Historico, operacao_claim
from .base import Pagina


def saudacao(agora: datetime | None = None) -> str:
    hora = (agora or datetime.now()).hour
    return "Bom dia" if hora < 12 else ("Boa tarde" if hora < 18 else "Boa noite")


class PaginaPainel(Pagina):
    titulo = "Painel"
    subtitulo = ""

    def __init__(self, janela):
        super().__init__(janela)
        self.hist = Historico(janela.caminho_db)
        topo = QHBoxLayout()
        textos = QVBoxLayout()
        textos.setSpacing(2)
        self.ola = rotulo("", "TituloPagina")
        self.ola_sub = rotulo("Resumo das automações feitas neste computador", "SubtituloPagina")
        textos.addWidget(self.ola)
        textos.addWidget(self.ola_sub)
        topo.addLayout(textos, 1)
        topo.addWidget(Botao("Novo claim", "primario", "mais", lambda: janela.ir("claim")), 0, Qt.AlignBottom)
        if self.cfg.cotacao:
            topo.addWidget(Botao("Nova cotação", "secundario", "cotacao", lambda: janela.ir("cotacao")), 0,
                           Qt.AlignBottom)
        self.lay.addLayout(topo)

        grade = QGridLayout()
        grade.setSpacing(16)
        self.i_operacoes = Indicador("Operações registradas", "historico", "info")
        self.i_claims = Indicador("Claims concluídos", "check", "ok")
        self.i_pendentes = Indicador("Pendências", "pendencia", "atencao")
        self.i_falhas = Indicador("Falhas (7 dias)", "alerta", "erro")
        for i, w in enumerate((self.i_operacoes, self.i_claims, self.i_pendentes, self.i_falhas)):
            grade.addWidget(w, 0, i)
        self.lay.addLayout(grade)

        linha = QHBoxLayout()
        linha.setSpacing(18)
        self.card_atividades = Card("Últimas atividades", "Claims e cotações mais recentes")
        self.card_atividades.cabecalho.addWidget(
            Botao("Ver histórico", "fantasma", "seta", lambda: janela.ir("historico")), 0, Qt.AlignTop)
        self.lista = QVBoxLayout()
        self.lista.setSpacing(0)
        self.card_atividades.corpo.addLayout(self.lista)
        self.card_atividades.corpo.addStretch(1)      # sobra de altura vai para baixo, não entre título e lista
        linha.addWidget(self.card_atividades, 3)

        lado = QVBoxLayout()
        lado.setSpacing(18)
        self.card_sap = Card("Conexão com o SAP")
        self.sap_estado = Badge("Verificando…", "neutro")
        self.card_sap.cabecalho.addWidget(self.sap_estado, 0, Qt.AlignTop)
        self.sap_detalhe = rotulo("", "Dica", quebra=True)
        self.card_sap.add(self.sap_detalhe)
        g = QGridLayout()
        g.setVerticalSpacing(6)
        g.addWidget(rotulo("Sistema permitido", "Dica"), 0, 0)
        g.addWidget(rotulo(self.cfg.sistema), 0, 1, Qt.AlignRight)
        g.addWidget(rotulo("Mandante", "Dica"), 1, 0)
        g.addWidget(rotulo(self.cfg.mandante), 1, 1, Qt.AlignRight)
        self.card_sap.corpo.addLayout(g)
        self.card_sap.add(Botao("Verificar conexão", "secundario", "atualizar", janela.verificar_sap))
        lado.addWidget(self.card_sap)
        self.card_pend = Card("Atenção", "Execuções aguardando decisão")
        self.pend_texto = rotulo("", "Dica", quebra=True)
        self.card_pend.add(self.pend_texto)
        self.card_pend.add(Botao("Abrir pendências", "secundario", "pendencia", lambda: janela.ir("pendencias")))
        lado.addWidget(self.card_pend)
        lado.addStretch(1)
        linha.addLayout(lado, 2)
        self.lay.addLayout(linha)
        self.lay.addStretch(1)

    def ao_mostrar(self) -> None:
        usuario = self.janela.usuario_sap or getpass.getuser()
        self.ola.setText(f"{saudacao()}, {usuario}")
        try:
            n = self.hist.indicadores()
        except Exception as erro:  # noqa: BLE001
            self.ola_sub.setText(f"Não foi possível ler o histórico: {erro}")
            return
        self.i_operacoes.definir(n["operacoes"], f"{n['operacoes_teste']} em simulação ou ensaio")
        self.i_claims.definir(n["claims_concluidos"], f"{n['cotacoes_concluidas']} cotação(ões) criadas"
                              if self.cfg.cotacao else "gravados no SAP")
        self.i_pendentes.definir(n["pendentes"], f"{n['pendentes_claim']} claim · {n['pendentes_cotacao']} cotação")
        self.i_falhas.definir(n["falhas_7d"], "falhas nos últimos 7 dias")
        self.pend_texto.setText("Nenhuma execução pendente." if not n["pendentes"] else
                                f"{n['pendentes']} execução(ões) precisam ser conferidas no SAP.")
        self._listar(n["ultimas"])

    def _listar(self, ultimas) -> None:
        esvaziar(self.lista)
        if not ultimas:
            self.lista.addWidget(EstadoVazio("historico", "Ainda não há atividades",
                                             "Crie um claim ou uma cotação para começar."))
            return
        for i, (origem, r) in enumerate(ultimas):
            if i:
                self.lista.addWidget(divisor())
            self.lista.addWidget(self._linha(origem, r))

    def _linha(self, origem: str, r) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 10, 0, 10)
        textos = QVBoxLayout()
        textos.setSpacing(2)
        if origem == "claim":
            titulo = f"{operacao_claim(r)} · {r.ordem}/{r.item or 'nova'}"
            sub = f"{r.tipo} · nota {r.numero_nota}" if r.numero_nota else r.tipo
        else:
            titulo = f"Cotação · {r.cliente or r.tipo} / {r.projeto}"
            sub = f"nº {r.numero}" if r.numero else r.tipo
        quando = datetime.fromisoformat(r.criado_em).strftime("%d/%m %H:%M")
        if r.modo in ("SIMULACAO", "ENSAIO"):
            sub += f" · {r.modo.lower().replace('simulacao', 'simulação')}"
        textos.addWidget(rotulo(titulo))
        textos.addWidget(rotulo(f"{quando} · {sub}", "Dica"))
        lay.addLayout(textos, 1)
        lay.addWidget(Badge(ROTULO_ESTADO.get(r.estado, r.estado.value), TOM_ESTADO.get(r.estado, "neutro")))
        return w

    def sap(self, situacao: str, detalhe: str) -> None:
        if situacao == "verificando":
            self.sap_estado.definir("Verificando…", "neutro")
            self.sap_detalhe.setText("")
        elif situacao == "ok":
            self.sap_estado.definir("Conectado", "ok")
            self.sap_detalhe.setText(detalhe)
        else:
            self.sap_estado.definir("Indisponível", "erro")
            self.sap_detalhe.setText(detalhe)
