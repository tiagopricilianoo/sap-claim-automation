# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Histórico local das cotações criadas pelo programa (mesmo banco SQLite dos claims).

Mesma regra dos claims: estado e evento sempre gravados juntos, e a máquina de
estados impede que uma gravação incerta volte a ser enviada.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, fields
from datetime import datetime
from pathlib import Path

from cotacao import CotacaoRequest
from pastas import nome_comparavel
from state import BLOQUEIAM_DUPLICIDADE, PENDENTES, TRANSICOES, Estado, validar_transicao
from storage import _Transacao, abrir_banco

ESQUEMA = """
CREATE TABLE IF NOT EXISTS cotacoes (
    id            TEXT PRIMARY KEY,
    criado_em     TEXT NOT NULL,
    atualizado_em TEXT NOT NULL,
    fim_em        TEXT,
    modo          TEXT NOT NULL,
    tipo          TEXT NOT NULL,
    regiao        TEXT,
    pais          TEXT,
    cliente       TEXT,
    projeto       TEXT NOT NULL,
    produto_a       INTEGER NOT NULL,
    produto_b       INTEGER NOT NULL,
    chave         TEXT NOT NULL,
    estado        TEXT NOT NULL,
    numero        TEXT,
    linhas        TEXT,
    pasta         TEXT,
    sap_usuario   TEXT,
    etapa_falha   TEXT,
    mensagem      TEXT
);
CREATE INDEX IF NOT EXISTS ix_cotacoes_chave ON cotacoes (chave);
CREATE TABLE IF NOT EXISTS cotacao_eventos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    cotacao_id  TEXT NOT NULL REFERENCES cotacoes(id),
    momento     TEXT NOT NULL,
    tipo        TEXT NOT NULL,
    de_estado   TEXT,
    para_estado TEXT,
    detalhe     TEXT
);
CREATE INDEX IF NOT EXISTS ix_cotacao_eventos ON cotacao_eventos (cotacao_id);
"""


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def chave_projeto(req: CotacaoRequest) -> str:
    return f"{req.tipo}|{nome_comparavel(req.cliente)}|{nome_comparavel(req.projeto)}"


@dataclass(frozen=True)
class CotacaoRegistro:
    id: str
    criado_em: str
    atualizado_em: str
    fim_em: str | None
    modo: str
    tipo: str
    regiao: str | None
    pais: str | None
    cliente: str | None
    projeto: str
    produto_a: int
    produto_b: int
    chave: str
    estado: Estado
    numero: str | None
    linhas: str | None
    pasta: str | None
    sap_usuario: str | None
    etapa_falha: str | None
    mensagem: str | None

    @property
    def request(self) -> CotacaoRequest:
        return CotacaoRequest(self.tipo, self.regiao or "", self.pais or "", self.cliente or "", self.projeto,
                              bool(self.produto_a), bool(self.produto_b))

    @property
    def lista_linhas(self) -> list[dict[str, str]]:
        return json.loads(self.linhas) if self.linhas else []


# Colunas acrescentadas depois da 1ª versão entram aqui (sempre opcionais), como em storage.COLUNAS_NOVAS:
# o banco de quem já usa o programa ganha a coluna ao abrir, sem perder nada.
COLUNAS_OPCIONAIS = {"fim_em": "TEXT", "regiao": "TEXT", "pais": "TEXT", "cliente": "TEXT", "numero": "TEXT",
                     "linhas": "TEXT", "pasta": "TEXT", "sap_usuario": "TEXT", "etapa_falha": "TEXT",
                     "mensagem": "TEXT"}


class CotacaoStorage:
    def __init__(self, caminho_db: Path | str):
        caminho_db = Path(caminho_db)
        caminho_db.parent.mkdir(parents=True, exist_ok=True)
        self._con = abrir_banco(caminho_db, ESQUEMA, "cotacoes", COLUNAS_OPCIONAIS)

    def close(self) -> None:
        self._con.close()

    # ------------------------------------------------------------------ escrita

    def criar(self, req: CotacaoRequest, modo: str) -> str:
        cid = "C" + uuid.uuid4().hex[:11].upper()
        agora = _agora()
        with self._transacao():
            self._con.execute(
                """INSERT INTO cotacoes (id, criado_em, atualizado_em, modo, tipo, regiao, pais, cliente, projeto,
                   produto_a, produto_b, chave, estado) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (cid, agora, agora, modo, req.tipo, req.regiao, req.pais, req.cliente, req.projeto,
                 int(req.produto_a), int(req.produto_b), chave_projeto(req), Estado.RECEBIDO.value),
            )
            self._evento(cid, "CRIACAO", None, Estado.RECEBIDO, f"modo={modo}")
        return cid

    def transitar(self, cid: str, novo: Estado, detalhe: str = "") -> None:
        with self._transacao():
            atual = self._estado(cid)
            validar_transicao(atual, novo)
            agora = _agora()
            fim = agora if not TRANSICOES[novo] else None
            self._con.execute(
                "UPDATE cotacoes SET estado = ?, atualizado_em = ?, fim_em = COALESCE(?, fim_em) WHERE id = ?",
                (novo.value, agora, fim, cid))
            self._evento(cid, "TRANSICAO", atual, novo, detalhe)

    def registrar_evento(self, cid: str, tipo: str, detalhe: str = "") -> None:
        with self._transacao():
            self._evento(cid, tipo, None, None, detalhe)

    def registrar_sessao(self, cid: str, usuario: str, sistema: str, mandante: str) -> None:
        self._atualizar(cid, sap_usuario=usuario)

    def registrar_falha(self, cid: str, etapa: str, mensagem: str) -> None:
        self._atualizar(cid, etapa_falha=etapa, mensagem=mensagem)
        self.registrar_evento(cid, "FALHA", f"{etapa}: {mensagem}")

    def registrar_numero(self, cid: str, numero: str, linhas: list[dict[str, str]]) -> None:
        self._atualizar(cid, numero=numero, linhas=json.dumps(linhas, ensure_ascii=False))
        self.registrar_evento(cid, "COTACAO", numero)

    def registrar_linhas(self, cid: str, linhas: list[dict[str, str]]) -> None:
        """Linhas lidas da tela antes de gravar (para criar o claim depois, mesmo sem confirmação)."""
        self._atualizar(cid, linhas=json.dumps(linhas, ensure_ascii=False))

    def registrar_pasta(self, cid: str, pasta: str) -> None:
        self._atualizar(cid, pasta=pasta)
        self.registrar_evento(cid, "PASTAS", pasta)

    # ------------------------------------------------------------------ leitura

    def obter(self, cid: str) -> CotacaoRegistro:
        linha = self._con.execute("SELECT * FROM cotacoes WHERE id = ?", (cid,)).fetchone()
        if linha is None:
            raise KeyError(f"Cotação não encontrada: {cid}")
        return _registro(linha)

    def eventos(self, cid: str) -> list[sqlite3.Row]:
        return self._con.execute("SELECT * FROM cotacao_eventos WHERE cotacao_id = ? ORDER BY id", (cid,)).fetchall()

    def duplicidades(self, req: CotacaoRequest, ignorar_id: str | None = None) -> list[CotacaoRegistro]:
        estados = [e.value for e in BLOQUEIAM_DUPLICIDADE]
        marcadores = ",".join("?" * len(estados))
        linhas = self._con.execute(
            f"SELECT * FROM cotacoes WHERE chave = ? AND estado IN ({marcadores}) AND id IS NOT ? "
            "AND modo != 'SIMULACAO' ORDER BY criado_em DESC",
            (chave_projeto(req), *estados, ignorar_id)).fetchall()
        return [_registro(l) for l in linhas]

    def pendentes(self) -> list[CotacaoRegistro]:
        estados = [e.value for e in PENDENTES] + [Estado.EXECUTANDO.value]
        marcadores = ",".join("?" * len(estados))
        linhas = self._con.execute(
            f"SELECT * FROM cotacoes WHERE estado IN ({marcadores}) ORDER BY criado_em", estados).fetchall()
        return [_registro(l) for l in linhas]

    def recentes(self, limite: int = 50) -> list[CotacaoRegistro]:
        linhas = self._con.execute(
            "SELECT * FROM cotacoes ORDER BY criado_em DESC, rowid DESC LIMIT ?", (limite,)).fetchall()
        return [_registro(l) for l in linhas]

    # ------------------------------------------------------------------ interno

    def _transacao(self):
        return _Transacao(self._con)

    def lote(self):
        """Várias gravações como UMA só (tudo ou nada)."""
        return _Transacao(self._con)

    def _estado(self, cid: str) -> Estado:
        linha = self._con.execute("SELECT estado FROM cotacoes WHERE id = ?", (cid,)).fetchone()
        if linha is None:
            raise KeyError(f"Cotação não encontrada: {cid}")
        return Estado(linha["estado"])

    def _atualizar(self, cid: str, **campos: str) -> None:
        colunas = ", ".join(f"{c} = ?" for c in campos)
        with self._transacao():
            self._con.execute(f"UPDATE cotacoes SET {colunas}, atualizado_em = ? WHERE id = ?",
                              (*campos.values(), _agora(), cid))

    def _evento(self, cid, tipo, de, para, detalhe) -> None:
        self._con.execute(
            "INSERT INTO cotacao_eventos (cotacao_id, momento, tipo, de_estado, para_estado, detalhe) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (cid, _agora(), tipo, de.value if de else None, para.value if para else None, detalhe or None))


def _registro(linha: sqlite3.Row) -> CotacaoRegistro:
    dados = dict(linha)
    dados["estado"] = Estado(dados["estado"])
    # Coluna de uma versão mais nova (ex.: depois de voltar para a versão anterior) é ignorada.
    campos = {c.name for c in fields(CotacaoRegistro)}
    return CotacaoRegistro(**{k: v for k, v in dados.items() if k in campos})
