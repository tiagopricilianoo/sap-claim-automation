# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Orquestração da criação do claim.

Modos:
    SIMULACAO   fluxo completo no SAP simulado
    ENSAIO      nota + atividades no SAP real; sem documento ZDC; NADA gravado
    ASSISTIDO   tudo, inclusive o documento ZDC (grava o documento); para ANTES
                de gravar o claim, para o usuário conferir e gravar
    AUTOMATICO  tudo, grava o claim e confirma

Regras que valem em qualquer modo:
- Falha antes de qualquer gravação: nada a desfazer (FALHA_RECUPERAVEL/DEFINITIVA).
- Falha depois de o documento ZDC ser gravado: REVISAO_NECESSARIA, com o número
  do documento; o documento nunca é recriado sozinho.
- Linha nova na cotação (VA22): é a PRIMEIRA gravação. Falha depois dela (ou
  sem confirmação dela): REVISAO_NECESSARIA com o item; a linha nunca é recriada
  sozinha e o claim deve ser criado para aquele item, sem marcar "linha nova".
- Depois de enviar a gravação do claim: o resultado só é CONCLUIDO com a
  mensagem de sucesso e o número; qualquer dúvida vira REVISAO_NECESSARIA.
  A gravação NUNCA é repetida automaticamente.
"""

from __future__ import annotations

import contextlib
import fnmatch
import logging
import re
import threading
import time
from dataclasses import dataclass, field, replace
from typing import Callable

from config import Settings
from models import ClaimRequest
from sap_gateway import (
    AtividadeSelecionada,
    ElementoNaoEncontrado,
    ResultadoIncerto,
    SapError,
    SapGateway,
    SistemaIncorreto,
    StatusMessage,
)
from state import Estado as E
from storage import Storage
from validators import ValidationIssue, validate

log = logging.getLogger("claim.servico")
MAX_JANELAS_DE_AVISO = 5

ETAPAS: tuple[tuple[str, str], ...] = (
    ("validacao", "Validação dos dados"),
    ("sessao", "Janela própria no SAP"),
    ("linha", "Linha nova na cotação (VA22)"),
    ("nota", "Preenchimento da nota"),
    ("avisos", "Avisos do SAP"),
    ("documento", "Documento ZDC e anexo"),
    ("atividades", "Atividades e responsáveis"),
    ("processamento", "Pôr em processamento"),
    ("gravacao", "Gravação e confirmação"),
)
ETAPAS_ENSAIO = tuple(e for e in ETAPAS if e[0] not in ("documento", "gravacao"))

# modo -> (inclui documento ZDC, grava o claim)
MODOS = {
    "SIMULACAO": (True, True),
    "ENSAIO": (False, False),
    "ASSISTIDO": (True, False),
    "AUTOMATICO": (True, True),
}
MODOS_QUE_GRAVAM = ("ASSISTIDO", "AUTOMATICO")


def etapas_do_modo(modo: str, linha_nova: bool = False) -> tuple[tuple[str, str], ...]:
    com_documento, grava = MODOS[modo]
    if modo == "ENSAIO" and linha_nova:
        # O ensaio da linha para depois de conferir a linha: o item ainda não existe no SAP.
        return tuple(e for e in ETAPAS if e[0] in ("validacao", "sessao", "linha"))
    return tuple(e for e in ETAPAS
                 if not (e[0] == "documento" and not com_documento)
                 and not (e[0] == "gravacao" and not grava)
                 and not (e[0] == "linha" and not linha_nova))


MENSAGEM_COTACAO_GRAVADA = ("V1", "311")   # "Cotação 1234567 foi gravado(a)" (print de 22/10/2026)


def cotacao_gravada(status: StatusMessage, cotacao: str) -> bool:
    """Confirmação da VA22: mensagem de sucesso V1/311 com o número da cotação."""
    if status.tipo != "S":
        return False
    codigo = (status.id_mensagem.strip().upper(), status.numero_mensagem.strip())
    if codigo != MENSAGEM_COTACAO_GRAVADA and not re.search(r"foi\s+gravad", status.texto or "", re.I):
        return False
    numeros = re.findall(r"\d+", status.texto or "")
    return cotacao.lstrip("0") in [n.lstrip("0") for n in numeros]


def numero_nota(texto: str) -> str:
    """'Nota 100063949 gravada' -> '100063949'."""
    import re
    achado = re.search(r"Nota\s+(\d+)\s+gravada", texto or "")
    return achado.group(1) if achado else ""


MINUTOS_LINHA_REPETIDA = 30   # outra "linha nova" na mesma cotação dentro deste prazo pede confirmação


def parado_nada_gravado(etapa: str, erro: object) -> str:
    """'Parado na etapa X: motivo. Nada foi gravado.' sem repetir a frase quando o motivo já a traz."""
    motivo = _sem_ponto(erro)
    if "nada foi gravado" in motivo.lower():
        return f"Parado na etapa '{etapa}': {motivo}."
    return f"Parado na etapa '{etapa}': {motivo}. Nada foi gravado."


def _sem_ponto(erro: object) -> str:
    """Texto do erro sem ponto final (as mensagens acrescentam o seu)."""
    return str(erro).rstrip(" .")


# progresso(etapa, situacao, detalhe) com situacao em: ativo | ok | falha
Progresso = Callable[[str, str, str], None]


@dataclass
class Resultado:
    execucao_id: str
    estado: E
    mensagem: str
    problemas: list[ValidationIssue] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    grade: list[dict[str, str]] = field(default_factory=list)
    conferencias: list[str] = field(default_factory=list)
    documento_dms: str = ""
    numero_nota: str = ""
    linha_criada: str = ""   # item acrescentado na cotação nesta execução
    confirmar: str = ""      # "linha_extra": a tela pergunta ao usuário e, se ele confirmar, executa de novo


class AvisoDesconhecido(SapError):
    """Janela ou mensagem que não está na lista de avisos aceitos."""


class Interrompido(SapError):
    """O usuário pediu para parar. Só é aceito entre etapas, antes da gravação do claim."""


class ClaimService:
    def __init__(self, settings: Settings, sap: SapGateway, storage: Storage,
                 progresso: Progresso | None = None, cancelar: threading.Event | None = None):
        self._cfg = settings
        self._sap = sap
        self._db = storage
        self._progresso = progresso
        self._cancelar = cancelar
        self._atual = ""
        self._inicio_etapa = 0.0

    # ------------------------------------------------------------------ entradas

    def ensaio(self, req: ClaimRequest) -> Resultado:
        return self.executar(req, "ENSAIO")

    def executar(self, req: ClaimRequest, modo: str) -> Resultado:
        if modo not in MODOS:
            raise ValueError(f"Modo desconhecido: {modo}")
        if modo in MODOS_QUE_GRAVAM and not self._cfg.automatico_habilitado:
            raise ValueError(f"Modo {modo} grava no SAP: habilite em [execucao] automatico_habilitado = sim")
        com_documento, grava = MODOS[modo]
        com_documento = com_documento and not req.sem_anexo
        req = req.normalizado()       # '010' = '10' no SAP: grava e compara sempre sem zeros à esquerda
        self._atual = ""

        eid = self._db.criar_execucao(req, modo)
        log.info("[%s] %s iniciado (tipo %s, ordem %s/%s)", eid, modo, req.tipo, req.ordem, req.item)

        # B - validação local
        self._inicio("validacao")
        self._db.transitar(eid, E.VALIDANDO)
        problemas = validate(req, self._cfg)
        if problemas:
            self._db.transitar(eid, E.RECEBIDO, f"{len(problemas)} problema(s) de validação")
            self._avisar("validacao", "falha", f"{len(problemas)} problema(s)")
            return Resultado(eid, E.RECEBIDO, "Corrija os dados antes de executar.", problemas=problemas)

        # C - verificação prévia de duplicidade (histórico local)
        if req.linha_nova:
            sem_claim = self._db.linhas_sem_claim(req.ordem, ignorar_id=eid, modo=modo)
            if sem_claim and modo in MODOS_QUE_GRAVAM:
                lista = ", ".join(f"item {(a.linha_criada or '?').lstrip('?') or '?'}"
                                  f"{' (sem confirmação)' if (a.linha_criada or '?').startswith('?') else ''} "
                                  f"— {a.estado.value}, execução {a.id}" for a in sem_claim)
                self._db.registrar_evento(eid, "AVISO_LINHA_PENDENTE", lista)
                self._db.transitar(eid, E.RECEBIDO, "bloqueado: linha anterior sem claim")
                self._avisar("validacao", "falha", "linha anterior sem claim")
                return Resultado(
                    eid, E.RECEBIDO,
                    f"Nada foi gravado. A cotação {req.ordem} já tem uma linha nova sem claim: {lista}. "
                    "Crie o claim para esse item SEM marcar 'Criar linha nova' (se a execução estiver em "
                    "Pendências, resolva lá primeiro).",
                )
            recentes = self._db.linhas_recentes(req.ordem, MINUTOS_LINHA_REPETIDA, ignorar_id=eid)
            if recentes and modo in MODOS_QUE_GRAVAM and not req.confirmar_linha_extra:
                lista = ", ".join(f"item {a.linha_criada} (claim {a.numero_nota or '?'})" for a in recentes)
                self._db.registrar_evento(eid, "AVISO_LINHA_RECENTE", lista)
                self._db.transitar(eid, E.RECEBIDO, "linha nova logo depois de outra: pedir confirmação")
                self._avisar("validacao", "falha", "confirmar outra linha")
                return Resultado(
                    eid, E.RECEBIDO,
                    f"Nada foi gravado. Há pouco foi criada uma linha nova nesta cotação: {lista}. "
                    "Confirme se precisa MESMO de mais uma linha.",
                    confirmar="linha_extra",
                )
        anteriores = [] if req.linha_nova else self._db.possiveis_duplicidades(req.ordem, req.item,
                                                                             ignorar_id=eid, modo=modo)
        if anteriores:
            lista = ", ".join(f"{a.id} ({a.estado.value}{' nota ' + a.numero_nota if a.numero_nota else ''})"
                              for a in anteriores)
            self._db.registrar_evento(eid, "AVISO_DUPLICIDADE", "execuções anteriores: " + lista)
            if modo in MODOS_QUE_GRAVAM:
                self._db.transitar(eid, E.RECEBIDO, "bloqueado por possível duplicidade")
                self._avisar("validacao", "falha", "possível duplicidade")
                return Resultado(
                    eid, E.RECEBIDO,
                    f"Já existe execução para a ordem {req.ordem}/{req.item}: {lista}. "
                    "Confira no SAP antes de criar outro claim.",
                )
        # Conferir de novo E reservar numa transação só (BEGIN IMMEDIATE): outro programa usando o mesmo
        # histórico não consegue passar pela mesma conferência entre a leitura e a reserva.
        if modo in MODOS_QUE_GRAVAM:
            lote = getattr(self._db, "lote", None)
            with (lote() if callable(lote) else contextlib.nullcontext()):
                if req.linha_nova:
                    conflito = self._db.linhas_sem_claim(req.ordem, ignorar_id=eid, modo=modo)
                else:
                    conflito = [a for a in self._db.possiveis_duplicidades(req.ordem, req.item, ignorar_id=eid,
                                                                           modo=modo)
                                if a.id not in {x.id for x in anteriores}]
                if conflito:
                    self._db.transitar(eid, E.RECEBIDO, "bloqueado: outra execução começou ao mesmo tempo")
                else:
                    self._db.transitar(eid, E.PRONTO_PARA_EXECUCAO)
                    self._db.transitar(eid, E.EXECUTANDO)
            if conflito:
                self._avisar("validacao", "falha", "outra execução ao mesmo tempo")
                return Resultado(eid, E.RECEBIDO, "Nada foi gravado. Outra execução da mesma ordem/item começou "
                                 f"ao mesmo tempo ({conflito[0].id}). Confira no Histórico antes de tentar de novo.")
        else:
            self._db.transitar(eid, E.PRONTO_PARA_EXECUCAO)
            self._db.transitar(eid, E.EXECUTANDO)
        self._ok("validacao", "dados válidos" + (" (já houve execução desta ordem/item)" if anteriores else ""))

        avisos: list[str] = []
        linhas: list[dict[str, str]] = []
        conferencias: list[str] = []
        documento = ""
        linha_item = ""
        try:
            # D - janela própria
            self._inicio("sessao")
            info = self._sap.sessao()
            self._db.registrar_sessao(eid, info.usuario, info.sistema, info.mandante)
            if (info.sistema, info.mandante) != (self._cfg.sistema, self._cfg.mandante):
                raise SistemaIncorreto(f"Sessão em {info.sistema}/{info.mandante}", etapa="sessao")
            self._ok("sessao", f"{info.sistema}/{info.mandante} · {info.usuario}")

            # Linha nova na cotação (VA22): primeira gravação no SAP
            if req.linha_nova:
                self._inicio("linha")
                rota = self._cfg.rota(req.tipo)
                self._sap.abrir_cotacao(req.ordem)
                avisos += self._tratar_avisos(eid)
                linha = self._sap.preencher_linha(material=rota.material, centro=rota.centro,
                                                  quantidade=self._cfg.linha_quantidade)
                avisos += self._tratar_avisos(eid)
                self._verificar_status(eid, linha.status, "linha da cotação")
                self._conferir_linha(linha, rota.material, rota.centro)
                descricao_linha = f"item {linha.item} · material {linha.material} · centro {linha.centro}"
                self._db.registrar_evento(eid, "LINHA_PREENCHIDA", descricao_linha)
                if modo == "ENSAIO":
                    self._ok("linha", descricao_linha + " · não gravada")
                    self._db.transitar(eid, E.ENSAIO_CONCLUIDO, f"linha {linha.item} preenchida na VA22; nada gravado")
                    return Resultado(
                        eid, E.ENSAIO_CONCLUIDO,
                        f"Ensaio da linha concluído: {descricao_linha}. Nada foi gravado. "
                        "Na janela do SAP, saia da VA22 SEM gravar (Voltar → Não).",
                        avisos=avisos,
                    )
                self._db.registrar_linha_incerta(eid, linha.item)
                linha_item = "?" + linha.item     # "?" = gravação enviada, ainda sem confirmação
                status = self._sap.gravar_cotacao(req.ordem)
                self._db.registrar_evento(eid, f"STATUS_{status.tipo or '-'}", status.texto)
                for aviso in getattr(self._sap, "avisos_gravacao", []) or []:
                    self._db.registrar_evento(eid, "AVISO_ACEITO", f"ao gravar a cotação: {aviso}")
                if not cotacao_gravada(status, req.ordem):
                    raise ResultadoIncerto(f"Gravação da cotação sem confirmação: '{status.texto or 'vazia'}'",
                                           etapa="gravar cotação")
                linha_item = linha.item
                self._db.registrar_linha(eid, linha_item)
                req = replace(req, item=linha_item)
                self._ok("linha", f"item {linha_item} gravado na cotação {req.ordem}")

            # E - Fase 1: nota
            self._inicio("nota")
            self._sap.abrir_criacao(self._cfg.tipo_nota)
            self._sap.preencher_nota(
                descricao=req.descricao, texto_livre=req.texto_livre,
                causa_grupo=self._cfg.causa_grupo, causa_codigo=self._cfg.causa_codigo,
                prioridade=self._cfg.prioridade, ordem=req.ordem, item=req.item,
            )
            status = self._sap.enter()
            self._ok("nota", f"CLM1 · {self._cfg.tipo_nota} · ordem {req.ordem}/{req.item}")

            self._inicio("avisos")
            avisos += self._tratar_avisos(eid)
            self._verificar_status(eid, status, "enter da nota")
            self._ok("avisos", f"{len(avisos)} aviso(s) aceito(s)" if avisos else "nenhum aviso")

            # E - Fase 2: documento ZDC (primeira gravação no SAP)
            if req.sem_anexo and MODOS[modo][0]:
                self._inicio("documento")
                self._db.registrar_evento(eid, "SEM_ANEXO", "claim sem anexo: documento não criado")
                self._ok("documento", "sem anexo · etapa pulada")
            elif com_documento:
                self._inicio("documento")
                self._db.registrar_evento(eid, "DOCUMENTO_ENVIADO", req.nome_arquivo)
                documento = self._sap.criar_documento(
                    tipo=self._cfg.doc_tipo, descricao=req.nome_arquivo, laboratorio=self._cfg.doc_laboratorio,
                    arquivo=req.arquivo, aplicacao=self._cfg.aplicacao_para(req.arquivo),
                )
                self._db.registrar_documento(eid, documento)
                self._ok("documento", f"{self._cfg.doc_tipo} {documento}")

            # E - Fase 3: atividades
            self._inicio("atividades")
            atividades = self._atividades(req, info.usuario)
            linhas = self._sap.selecionar_atividades(atividades, self._cfg.raiz_arvore)
            conferencias = self._conferir_grade(eid, atividades, linhas)
            if conferencias and modo != "ENSAIO":
                raise SapError("Atividades diferentes do configurado: " + "; ".join(conferencias),
                               etapa="conferência das atividades")
            avisos += self._tratar_avisos(eid)
            self._ok("atividades", f"{len(linhas)} atividade(s) transferida(s)")

            # E - bandeira verde, sempre por último antes de gravar (não grava nada)
            self._inicio("processamento")
            status = self._sap.por_em_processamento()
            avisos += self._tratar_avisos(eid)
            self._verificar_status(eid, status, "pôr em processamento")
            self._db.registrar_evento(eid, "EM_PROCESSAMENTO", status.texto or "sem mensagem")
            self._ok("processamento", status.texto or "status alterado")

        except Exception as erro:  # noqa: BLE001
            return self._falha_antes_do_claim(eid, erro, documento, avisos, linhas, linha_item)

        extras = dict(avisos=avisos, grade=linhas, conferencias=conferencias, documento_dms=documento,
                      linha_criada=linha_item)

        if modo == "ENSAIO":
            self._db.transitar(eid, E.ENSAIO_CONCLUIDO, "nota + atividades preenchidas; sem ZDC; nada gravado")
            log.info("[%s] Ensaio concluído sem gravar", eid)
            return Resultado(eid, E.ENSAIO_CONCLUIDO,
                             "Ensaio concluído. Nada foi gravado. Confira a janela do SAP e saia com Voltar → Não.",
                             **extras)

        if not grava:   # ASSISTIDO
            doc = f"documento {self._cfg.doc_tipo} {documento} gravado" if documento else "sem anexo"
            self._db.transitar(eid, E.REVISAO_NECESSARIA, f"assistido: {doc}; claim aguardando gravação manual")
            return Resultado(
                eid, E.REVISAO_NECESSARIA,
                f"Tudo preenchido ({doc}). Confira a janela do SAP e grave o claim manualmente (Ctrl+S).",
                **extras,
            )

        return self._gravar(eid, extras)

    # ------------------------------------------------------------------ gravação do claim

    def _gravar(self, eid: str, extras: dict) -> Resultado:
        if self._cancelar is not None and self._cancelar.is_set():
            # Parada atendida ANTES de enviar a gravação do claim. Só vira revisão se algo já foi
            # gravado (documento ZDC ou linha incerta); sem nada gravado é uma falha comum.
            return self._falha_antes_do_claim(
                eid, Interrompido("Interrompido pelo usuário antes de gravar o claim", etapa="gravacao"),
                extras.get("documento_dms", ""), extras.get("avisos", []), extras.get("grade", []),
                extras.get("linha_criada", ""))
        self._inicio("gravacao")
        # Registrado ANTES de enviar: se o programa cair agora, a execução fica pendente.
        self._db.transitar(eid, E.AGUARDANDO_CONFIRMACAO, "gravação do claim enviada")
        try:
            status = self._sap.gravar_nota()
        except Exception as erro:  # noqa: BLE001 - qualquer coisa aqui é resultado incerto
            return self._revisao(eid, "gravar claim", f"Sem confirmação da gravação ({erro})", extras)

        self._db.registrar_evento(eid, f"STATUS_{status.tipo or '-'}", status.texto)
        numero = numero_nota(status.texto)
        if status.tipo != "S" or not numero:
            return self._revisao(eid, "gravar claim",
                                 f"Resposta do SAP sem confirmação: '{status.texto or 'vazia'}'", extras)

        self._db.registrar_nota(eid, numero)
        self._db.transitar(eid, E.CONCLUIDO, f"nota {numero} gravada")
        self._ok("gravacao", f"nota {numero}")
        log.info("[%s] Claim %s gravado (documento %s)", eid, numero, extras.get("documento_dms"))
        try:
            self._sap.encerrar()
        except Exception:  # noqa: BLE001 - fechar a janela não muda o resultado
            log.warning("[%s] Não foi possível fechar a janela da automação", eid)
        linha = extras.get("linha_criada", "")
        mensagem = (f"Linha {linha} criada na cotação e claim {numero} criado com sucesso." if linha
                    else f"Claim {numero} criado com sucesso.")
        return Resultado(eid, E.CONCLUIDO, mensagem, numero_nota=numero, **extras)

    def _revisao(self, eid: str, etapa: str, mensagem: str, extras: dict) -> Resultado:
        self._db.registrar_falha(eid, etapa, mensagem)
        self._db.transitar(eid, E.REVISAO_NECESSARIA, mensagem)
        self._avisar(self._atual or etapa, "falha", mensagem)
        log.warning("[%s] REVISAO_NECESSARIA: %s", eid, mensagem)
        doc = extras.get("documento_dms")
        linha = extras.get("linha_criada", "")
        if linha and self._atual != "gravacao":   # claim ainda não enviado: orientar sobre a linha
            item = linha.lstrip("?")
            gravada = "pode ter sido gravada" if linha.startswith("?") else "JÁ FOI GRAVADA"
            orientacao = (f" A linha {item} da cotação {gravada}. Resolva em Pendências (a tela pergunta "
                          f"sobre a linha e sobre o claim) e depois crie o claim para o item {item} SEM marcar "
                          "'Criar linha nova'.")
        else:
            orientacao = ""
        return Resultado(
            eid, E.REVISAO_NECESSARIA,
            f"{mensagem}. NÃO crie de novo: confira no SAP se o claim existe"
            + (f" (documento ZDC {doc})" if doc else "") + "." + orientacao,
            **extras,
        )

    def _falha_antes_do_claim(self, eid, erro, documento, avisos, linhas, linha_item="") -> Resultado:
        etapa = getattr(erro, "etapa", "") or type(erro).__name__
        documento_talvez_gravado = self._atual == "documento" and isinstance(erro, ResultadoIncerto)
        if linha_item and not linha_item.startswith("?") and not (documento or documento_talvez_gravado):
            # Linha CONFIRMADA e nada do claim gravado (nem ZDC): não é pendência. O claim do item pode ser
            # criado normalmente; uma nova "linha nova" continua bloqueada até esse claim existir.
            self._db.registrar_falha(eid, etapa, str(erro))
            self._db.transitar(eid, E.FALHA_RECUPERAVEL, f"linha {linha_item} gravada; claim não criado: {erro}")
            self._avisar(self._atual or "validacao", "falha", str(erro))
            log.warning("[%s] Linha %s gravada, claim não criado: %s", eid, linha_item, erro)
            return Resultado(
                eid, E.FALHA_RECUPERAVEL,
                f"A linha {linha_item} FOI GRAVADA na cotação, mas o claim não foi criado (parou em "
                f"'{etapa}': {_sem_ponto(erro)}). Crie agora o claim para o item {linha_item} SEM marcar "
                "'Criar linha nova'.",
                avisos=avisos, linha_criada=linha_item)
        if documento or documento_talvez_gravado or linha_item:
            # O documento ZDC ou a linha da cotação existem (ou podem existir): nunca recriar.
            if documento or documento_talvez_gravado:
                ref = f"do documento ZDC {documento or '(possivelmente criado)'}"
            else:
                ref = f"da linha {linha_item.lstrip('?')} na cotação"
            return self._revisao(eid, etapa, f"Falha em '{etapa}' depois {ref}: {erro}",
                                 dict(avisos=avisos, grade=linhas, documento_dms=documento,
                                      linha_criada=linha_item))
        estado = (E.FALHA_DEFINITIVA if isinstance(erro, (ElementoNaoEncontrado, NotImplementedError))
                  else E.FALHA_RECUPERAVEL)
        self._db.registrar_falha(eid, etapa, str(erro))
        self._db.transitar(eid, estado, str(erro))
        self._avisar(self._atual or "validacao", "falha", str(erro))
        log.warning("[%s] %s na etapa '%s': %s", eid, estado.value, etapa, erro)
        return Resultado(eid, estado, parado_nada_gravado(etapa, erro),
                         avisos=avisos)

    # ------------------------------------------------------------------ atividades

    def _atividades(self, req: ClaimRequest, usuario: str) -> list[AtividadeSelecionada]:
        return [
            AtividadeSelecionada(a.descricao, a.subgrupo, a.pasta, a.no, a.responsavel_para(usuario))
            for a in self._cfg.rota(req.tipo).atividades
        ]

    def _conferir_grade(self, eid: str, atividades: list[AtividadeSelecionada],
                        linhas: list[dict[str, str]]) -> list[str]:
        """Registra a grade e aponta divergências com o settings.ini.

        Divergências de TEXTO viram itens de conferência. Linhas a mais ou a
        menos são sempre erro.
        """
        for i, linha in enumerate(linhas, 1):
            self._db.registrar_evento(eid, "GRADE_ATIVIDADES",
                                      f"linha {i}: " + " | ".join(f"{k}={v}" for k, v in linha.items()))
        if len(linhas) != len(atividades):
            raise SapError(f"Grade com {len(linhas)} linha(s); esperado {len(atividades)}",
                           etapa="grade de atividades")

        conferencias: list[str] = []
        for i, (atividade, linha) in enumerate(zip(atividades, linhas), 1):
            valores = {v.upper() for v in linha.values()}
            esperados = [("descrição", atividade.descricao), ("sub grupo", atividade.subgrupo),
                         ("responsável", atividade.responsavel)]
            for nome, valor in esperados:
                if valor and valor.upper() not in valores:
                    conferencias.append(f"Linha {i}: {nome} '{valor}' não encontrado na grade")
        for item in conferencias:
            self._db.registrar_evento(eid, "CONFERIR_ATIVIDADE", item)
        return conferencias

    # ------------------------------------------------------------------ progresso

    def _avisar(self, etapa: str, situacao: str, detalhe: str = "") -> None:
        if self._progresso is not None:
            try:
                self._progresso(etapa, situacao, detalhe)
            except Exception:  # noqa: BLE001 - a interface nunca derruba a execução
                log.exception("Falha ao notificar progresso")

    def _inicio(self, etapa: str) -> None:
        # A gravação do claim trata o pedido de parada em _gravar (antes de enviar).
        if self._atual and etapa != "gravacao" and self._cancelar is not None and self._cancelar.is_set():
            raise Interrompido("Interrompido pelo usuário", etapa=self._atual)
        self._atual = etapa
        self._inicio_etapa = time.monotonic()
        self._avisar(etapa, "ativo")

    def _ok(self, etapa: str, detalhe: str = "") -> None:
        if self._inicio_etapa:
            log.info("Etapa '%s' em %.1f s (%s)", etapa, time.monotonic() - self._inicio_etapa, detalhe)
        self._avisar(etapa, "ok", detalhe)

    # ------------------------------------------------------------------ avisos

    def _aceito(self, texto: str) -> bool:
        texto = " ".join(texto.split())
        return any(fnmatch.fnmatchcase(texto, padrao) for padrao in self._cfg.avisos_aceitos)

    def _tratar_avisos(self, eid: str) -> list[str]:
        vistos: list[str] = []
        for _ in range(MAX_JANELAS_DE_AVISO):
            popup = self._sap.popup_aberto()
            if popup is None:
                return vistos
            descricao = f"{popup.titulo}: {popup.texto}".strip(": ")
            if not self._aceito(popup.texto):
                self._db.registrar_evento(eid, "JANELA_DESCONHECIDA", descricao)
                raise AvisoDesconhecido(f"Janela não prevista: {descricao}", etapa="janela de aviso")
            self._db.registrar_evento(eid, "AVISO_ACEITO", descricao)
            vistos.append(popup.texto)
            self._sap.confirmar_popup()
        raise AvisoDesconhecido("Janelas de aviso em sequência além do limite", etapa="janela de aviso")

    def _verificar_status(self, eid: str, status: StatusMessage, etapa: str) -> None:
        if not status.tipo:
            return
        self._db.registrar_evento(eid, f"STATUS_{status.tipo}", status.texto)
        if status.e_erro:
            raise SapError(f"SAP: {status.texto}", etapa=etapa)
        if status.tipo == "W" and not self._aceito(status.texto):
            raise AvisoDesconhecido(f"Aviso não previsto: {status.texto}", etapa=etapa)

    @staticmethod
    def _conferir_linha(linha, material: str, centro: str) -> None:
        """A linha lida da tela tem que ter o material e o centro configurados (antes de gravar)."""
        lido = {"material": linha.material.lstrip("0"), "centro": linha.centro.strip()}
        esperado = {"material": material.lstrip("0"), "centro": centro.strip()}
        erradas = [f"{k} '{lido[k] or 'vazio'}' (esperado {esperado[k]})" for k in lido if lido[k] != esperado[k]]
        if not linha.item.isdigit():
            erradas.append(f"item '{linha.item or 'vazio'}'")
        if erradas:
            raise SapError("Linha nova diferente do esperado: " + ", ".join(erradas) + ". Nada foi gravado.",
                           etapa="conferência da linha")
