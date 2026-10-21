# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Histórico local de execuções em SQLite.

Limitações (documentadas de propósito):
- É um histórico operacional de um único usuário, não uma auditoria inviolável.
- Não enxerga claims criados manualmente no SAP: a checagem de duplicidade
  no SAP continua sendo a verificação principal.
- Não guarda o texto livre nem o conteúdo do anexo.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from models import ClaimRequest
from state import BLOQUEIAM_DUPLICIDADE, PENDENTES, TRANSICOES, Estado, validar_transicao

ESQUEMA = """
CREATE TABLE IF NOT EXISTS execucoes (
    id               TEXT PRIMARY KEY,
    criado_em        TEXT NOT NULL,
    atualizado_em    TEXT NOT NULL,
    fim_em           TEXT,
    modo             TEXT NOT NULL,
    tipo             TEXT NOT NULL,
    ordem            TEXT NOT NULL,
    item             TEXT NOT NULL,
    arquivo_nome     TEXT,
    arquivo_bytes    INTEGER,
    sap_usuario      TEXT,
    sap_sistema      TEXT,
    sap_mandante     TEXT,
    estado           TEXT NOT NULL,
    documento_dms    TEXT,
    numero_nota      TEXT,
    etapa_falha      TEXT,
    mensagem_tecnica TEXT
);
CREATE INDEX IF NOT EXISTS ix_execucoes_ordem_item ON execucoes (ordem, item);
CREATE INDEX IF NOT EXISTS ix_execucoes_estado ON execucoes (estado);

CREATE TABLE IF NOT EXISTS eventos (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    execucao_id  TEXT NOT NULL REFERENCES execucoes(id),
    momento      TEXT NOT NULL,
    tipo         TEXT NOT NULL,
    de_estado    TEXT,
    para_estado  TEXT,
    detalhe      TEXT
);
CREATE INDEX IF NOT EXISTS ix_eventos_execucao ON eventos (execucao_id);
"""


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass(frozen=True)
class Execucao:
    id: str
    criado_em: str
    atualizado_em: str
    fim_em: str | None
    modo: str
    tipo: str
    ordem: str
    item: str
    arquivo_nome: str | None
    arquivo_bytes: int | None
    sap_usuario: str | None
    sap_sistema: str | None
    sap_mandante: str | None
    estado: Estado
    documento_dms: str | None
    numero_nota: str | None
    etapa_falha: str | None
    mensagem_tecnica: str | None

    @property
    def duracao_segundos(self) -> float | None:
        if not self.fim_em:
            return None
        inicio = datetime.fromisoformat(self.criado_em)
        return (datetime.fromisoformat(self.fim_em) - inicio).total_seconds()


@dataclass(frozen=True)
class Evento:
    momento: str
    tipo: str
    de_estado: str | None
    para_estado: str | None
    detalhe: str | None


class Storage:
    def __init__(self, caminho_db: Path | str):
        caminho_db = Path(caminho_db)
        caminho_db.parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(caminho_db, isolation_level=None)  # transações explícitas
        self._con.row_factory = sqlite3.Row
        self._con.execute("PRAGMA foreign_keys = ON")
        self._con.execute("PRAGMA journal_mode = WAL")
        self._con.executescript(ESQUEMA)

    def close(self) -> None:
        self._con.close()

    # ------------------------------------------------------------------ escrita

    def criar_execucao(self, req: ClaimRequest, modo: str) -> str:
        execucao_id = uuid.uuid4().hex[:12].upper()
        agora = _agora()
        tamanho = None
        if req.arquivo is not None and req.arquivo.is_file():
            tamanho = req.arquivo.stat().st_size
        with self._transacao():
            self._con.execute(
                """INSERT INTO execucoes
                   (id, criado_em, atualizado_em, modo, tipo, ordem, item,
                    arquivo_nome, arquivo_bytes, estado)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (execucao_id, agora, agora, modo, req.tipo, req.ordem, req.item,
                 req.nome_arquivo or None, tamanho, Estado.RECEBIDO.value),
            )
            self._evento(execucao_id, "CRIACAO", None, Estado.RECEBIDO, f"modo={modo}")
        return execucao_id

    def transitar(self, execucao_id: str, novo: Estado, detalhe: str = "") -> None:
        """Muda o estado, validando a transição. Atômico: estado e evento juntos."""
        with self._transacao():
            atual = self._estado_atual(execucao_id)
            validar_transicao(atual, novo)
            agora = _agora()
            fim = agora if not _tem_saida(novo) else None
            self._con.execute(
                "UPDATE execucoes SET estado = ?, atualizado_em = ?, fim_em = COALESCE(?, fim_em) WHERE id = ?",
                (novo.value, agora, fim, execucao_id),
            )
            self._evento(execucao_id, "TRANSICAO", atual, novo, detalhe)

    def registrar_sessao(self, execucao_id: str, usuario: str, sistema: str, mandante: str) -> None:
        self._atualizar(execucao_id, sap_usuario=usuario, sap_sistema=sistema, sap_mandante=mandante)

    def registrar_documento(self, execucao_id: str, numero: str) -> None:
        self._atualizar(execucao_id, documento_dms=numero)
        self.registrar_evento(execucao_id, "DOCUMENTO_ZDC", numero)

    def registrar_nota(self, execucao_id: str, numero: str) -> None:
        self._atualizar(execucao_id, numero_nota=numero)
        self.registrar_evento(execucao_id, "NOTA", numero)

    def registrar_falha(self, execucao_id: str, etapa: str, mensagem: str) -> None:
        self._atualizar(execucao_id, etapa_falha=etapa, mensagem_tecnica=mensagem)
        self.registrar_evento(execucao_id, "FALHA", f"{etapa}: {mensagem}")

    def registrar_evento(self, execucao_id: str, tipo: str, detalhe: str = "") -> None:
        with self._transacao():
            self._evento(execucao_id, tipo, None, None, detalhe)

    # ------------------------------------------------------------------ leitura

    def obter(self, execucao_id: str) -> Execucao:
        linha = self._con.execute("SELECT * FROM execucoes WHERE id = ?", (execucao_id,)).fetchone()
        if linha is None:
            raise KeyError(f"Execução não encontrada: {execucao_id}")
        return _para_execucao(linha)

    def eventos(self, execucao_id: str) -> list[Evento]:
        linhas = self._con.execute(
            "SELECT momento, tipo, de_estado, para_estado, detalhe FROM eventos "
            "WHERE execucao_id = ? ORDER BY id",
            (execucao_id,),
        ).fetchall()
        return [Evento(**dict(l)) for l in linhas]

    def possiveis_duplicidades(self, ordem: str, item: str, ignorar_id: str | None = None) -> list[Execucao]:
        """Execuções da mesma ordem/item que criaram ou podem ter criado um claim."""
        estados = [e.value for e in BLOQUEIAM_DUPLICIDADE]
        marcadores = ",".join("?" * len(estados))
        linhas = self._con.execute(
            f"SELECT * FROM execucoes WHERE ordem = ? AND item = ? AND estado IN ({marcadores}) "
            "AND id IS NOT ? ORDER BY criado_em DESC",
            (ordem, item, *estados, ignorar_id),
        ).fetchall()
        return [_para_execucao(l) for l in linhas]

    def pendentes(self) -> list[Execucao]:
        estados = [e.value for e in PENDENTES]
        marcadores = ",".join("?" * len(estados))
        linhas = self._con.execute(
            f"SELECT * FROM execucoes WHERE estado IN ({marcadores}) ORDER BY criado_em",
            estados,
        ).fetchall()
        return [_para_execucao(l) for l in linhas]

    def nao_finalizadas(self) -> list[Execucao]:
        """Execuções interrompidas (ex.: programa fechado no meio). Usado ao reabrir."""
        linhas = self._con.execute(
            "SELECT * FROM execucoes WHERE fim_em IS NULL ORDER BY criado_em"
        ).fetchall()
        return [_para_execucao(l) for l in linhas]

    def recentes(self, limite: int = 50) -> list[Execucao]:
        linhas = self._con.execute(
            "SELECT * FROM execucoes ORDER BY criado_em DESC, rowid DESC LIMIT ?", (limite,)
        ).fetchall()
        return [_para_execucao(l) for l in linhas]

    # ------------------------------------------------------------------ interno

    def _transacao(self):
        return _Transacao(self._con)

    def _estado_atual(self, execucao_id: str) -> Estado:
        linha = self._con.execute("SELECT estado FROM execucoes WHERE id = ?", (execucao_id,)).fetchone()
        if linha is None:
            raise KeyError(f"Execução não encontrada: {execucao_id}")
        return Estado(linha["estado"])

    def _atualizar(self, execucao_id: str, **campos: str) -> None:
        colunas = ", ".join(f"{c} = ?" for c in campos)
        with self._transacao():
            cur = self._con.execute(
                f"UPDATE execucoes SET {colunas}, atualizado_em = ? WHERE id = ?",
                (*campos.values(), _agora(), execucao_id),
            )
            if cur.rowcount == 0:
                raise KeyError(f"Execução não encontrada: {execucao_id}")

    def _evento(self, execucao_id, tipo, de, para, detalhe) -> None:
        self._con.execute(
            "INSERT INTO eventos (execucao_id, momento, tipo, de_estado, para_estado, detalhe) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (execucao_id, _agora(), tipo,
             de.value if de else None, para.value if para else None, detalhe or None),
        )


class _Transacao:
    """BEGIN IMMEDIATE ... COMMIT/ROLLBACK, para estado e evento nunca divergirem."""

    def __init__(self, con: sqlite3.Connection):
        self._con = con

    def __enter__(self):
        self._con.execute("BEGIN IMMEDIATE")
        return self._con

    def __exit__(self, tipo_exc, exc, tb):
        self._con.execute("COMMIT" if tipo_exc is None else "ROLLBACK")
        return False


def _tem_saida(estado: Estado) -> bool:
    return bool(TRANSICOES[estado])


def _para_execucao(linha: sqlite3.Row) -> Execucao:
    dados = dict(linha)
    dados["estado"] = Estado(dados["estado"])
    return Execucao(**dados)
