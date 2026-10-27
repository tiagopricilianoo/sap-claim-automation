# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Histórico local de execuções em SQLite.

Limitações (documentadas de propósito):
- É um histórico operacional de um único usuário, não uma auditoria inviolável.
- Não enxerga claims criados manualmente no SAP, em outro computador ou antes
  de o histórico ser apagado. HOJE NÃO HÁ checagem no SAP (falta a consulta
  CLM3): a única proteção automática é este histórico; para item que pode já
  ter claim, o orçamentista confere na CLM3.
- Não guarda o texto livre nem o conteúdo do anexo.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, fields
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

# Colunas acrescentadas depois da 1ª versão (bancos antigos recebem com ALTER TABLE).
COLUNAS_NOVAS = {"linha_criada": "TEXT"}


def abrir_banco(caminho_db: Path, esquema: str, tabela: str, colunas: dict[str, str]) -> sqlite3.Connection:
    """Conexão pronta (WAL, esquema, migração). A tela e a thread abrem o mesmo banco ao mesmo tempo:
    'database is locked' na criação/migração é esperado de vez em quando e vale tentar de novo."""
    import time
    for tentativa in range(20):
        # timeout: outra conexão gravando espera até 15 s, em vez de errar. Transações explícitas.
        con = sqlite3.connect(caminho_db, isolation_level=None, timeout=15)
        try:
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA foreign_keys = ON")
            con.execute("PRAGMA journal_mode = WAL")
            con.executescript(esquema)
            migrar_colunas(con, tabela, colunas)
            return con
        except sqlite3.OperationalError as erro:
            con.close()
            if "locked" not in str(erro).lower() or tentativa == 19:
                raise
            time.sleep(0.1 + 0.05 * tentativa)
    raise AssertionError("inalcançável")


def migrar_colunas(con: sqlite3.Connection, tabela: str, colunas: dict[str, str]) -> None:
    """Acrescenta colunas novas (sempre opcionais) a um banco criado por uma versão anterior.
    Dois programas abrindo o mesmo banco ao mesmo tempo: quem chegar depois ignora a coluna repetida."""
    existentes = {l[1] for l in con.execute(f"PRAGMA table_info({tabela})")}
    for coluna, tipo in colunas.items():
        if coluna in existentes:
            continue
        try:
            con.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")
        except sqlite3.OperationalError as erro:
            if "duplicate column" not in str(erro).lower():
                raise


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
    linha_criada: str | None = None   # item acrescentado na cotação por esta execução

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
        self._con = abrir_banco(caminho_db, ESQUEMA, "execucoes", COLUNAS_NOVAS)

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

    def lote(self):
        """Várias gravações como UMA só (tudo ou nada): ex.: resolução de pendência."""
        return _Transacao(self._con)

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

    def registrar_linha(self, execucao_id: str, item: str) -> None:
        """Linha gravada na cotação: a execução passa a valer para ordem/item novo."""
        self._atualizar(execucao_id, item=item, linha_criada=item)
        self.registrar_evento(execucao_id, "LINHA_CRIADA", f"item {item}")

    def registrar_linha_incerta(self, execucao_id: str, item: str) -> None:
        """Gravação da linha ENVIADA, ainda sem confirmação: '?20' (pode existir na VA22)."""
        self._atualizar(execucao_id, linha_criada="?" + item)
        self.registrar_evento(execucao_id, "LINHA_ENVIADA", f"item {item} (sem confirmação)")

    def definir_linha(self, execucao_id: str, item: str | None, detalhe: str) -> None:
        """Decisão humana sobre uma linha incerta: confirmada (item) ou inexistente (None)."""
        campos = {"linha_criada": item}
        if item:
            campos["item"] = item
        self._atualizar(execucao_id, **campos)
        self.registrar_evento(execucao_id, "LINHA_RESOLVIDA", detalhe)

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

    def possiveis_duplicidades(self, ordem: str, item: str, ignorar_id: str | None = None,
                               modo: str | None = None) -> list[Execucao]:
        """Execuções da mesma ordem/item que criaram ou podem ter criado um claim.
        Uma simulação nunca gravou nada no SAP: só bloqueia outra simulação (modo == "SIMULACAO")."""
        estados = [e.value for e in BLOQUEIAM_DUPLICIDADE]
        marcadores = ",".join("?" * len(estados))
        linhas = self._con.execute(
            # ltrim(…,'0'): '010' e '10' são o mesmo item no SAP (vale também para registros antigos)
            # ltrim(item) != '': execução de linha nova ainda sem item não é "o item 0".
            f"SELECT * FROM execucoes WHERE ltrim(ordem, '0') = ltrim(?, '0') AND ltrim(item, '0') = ltrim(?, '0') "
            "AND ltrim(item, '0') != '' "
            f"AND estado IN ({marcadores}) "
            "AND id IS NOT ? AND (modo != 'SIMULACAO' OR ? = 'SIMULACAO') ORDER BY criado_em DESC",
            (ordem, item, *estados, ignorar_id, modo or ""),
        ).fetchall()
        return [_para_execucao(l) for l in linhas]

    def linhas_sem_claim(self, ordem: str, ignorar_id: str | None = None,
                         modo: str | None = None) -> list[Execucao]:
        """Linhas desta cotação que existem (ou podem existir) na VA22 e ainda não têm claim.

        - execuções de linha nova ainda em andamento ou pendentes (a linha pode estar sendo gravada);
        - qualquer execução com linha registrada ('20' ou incerta '?20'), em qualquer estado menos
          CONCLUIDO, enquanto não houver um claim CONCLUIDO para aquele ordem/item.
        Resolver a pendência como "claim não existe" NÃO apaga a linha: só a decisão sobre a linha apaga.
        Linha de simulação não existe no SAP: só conta para outra simulação.
        """
        andamento = [e.value for e in PENDENTES] + [Estado.EXECUTANDO.value, Estado.PRONTO_PARA_EXECUCAO.value]
        marcadores = ",".join("?" * len(andamento))
        linhas = self._con.execute(
            f"""SELECT * FROM execucoes e
                WHERE ltrim(e.ordem, '0') = ltrim(?, '0') AND e.id IS NOT ?
                  AND (e.modo != 'SIMULACAO' OR ? = 'SIMULACAO') AND (
                    (e.estado IN ({marcadores}) AND (e.linha_criada IS NOT NULL OR e.item = ''))
                    OR (e.linha_criada IS NOT NULL AND e.estado != 'CONCLUIDO' AND NOT EXISTS (
                        SELECT 1 FROM execucoes c WHERE c.estado = 'CONCLUIDO'
                          AND (c.modo != 'SIMULACAO' OR ? = 'SIMULACAO')
                          AND ltrim(c.ordem, '0') = ltrim(e.ordem, '0')
                          AND ltrim(c.item, '0') = ltrim(replace(e.linha_criada, '?', ''), '0')))
                ) ORDER BY e.criado_em DESC""",
            (ordem, ignorar_id, modo or "", *andamento, modo or ""),
        ).fetchall()
        return [_para_execucao(l) for l in linhas]

    def linhas_recentes(self, ordem: str, minutos: int, ignorar_id: str | None = None) -> list[Execucao]:
        """Linhas novas CONCLUÍDAS nesta cotação nos últimos minutos (clique repetido por engano)."""
        from datetime import timedelta
        desde = (datetime.now() - timedelta(minutes=minutos)).isoformat(timespec="seconds")
        linhas = self._con.execute(
            "SELECT * FROM execucoes WHERE ltrim(ordem, '0') = ltrim(?, '0') AND estado = 'CONCLUIDO' "
            "AND linha_criada IS NOT NULL AND modo != 'SIMULACAO' AND criado_em >= ? AND id IS NOT ? "
            "ORDER BY criado_em DESC",
            (ordem, desde, ignorar_id),
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
    """BEGIN IMMEDIATE ... COMMIT/ROLLBACK, para estado e evento nunca divergirem.
    Reentrante: dentro de uma transação já aberta (ex.: Storage.lote()), participa dela."""

    def __init__(self, con: sqlite3.Connection):
        self._con = con
        self._dono = False

    def __enter__(self):
        if not self._con.in_transaction:
            self._con.execute("BEGIN IMMEDIATE")
            self._dono = True
        return self._con

    def __exit__(self, tipo_exc, exc, tb):
        if self._dono:
            self._con.execute("COMMIT" if tipo_exc is None else "ROLLBACK")
        return False


def _tem_saida(estado: Estado) -> bool:
    return bool(TRANSICOES[estado])


def _para_execucao(linha: sqlite3.Row) -> Execucao:
    dados = dict(linha)
    dados["estado"] = Estado(dados["estado"])
    # Coluna de uma versão mais nova (ex.: depois de voltar para a versão anterior) é ignorada.
    campos = {c.name for c in fields(Execucao)}
    return Execucao(**{k: v for k, v in dados.items() if k in campos})
