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
from state import Estado, pode_transitar
from storage import Execucao, Storage
from validators import ValidationIssue, validate

log = logging.getLogger("claim.controlador")

MODOS_DA_INTERFACE = ("SIMULACAO", "ENSAIO")          # sempre disponíveis (não gravam)
MODOS_COM_GRAVACAO = ("ASSISTIDO", "AUTOMATICO")      # só com automatico_habilitado = sim
ROTULO_MODO = {"SIMULACAO": "Simulação", "ENSAIO": "Ensaio", "ASSISTIDO": "Assistido", "AUTOMATICO": "Completo"}


def modos_da_interface(settings: Settings) -> tuple[str, ...]:
    return MODOS_DA_INTERFACE + (MODOS_COM_GRAVACAO if settings.automatico_habilitado else ())


def modos_cotacao_da_interface(settings: Settings) -> tuple[str, ...]:
    """Cotação: sem Assistido (as pastas dependem do número gravado)."""
    return MODOS_DA_INTERFACE + (("AUTOMATICO",) if settings.automatico_habilitado else ())

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
    resultado: object | None = None      # Resultado (claim) ou ResultadoCotacao
    origem: str = "claim"                # claim | cotacao


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
        linha_nova=bool(campos.get("linha_nova", False)),
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
    return (quando, ROTULO_ESTADO.get(e.estado, e.estado.value), e.tipo, f"{e.ordem}/{e.item or 'nova'}",
            e.numero_nota or "—", duracao, e.id)


def pendencias(storage: Storage) -> list[Execucao]:
    """Execuções que pedem atenção: sem confirmação, em revisão ou interrompidas no meio."""
    interrompidas = [e for e in storage.nao_finalizadas()
                     if e.estado in (Estado.EXECUTANDO, Estado.PRONTO_PARA_EXECUCAO)]
    vistos = {e.id for e in interrompidas}
    return interrompidas + [e for e in storage.pendentes() if e.id not in vistos]


def _caminho_de_resolucao(atual: Estado, final: Estado) -> list[Estado]:
    """Transições até o estado final, SEMPRE passando por revisão (decisão humana).

    O caminho inteiro é conferido ANTES de gravar qualquer coisa: se não der, nada muda.
    """
    caminho = {
        Estado.PRONTO_PARA_EXECUCAO: [Estado.EXECUTANDO, Estado.REVISAO_NECESSARIA],
        Estado.EXECUTANDO: [Estado.REVISAO_NECESSARIA],
        Estado.AGUARDANDO_CONFIRMACAO: [Estado.REVISAO_NECESSARIA],
        Estado.REVISAO_NECESSARIA: [],
    }.get(atual)
    if caminho is None:
        raise ValueError(f"Esta execução não está pendente ({ROTULO_ESTADO.get(atual, atual.value)}).")
    caminho = caminho + [final]
    anterior = atual
    for proximo in caminho:
        if not pode_transitar(anterior, proximo):
            raise ValueError(f"Não é possível resolver a partir de {ROTULO_ESTADO.get(atual, atual.value)}.")
        anterior = proximo
    return caminho


def _lote(storage):
    """Transação única do storage (ou nada, para storages de teste sem lote())."""
    import contextlib
    lote = getattr(storage, "lote", None)
    return lote() if callable(lote) else contextlib.nullcontext()


def resolver_pendencia(storage: Storage, execucao_id: str, *, criado: bool, numero_nota: str = "",
                       observacao: str = "", linha_existe: bool | None = None) -> None:
    """Decisão humana, depois de conferir no SAP.

    criado=True  -> o claim existe no SAP: CONCLUIDO, com o número informado.
    criado=False -> o claim NÃO existe: FALHA_DEFINITIVA (libera nova execução da ordem/item).
    linha_existe -> só para execução de linha nova com gravação da linha sem confirmação ('?20'):
                    True = a linha existe na VA22, False = não existe, None = não informado (a linha
                    continua contando como "talvez exista" e bloqueia outra linha nova).
    """
    numero = numero_nota.strip()
    if criado and (not numero.isdigit() or not numero.isascii()):
        raise ValueError("Informe o número da nota (somente dígitos).")
    execucao = storage.obter(execucao_id)
    final = Estado.CONCLUIDO if criado else Estado.FALHA_DEFINITIVA
    caminho = _caminho_de_resolucao(execucao.estado, final)      # confere tudo antes de gravar
    detalhe = "resolvido pelo usuário" + (f": {observacao.strip()}" if observacao.strip() else "")
    linha = execucao.linha_criada or ""
    if criado:
        if numero.lstrip("0") == (execucao.ordem or "").lstrip("0"):
            raise ValueError(f"{numero} é o número da cotação/ordem. Informe o número da NOTA (claim), "
                             "conferido na CLM3.")
        if linha.startswith("?"):
            if linha_existe is False:
                raise ValueError(f"Se o claim existe, a linha {linha.lstrip('?')} também existe na cotação "
                                 "(o claim é do item dela). Confira de novo na VA23.")
            linha_existe = True                  # claim criado => a linha dele existe
        elif not (execucao.item or linha):
            raise ValueError("Esta execução não chegou a criar a linha: não há item para um claim. "
                             "Confira na VA23/CLM3; se nada foi criado, use 'Não foi criado'.")
    with _lote(storage):              # tudo ou nada: linha, nota e estado juntos
        for estado in caminho[:-1]:
            storage.transitar(execucao_id, estado, "resolução manual")
        if linha.startswith("?") and linha_existe is not None:
            item = linha.lstrip("?")
            storage.definir_linha(execucao_id, item if linha_existe else None,
                                  f"linha {item} {'existe' if linha_existe else 'não existe'} na cotação (usuário)")
        if criado:
            storage.registrar_nota(execucao_id, numero)
            storage.transitar(execucao_id, Estado.CONCLUIDO, f"{detalhe}; nota {numero} conferida no SAP")
        else:
            storage.transitar(execucao_id, Estado.FALHA_DEFINITIVA, f"{detalhe}; claim não existe no SAP")


# ----------------------------------------------------------------------- cotações

ROTULO_MODO_COTACAO_LISTA = {"SIMULACAO": "simulação", "ENSAIO": "ensaio"}


def linha_cotacao(c) -> tuple[str, ...]:
    """Quando, Cliente, Projeto, Cotação, Linhas, Situação, Tipo."""
    quando = datetime.fromisoformat(c.criado_em).strftime("%d/%m/%y %H:%M")
    itens = ", ".join(f"{l['item']} {l['equipamento']}" for l in c.lista_linhas) or \
        " + ".join(n for n, ok in (("Produto A", c.produto_a), ("Produto B", c.produto_b)) if ok)
    cliente = c.cliente or ("Cliente Especial" if c.tipo == "Cliente Especial" else "—")
    situacao = ROTULO_ESTADO.get(c.estado, c.estado.value)
    if c.modo != "AUTOMATICO":          # simulação/ensaio nunca gravou no SAP: não confundir com a real
        situacao = f"{situacao} ({ROTULO_MODO_COTACAO_LISTA.get(c.modo, c.modo)})"
    return (quando, cliente, c.projeto, c.numero or "—", itens, situacao, c.tipo)


def filtrar_cotacoes(registros, texto: str):
    """Filtro da lista: cada palavra digitada tem que aparecer no cliente, projeto, número, país ou tipo."""
    from pastas import nome_comparavel
    palavras = nome_comparavel(texto or "").split()
    if not palavras:
        return list(registros)
    filtrados = []
    for c in registros:
        alvo = nome_comparavel(" ".join(filter(None, (c.cliente, c.projeto, c.numero, c.pais, c.regiao, c.tipo))))
        if all(p in alvo for p in palavras):
            filtrados.append(c)
    return filtrados


def resolver_cotacao(storage, cotacao_id: str, *, criada: bool, numero: str = "") -> None:
    """Decisão humana depois de conferir no SAP (VA23) uma cotação sem confirmação."""
    numero = numero.strip()
    if criada and (not numero.isdigit() or not numero.isascii()):
        raise ValueError("Informe o número da cotação (somente dígitos).")
    registro = storage.obter(cotacao_id)
    final = Estado.CONCLUIDO if criada else Estado.FALHA_DEFINITIVA
    caminho = _caminho_de_resolucao(registro.estado, final)     # confere tudo antes de gravar
    with _lote(storage):
        for estado in caminho[:-1]:
            storage.transitar(cotacao_id, estado, "resolução manual")
        if criada:
            storage.registrar_numero(cotacao_id, numero, registro.lista_linhas)
            storage.transitar(cotacao_id, Estado.CONCLUIDO, f"resolvido pelo usuário: cotação {numero} conferida")
        else:
            storage.transitar(cotacao_id, Estado.FALHA_DEFINITIVA, "resolvido pelo usuário: cotação não existe")


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
        self._verificacao: threading.Thread | None = None
        self._cancelar: threading.Event | None = None
        self.janela_mantida: str | None = None   # janela do SAP deixada no menu para o próximo claim

    @property
    def ocupado(self) -> bool:
        """Execução OU verificação do SAP em andamento: as duas nunca usam o SAP ao mesmo tempo."""
        return (self._thread is not None and self._thread.is_alive()) or self.verificando

    @property
    def verificando(self) -> bool:
        return self._verificacao is not None and self._verificacao.is_alive()

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
        """Diagnóstico da conexão. Nunca junto com uma execução: as duas usariam o SAP ao mesmo tempo."""
        if self.ocupado:
            raise RuntimeError("Aguarde a execução em andamento terminar para verificar o SAP.")
        self._verificacao = threading.Thread(target=self._verificar, daemon=True, name="verificar-sap")
        self._verificacao.start()

    def iniciar_cotacao(self, req, modo: str, plano_pastas) -> None:
        """Cotação nova (VA21) em segundo plano. plano_pastas: conferido antes, na tela (pode perguntar)."""
        if self.ocupado:
            raise RuntimeError("Já existe uma execução em andamento.")
        if modo not in modos_cotacao_da_interface(self._cfg):
            raise ValueError(f"Modo não disponível para cotação: {modo}")
        self._cancelar = threading.Event()
        self._thread = threading.Thread(target=self._rodar_cotacao, args=(req, modo, plano_pastas), daemon=True,
                                        name="cotacao")
        self._thread.start()

    def _rodar_cotacao(self, req, modo: str, plano_pastas) -> None:
        from cotacao_service import CotacaoService
        from storage_cotacao import CotacaoStorage
        com = _com_inicio()
        try:
            sap = self._fabrica(self._cfg, modo)          # o modo real (nunca "ENSAIO" para gravar)
            if hasattr(sap, "manter_janela"):
                sap.reaproveitar, sap.manter_janela = self.janela_mantida, True
                self.janela_mantida = None
            db = CotacaoStorage(self._db)
            try:
                servico = CotacaoService(
                    self._cfg, sap, db,
                    progresso=lambda e, s, d: self.fila.put(Evento("etapa", e, s, d, origem="cotacao")),
                    cancelar=self._cancelar,
                )
                resultado = servico.executar_cotacao(req, modo, plano_pastas)
                self.janela_mantida = getattr(sap, "janela_mantida", None)
            finally:
                db.close()
            self.fila.put(Evento("fim", resultado=resultado, origem="cotacao"))
        except Exception as erro:  # noqa: BLE001
            log.exception("Erro inesperado na cotação")
            self.fila.put(Evento("erro", detalhe=str(erro), origem="cotacao"))
        finally:
            _com_fim(com)

    def fechar_janela_mantida(self) -> None:
        """Ao fechar o programa: fecha a janela da automação que ficou no menu (se ainda estiver lá)."""
        janela, self.janela_mantida = self.janela_mantida, None
        if not janela:
            return
        com = _com_inicio()
        try:
            from sap_client import SapClient
            SapClient(self._cfg).fechar_por_id(janela)
        except Exception:  # noqa: BLE001 - fechar o programa nunca pode falhar por isso
            log.warning("Não foi possível fechar a janela mantida %s", janela)
        finally:
            _com_fim(com)

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
            if hasattr(sap, "manter_janela"):
                sap.reaproveitar, sap.manter_janela = self.janela_mantida, True
                self.janela_mantida = None      # só volta a valer se esta execução terminar bem
            db = Storage(self._db)   # conexão própria desta thread
            try:
                servico = ClaimService(
                    self._cfg, sap, db,
                    progresso=lambda e, s, d: self.fila.put(Evento("etapa", e, s, d)),
                    cancelar=self._cancelar,
                )
                resultado = servico.executar(req, modo)
                self.janela_mantida = getattr(sap, "janela_mantida", None)
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
