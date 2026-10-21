# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Ponte entre a interface e o serviço. Não depende de tkinter (testável).

A execução roda em uma thread separada para a janela não congelar. A thread
nunca toca na interface: ela só coloca eventos numa fila, que a interface lê.
"""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from claim_service import ClaimService, Resultado
from config import Settings
from models import ClaimRequest
from sap_gateway import SapError, SapGateway
from state import Estado
from storage import Execucao, Storage
from validators import ValidationIssue, validate

log = logging.getLogger("claim.controlador")

MODOS_DA_INTERFACE = ("SIMULACAO", "ENSAIO")          # sempre disponíveis (não gravam)
MODOS_COM_GRAVACAO = ("ASSISTIDO", "AUTOMATICO")      # só com automatico_habilitado = sim
ROTULO_MODO = {"SIMULACAO": "Simulação", "ENSAIO": "Ensaio", "ASSISTIDO": "Assistido", "AUTOMATICO": "Completo"}


def modos_da_interface(settings: Settings) -> tuple[str, ...]:
    return MODOS_DA_INTERFACE + (MODOS_COM_GRAVACAO if settings.automatico_habilitado else ())

ROTULO_ESTADO = {
    Estado.RECEBIDO: "Recebido",
    Estado.VALIDANDO: "Validando",
    Estado.PRONTO_PARA_EXECUCAO: "Pronto",
    Estado.EXECUTANDO: "Executando",
    Estado.AGUARDANDO_CONFIRMACAO: "Aguardando confirmação",
    Estado.CONCLUIDO: "Concluído",
    Estado.ENSAIO_CONCLUIDO: "Ensaio concluído",
    Estado.FALHA_RECUPERAVEL: "Falha (pode repetir)",
    Estado.FALHA_DEFINITIVA: "Falha definitiva",
    Estado.REVISAO_NECESSARIA: "Revisão necessária",
}

# Tom visual de cada estado: ok | atencao | erro | neutro
TOM_ESTADO = {
    Estado.CONCLUIDO: "ok",
    Estado.ENSAIO_CONCLUIDO: "ok",
    Estado.AGUARDANDO_CONFIRMACAO: "atencao",
    Estado.REVISAO_NECESSARIA: "atencao",
    Estado.FALHA_RECUPERAVEL: "erro",
    Estado.FALHA_DEFINITIVA: "erro",
}


@dataclass(frozen=True)
class Evento:
    tipo: str                 # etapa | fim | erro | sap
    etapa: str = ""
    situacao: str = ""        # ativo | ok | falha
    detalhe: str = ""
    resultado: Resultado | None = None


# ----------------------------------------------------------------------- formulário

def montar_request(campos: dict[str, object]) -> ClaimRequest:
    return ClaimRequest.from_form(
        tipo=campos.get("tipo", ""),
        descricao=campos.get("descricao", ""),
        texto_livre=campos.get("texto_livre", ""),
        ordem=campos.get("ordem", ""),
        item=campos.get("item", ""),
        arquivo=campos.get("arquivo", ""),
        sem_anexo=bool(campos.get("sem_anexo", False)),
    )


def erros_por_campo(problemas: list[ValidationIssue]) -> dict[str, str]:
    erros: dict[str, str] = {}
    for p in problemas:
        erros.setdefault(p.campo, p.mensagem)
    return erros


def validar_formulario(campos: dict[str, object], settings: Settings) -> dict[str, str]:
    return erros_por_campo(validate(montar_request(campos), settings))


def resumo_arquivo(caminho: str) -> str:
    try:
        p = Path(caminho)
        tamanho = p.stat().st_size
    except (OSError, ValueError):
        return ""
    for unidade in ("B", "KB", "MB", "GB"):
        if tamanho < 1024 or unidade == "GB":
            valor = f"{tamanho:.0f}" if unidade == "B" else f"{tamanho:.1f}".replace(".", ",")
            return f"{p.name} · {valor} {unidade}"
        tamanho /= 1024
    return p.name


# ----------------------------------------------------------------------- histórico

def linha_historico(e: Execucao) -> tuple[str, ...]:
    quando = datetime.fromisoformat(e.criado_em).strftime("%d/%m %H:%M")
    duracao = f"{e.duracao_segundos:.0f}s" if e.duracao_segundos is not None else "—"
    return (quando, ROTULO_ESTADO.get(e.estado, e.estado.value), e.tipo, f"{e.ordem}/{e.item}",
            e.numero_nota or "—", duracao, e.id)


def pendencias(storage: Storage) -> list[Execucao]:
    """Execuções que pedem atenção: sem confirmação, em revisão ou interrompidas no meio."""
    interrompidas = [e for e in storage.nao_finalizadas()
                     if e.estado in (Estado.EXECUTANDO, Estado.PRONTO_PARA_EXECUCAO)]
    vistos = {e.id for e in interrompidas}
    return interrompidas + [e for e in storage.pendentes() if e.id not in vistos]


def resolver_pendencia(storage: Storage, execucao_id: str, *, criado: bool, numero_nota: str = "",
                       observacao: str = "") -> None:
    """Decisão humana, depois de conferir no SAP.

    criado=True  -> o claim existe no SAP: CONCLUIDO, com o número informado.
    criado=False -> o claim NÃO existe: FALHA_DEFINITIVA (libera nova execução da ordem/item).
    """
    numero = numero_nota.strip()
    if criado and (not numero.isdigit() or not numero.isascii()):
        raise ValueError("Informe o número da nota (somente dígitos).")
    atual = storage.obter(execucao_id).estado
    if atual not in (Estado.REVISAO_NECESSARIA, Estado.AGUARDANDO_CONFIRMACAO,
                     Estado.EXECUTANDO, Estado.PRONTO_PARA_EXECUCAO):
        raise ValueError(f"Esta execução não está pendente ({ROTULO_ESTADO.get(atual, atual.value)}).")
    if atual == Estado.PRONTO_PARA_EXECUCAO:
        storage.transitar(execucao_id, Estado.EXECUTANDO, "retomada para resolução manual")
        atual = Estado.EXECUTANDO
    if atual in (Estado.EXECUTANDO, Estado.AGUARDANDO_CONFIRMACAO) and not criado:
        storage.transitar(execucao_id, Estado.REVISAO_NECESSARIA, "resolução manual")
    detalhe = "resolvido pelo usuário" + (f": {observacao.strip()}" if observacao.strip() else "")
    if criado:
        storage.registrar_nota(execucao_id, numero)
        storage.transitar(execucao_id, Estado.CONCLUIDO, f"{detalhe}; nota {numero} conferida no SAP")
    else:
        storage.transitar(execucao_id, Estado.FALHA_DEFINITIVA, f"{detalhe}; claim não existe no SAP")


# ----------------------------------------------------------------------- execução

def fabrica_sap_padrao(settings: Settings, modo: str) -> SapGateway:
    if modo == "SIMULACAO":
        from sap_fake import FakeSap
        return FakeSap(popups_apos_enter=["O cliente SIMULADO tem bloqueio de registro"], atraso_s=0.5)
    if modo in ("ENSAIO",) + MODOS_COM_GRAVACAO:
        from sap_client import SapClient
        return SapClient(settings)
    raise ValueError(f"Modo não disponível na interface: {modo}")


def _com_inicio() -> bool:
    """O COM do Windows precisa ser inicializado em cada thread que fala com o SAP."""
    try:
        import pythoncom  # type: ignore
    except ImportError:
        return False
    pythoncom.CoInitialize()
    return True


def _com_fim(iniciado: bool) -> None:
    if iniciado:
        import pythoncom  # type: ignore
        pythoncom.CoUninitialize()


class Executor:
    def __init__(self, settings: Settings, caminho_db: Path,
                 fabrica_sap: Callable[[Settings, str], SapGateway] = fabrica_sap_padrao):
        self._cfg = settings
        self._db = Path(caminho_db)
        self._fabrica = fabrica_sap
        self.fila: "queue.Queue[Evento]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self._cancelar: threading.Event | None = None

    @property
    def ocupado(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def iniciar(self, req: ClaimRequest, modo: str) -> None:
        if self.ocupado:
            raise RuntimeError("Já existe uma execução em andamento.")
        if modo not in modos_da_interface(self._cfg):
            raise ValueError(f"Modo não disponível na interface: {modo}")
        self._cancelar = threading.Event()
        self._thread = threading.Thread(target=self._rodar, args=(req, modo), daemon=True, name="execucao")
        self._thread.start()

    iniciar_ensaio = iniciar   # compatibilidade

    def interromper(self) -> None:
        """Pedido de parada: atendido no início da próxima etapa (nunca no meio de uma)."""
        if self._cancelar is not None:
            self._cancelar.set()

    def verificar_sap(self) -> None:
        threading.Thread(target=self._verificar, daemon=True, name="verificar-sap").start()

    def drenar(self) -> list[Evento]:
        eventos: list[Evento] = []
        while True:
            try:
                eventos.append(self.fila.get_nowait())
            except queue.Empty:
                return eventos

    def aguardar(self, timeout: float = 10.0) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    # ------------------------------------------------------------------ threads

    def _rodar(self, req: ClaimRequest, modo: str) -> None:
        com = _com_inicio()
        try:
            sap = self._fabrica(self._cfg, modo)
            db = Storage(self._db)   # conexão própria desta thread
            try:
                servico = ClaimService(
                    self._cfg, sap, db,
                    progresso=lambda e, s, d: self.fila.put(Evento("etapa", e, s, d)),
                    cancelar=self._cancelar,
                )
                resultado = servico.executar(req, modo)
            finally:
                db.close()
            self.fila.put(Evento("fim", resultado=resultado))
        except Exception as erro:  # noqa: BLE001 - a interface precisa saber de qualquer erro
            log.exception("Erro inesperado na execução")
            self.fila.put(Evento("erro", detalhe=str(erro)))
        finally:
            _com_fim(com)

    def _verificar(self) -> None:
        com = _com_inicio()
        try:
            from sap_client import SapClient
            base = SapClient(self._cfg).diagnostico()
            self.fila.put(Evento("sap", situacao="ok",
                                 detalhe=f"{base.info.sistema}/{base.info.mandante} · {base.info.usuario}"))
        except SapError as erro:
            self.fila.put(Evento("sap", situacao="falha", detalhe=str(erro)))
        except Exception as erro:  # noqa: BLE001
            self.fila.put(Evento("sap", situacao="falha", detalhe=f"Erro inesperado: {erro}"))
        finally:
            _com_fim(com)
