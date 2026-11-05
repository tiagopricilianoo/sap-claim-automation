# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Leitura do histórico para as telas (sempre dados reais do SQLite; nada inventado)."""

from __future__ import annotations

from datetime import datetime, timedelta

from controlador import ROTULO_ESTADO, ROTULO_MODO, TOM_ESTADO, linha_cotacao, pendencias
from state import Estado
from storage import Storage
from storage_cotacao import CotacaoStorage

GRUPOS = {
    "Concluídos": {Estado.CONCLUIDO, Estado.ENSAIO_CONCLUIDO},
    "Pendentes": {Estado.AGUARDANDO_CONFIRMACAO, Estado.REVISAO_NECESSARIA, Estado.EXECUTANDO,
                  Estado.PRONTO_PARA_EXECUCAO},
    "Falhas": {Estado.FALHA_RECUPERAVEL, Estado.FALHA_DEFINITIVA},
    "Não iniciados": {Estado.RECEBIDO, Estado.VALIDANDO},
}
PERIODOS = {"Hoje": 0, "Últimos 7 dias": 7, "Últimos 30 dias": 30, "Tudo": None}


def dentro_do_periodo(criado_em: str, periodo: str, agora: datetime | None = None) -> bool:
    dias = PERIODOS.get(periodo)
    if dias is None:
        return True
    agora = agora or datetime.now()
    inicio = datetime(agora.year, agora.month, agora.day) - timedelta(days=dias)
    return datetime.fromisoformat(criado_em) >= inicio


def operacao_claim(e) -> str:
    """Linha nova: a execução nasce sem item (o SAP numera) e registra a linha criada."""
    return "Linha nova + claim" if (e.linha_criada or not e.item) else "Claim"


def linha_claim(e) -> dict:
    quando = datetime.fromisoformat(e.criado_em)
    duracao = e.duracao_segundos
    return {
        "valores": [quando.strftime("%d/%m/%y %H:%M"), operacao_claim(e), e.ordem, e.item or "nova",
                    ROTULO_MODO.get(e.modo, e.modo), e.numero_nota or "—",
                    ROTULO_ESTADO.get(e.estado, e.estado.value),
                    f"{duracao:.0f}s" if duracao is not None else "—"],
        "ordem": [e.criado_em, operacao_claim(e), e.ordem, (e.item or "").zfill(6), e.modo, e.numero_nota or "",
                  e.estado.value, duracao if duracao is not None else -1],
        "tom": TOM_ESTADO.get(e.estado, "neutro"),
        "dado": e,
    }


def linha_cot(c) -> dict:
    quando, cliente, projeto, numero, itens, situacao, tipo = linha_cotacao(c)
    return {
        "valores": [datetime.fromisoformat(c.criado_em).strftime("%d/%m/%y %H:%M"), cliente, projeto, numero, itens,
                    ROTULO_MODO.get(c.modo, c.modo) if c.modo != "AUTOMATICO" else "Criar", situacao, tipo],
        "ordem": [c.criado_em, cliente, projeto, numero, itens, c.modo, c.estado.value, tipo],
        "tom": TOM_ESTADO.get(c.estado, "neutro"),
        "dado": c,
    }


class Historico:
    """Abre e fecha o banco a cada leitura (a thread de execução usa a própria conexão)."""

    def __init__(self, caminho_db):
        self.caminho = caminho_db

    def claims(self, limite: int = 2000):
        db = Storage(self.caminho)
        try:
            return db.recentes(limite)
        finally:
            db.close()

    def cotacoes(self, limite: int = 2000):
        if not self._tem_cotacao():
            return []
        db = CotacaoStorage(self.caminho)
        try:
            return db.recentes(limite)
        finally:
            db.close()

    def pendencias_claim(self):
        db = Storage(self.caminho)
        try:
            return pendencias(db)
        finally:
            db.close()

    def pendencias_cotacao(self):
        db = CotacaoStorage(self.caminho)
        try:
            return db.pendentes()
        finally:
            db.close()

    def eventos_claim(self, eid: str):
        db = Storage(self.caminho)
        try:
            return [(e.momento, e.tipo, e.de_estado, e.para_estado, e.detalhe) for e in db.eventos(eid)]
        finally:
            db.close()

    def eventos_cotacao(self, cid: str):
        db = CotacaoStorage(self.caminho)
        try:
            return [(l["momento"], l["tipo"], l["de_estado"], l["para_estado"], l["detalhe"]) for l in db.eventos(cid)]
        finally:
            db.close()

    def _tem_cotacao(self) -> bool:
        return True

    def indicadores(self, agora: datetime | None = None) -> dict:
        """Números do painel. Simulação e ensaio não contam como claim/cotação criada."""
        agora = agora or datetime.now()
        claims, cotacoes = self.claims(100000), self.cotacoes(100000)
        reais = [e for e in claims if e.modo not in ("SIMULACAO", "ENSAIO")]
        semana = agora - timedelta(days=7)
        falhas = [e for e in list(claims) + list(cotacoes)
                  if e.estado in GRUPOS["Falhas"] and datetime.fromisoformat(e.criado_em) >= semana]
        pend_claim, pend_cot = self.pendencias_claim(), self.pendencias_cotacao()
        return {
            "operacoes": len(claims) + len(cotacoes),
            "operacoes_teste": sum(1 for e in list(claims) + list(cotacoes) if e.modo in ("SIMULACAO", "ENSAIO")),
            "claims_concluidos": sum(1 for e in reais if e.estado == Estado.CONCLUIDO),
            "cotacoes_concluidas": sum(1 for c in cotacoes if c.estado == Estado.CONCLUIDO and c.modo == "AUTOMATICO"),
            "pendentes": len(pend_claim) + len(pend_cot),
            "pendentes_claim": len(pend_claim),
            "pendentes_cotacao": len(pend_cot),
            "falhas_7d": len(falhas),
            "ultimas": sorted([("claim", e) for e in claims[:8]] + [("cotacao", c) for c in cotacoes[:8]],
                              key=lambda x: x[1].criado_em, reverse=True)[:8],
        }
