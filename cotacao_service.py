# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Orquestração da criação de cotação (VA21) + pastas na rede.

Modos: SIMULACAO (SAP simulado, sem pastas), ENSAIO (preenche a VA21 e NÃO grava;
sem pastas) e AUTOMATICO (grava a cotação e cria as pastas).

Regras (as mesmas dos claims):
- Tudo antes do Ctrl+S é desfazível: falha = FALHA_RECUPERAVEL/DEFINITIVA, nada gravado.
- Depois de enviar a gravação, só é CONCLUIDO com a mensagem de sucesso e o número;
  qualquer dúvida vira REVISAO_NECESSARIA e a gravação NUNCA é repetida sozinha.
- As pastas só são criadas depois de a cotação existir. Se falharem, a cotação
  continua criada (CONCLUIDO) e o aviso diz o que fazer.
"""

from __future__ import annotations

import logging
import time
import re
from dataclasses import dataclass, field

from claim_service import MODOS_QUE_GRAVAM, AvisoDesconhecido, ClaimService, Interrompido, _sem_ponto, parado_nada_gravado
from cotacao import CotacaoRequest, PlanoCotacao, planejar, resumo_plano, validar_cotacao
from pastas import PlanoPastas, criar_pastas
from sap_gateway import ElementoNaoEncontrado, ResultadoIncerto, SapError, SistemaIncorreto, StatusMessage
from state import Estado as E
from validators import ValidationIssue

log = logging.getLogger("claim.cotacao")

ETAPAS_COTACAO: tuple[tuple[str, str], ...] = (
    ("validacao", "Validação dos dados"),
    ("sessao", "Janela própria no SAP"),
    ("dados", "Dados iniciais (VA21)"),
    ("cliente", "Emissor e endereço"),
    ("validade", "Validade e referência"),
    ("linhas", "Linhas: material e centro"),
    ("cabecalho", "Cabeçalho: utilização e recebimento"),
    ("gravacao", "Gravação e número da cotação"),
    ("pastas", "Pastas da proposta na rede"),
)
MODOS_COTACAO = ("SIMULACAO", "ENSAIO", "AUTOMATICO")


def etapas_cotacao_do_modo(modo: str) -> tuple[tuple[str, str], ...]:
    if modo == "ENSAIO":
        return tuple(e for e in ETAPAS_COTACAO if e[0] not in ("gravacao", "pastas"))
    return ETAPAS_COTACAO


def numero_cotacao(status: StatusMessage) -> str:
    """'Cotação 21800001 foi gravado(a)' (V1/311) -> '21800001'. Vazio se não for a confirmação."""
    if status.tipo != "S":
        return ""
    confirmado = (status.id_mensagem.strip().upper(), status.numero_mensagem.strip()) == ("V1", "311") \
        or re.search(r"foi\s+gravad", status.texto or "", re.I)
    achado = re.search(r"(\d{5,})", status.texto or "")
    return achado.group(1) if (confirmado and achado) else ""


@dataclass
class ResultadoCotacao:
    cotacao_id: str
    estado: E
    mensagem: str
    problemas: list[ValidationIssue] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    numero: str = ""
    linhas: list[dict[str, str]] = field(default_factory=list)   # item, equipamento, rota, material, centro
    pasta: str = ""
    aviso_pastas: str = ""
    resumo: list[str] = field(default_factory=list)


class CotacaoService(ClaimService):
    """Reaproveita do serviço de claims: progresso, interrupção, avisos e conferência de linha."""

    criar_pastas = staticmethod(criar_pastas)   # substituível nos testes

    # Herdados do serviço de claims, mas sem sentido aqui (gravariam um claim no banco de cotações).
    def executar(self, *_args, **_kwargs):  # noqa: D401
        raise TypeError("CotacaoService cria cotações: use executar_cotacao().")

    def ensaio(self, *_args, **_kwargs):  # noqa: D401
        raise TypeError("CotacaoService cria cotações: use executar_cotacao().")

    def _inicio(self, etapa: str) -> None:
        # Depois de enviar a gravação (gravação e pastas), um pedido de parada não interrompe mais.
        if etapa in ("gravacao", "pastas"):
            self._atual = etapa
            self._inicio_etapa = time.monotonic()
            self._avisar(etapa, "ativo")
            return
        super()._inicio(etapa)

    def executar_cotacao(self, req: CotacaoRequest, modo: str, plano_pastas: PlanoPastas | None) -> ResultadoCotacao:
        if modo not in MODOS_COTACAO:
            raise ValueError(f"Modo desconhecido para cotação: {modo}")
        if modo in MODOS_QUE_GRAVAM and not self._cfg.automatico_habilitado:
            raise ValueError("Criar cotação grava no SAP: habilite em [execucao] automatico_habilitado = sim")
        self._atual = ""
        cid = self._db.criar(req, modo)
        log.info("[%s] Cotação %s iniciada (%s, %s, %s / %s)", cid, modo, req.tipo, req.equipamentos,
                 req.cliente, req.projeto)

        self._inicio("validacao")
        self._db.transitar(cid, E.VALIDANDO)
        problemas = validar_cotacao(req, self._cfg)
        if not problemas and modo == "AUTOMATICO" and plano_pastas is None:
            problemas = [ValidationIssue("projeto", "As pastas da proposta não foram conferidas antes de criar.")]
        if problemas:
            self._db.transitar(cid, E.RECEBIDO, f"{len(problemas)} problema(s) de validação")
            self._avisar("validacao", "falha", f"{len(problemas)} problema(s)")
            return ResultadoCotacao(cid, E.RECEBIDO, "Corrija os dados antes de criar.", problemas=problemas)
        if modo in MODOS_QUE_GRAVAM:
            repetidas = self._db.duplicidades(req, ignorar_id=cid)
            if repetidas:
                lista = ", ".join(f"{r.numero or r.id} ({r.estado.value})" for r in repetidas)
                self._db.registrar_evento(cid, "AVISO_DUPLICIDADE", lista)
                self._db.transitar(cid, E.RECEBIDO, "bloqueado por possível duplicidade")
                self._avisar("validacao", "falha", "cotação já criada para este projeto")
                return ResultadoCotacao(cid, E.RECEBIDO,
                                        f"Já existe cotação deste programa para {req.cliente or req.tipo} / "
                                        f"{req.projeto}: {lista}. Confira antes de criar outra.")
        plano = planejar(req, self._cfg)
        resumo = resumo_plano(plano, self._cfg)
        for linha in resumo:
            self._db.registrar_evento(cid, "PLANO", linha)
        self._ok("validacao", f"{len(plano.linhas)} linha(s) · {req.tipo}")
        self._db.transitar(cid, E.PRONTO_PARA_EXECUCAO)
        self._db.transitar(cid, E.EXECUTANDO)

        avisos: list[str] = []
        try:
            lidas = self._preencher(cid, plano, avisos)
        except Exception as erro:  # noqa: BLE001
            return self._falha(cid, erro, avisos, resumo)

        linhas = [dict(item=l.item, equipamento=p.equipamento, rota=p.rota, material=l.material, centro=l.centro)
                  for l, p in zip(lidas, plano.linhas)]
        if modo == "ENSAIO":
            self._db.transitar(cid, E.ENSAIO_CONCLUIDO, "VA21 preenchida; nada gravado")
            return ResultadoCotacao(
                cid, E.ENSAIO_CONCLUIDO,
                "Ensaio concluído: a VA21 está preenchida e NADA foi gravado. Confira a janela do SAP e "
                "saia sem gravar (Voltar → Não).", avisos=avisos, linhas=linhas, resumo=resumo)
        return self._gravar_cotacao(cid, req, modo, plano_pastas, avisos, linhas, resumo)

    # ------------------------------------------------------------------ VA21

    def _preencher(self, cid: str, plano: PlanoCotacao, avisos: list[str]):
        cfg = self._cfg.cotacao
        self._inicio("sessao")
        info = self._sap.sessao()
        self._db.registrar_sessao(cid, info.usuario, info.sistema, info.mandante)
        if (info.sistema, info.mandante) != (self._cfg.sistema, self._cfg.mandante):
            raise SistemaIncorreto(f"Sessão em {info.sistema}/{info.mandante}", etapa="sessao")
        self._ok("sessao", f"{info.sistema}/{info.mandante} · {info.usuario}")

        self._inicio("dados")
        self._sap.iniciar_cotacao(tipo_documento=cfg.tipo_documento, organizacao=cfg.organizacao,
                                  canal=cfg.canal, setor=plano.tipo.setor, escritorio=cfg.escritorio,
                                  equipe=plano.equipe)
        avisos += self._tratar_avisos(cid)
        self._ok("dados", f"{cfg.tipo_documento} · {cfg.organizacao}/{cfg.canal}/{plano.tipo.setor} · {plano.equipe}")

        self._inicio("cliente")
        janela = self._sap.preencher_cliente(emissor=plano.tipo.emissor, titulo=cfg.titulo_endereco,
                                             nome=plano.nome_endereco, cidade=plano.cidade,
                                             codigo_postal=plano.tipo.codigo_postal)
        if janela is not None and plano.tipo.codigo_postal:
            # Exportação: janela do endereço do emissor (26/10/2026). Só é confirmada se estiver em
            # [avisos_aceitos]; qualquer outra para aqui, antes de gravar.
            if not (self._aceito(janela.titulo) or (janela.texto and self._aceito(janela.texto))):
                self._db.registrar_evento(cid, "JANELA_DESCONHECIDA", f"{janela.titulo}: {janela.texto}")
                raise AvisoDesconhecido(f"Janela não prevista depois do endereço: {janela.titulo} {janela.texto}"
                                        .strip(), etapa="endereço do cliente")
            self._db.registrar_evento(cid, "AVISO_ACEITO", f"exportação: {janela.titulo}: {janela.texto}")
            avisos.append(janela.texto)
            log.info("[%s] Exportação: janela '%s' confirmada (%s)", cid, janela.titulo, janela.texto)
            self._sap.confirmar_popup()
        avisos += self._tratar_avisos(cid)
        self._ok("cliente", f"{plano.tipo.emissor} · {plano.nome_endereco or '—'} / {plano.cidade}")

        self._inicio("validade")
        status = self._sap.preencher_validade(validade=f"{plano.validade:%d.%m.%Y}", referencia=plano.referencia)
        avisos += self._tratar_avisos(cid)
        self._verificar_status(cid, status, "validade da cotação")
        self._ok("validade", f"até {plano.validade:%d/%m/%Y}")

        self._inicio("linhas")
        lidas = self._sap.preencher_linhas_novas([(l.material, l.centro, l.quantidade) for l in plano.linhas])
        avisos += self._tratar_avisos(cid)
        if len(lidas) != len(plano.linhas):
            raise SapError(f"A cotação ficou com {len(lidas)} linha(s); esperado {len(plano.linhas)}. "
                           "Nada foi gravado.", etapa="linhas da cotação")
        self._verificar_status(cid, lidas[0].status, "linhas da cotação")
        for lida, esperada in zip(lidas, plano.linhas):
            self._conferir_linha(lida, esperada.material, esperada.centro)
            self._db.registrar_evento(cid, "LINHA_PREENCHIDA",
                                      f"item {lida.item} · {esperada.equipamento} · {lida.material} · {lida.centro}")
        self._ok("linhas", " · ".join(f"{l.item} {p.equipamento}" for l, p in zip(lidas, plano.linhas)))

        self._inicio("cabecalho")
        status = self._sap.preencher_cabecalho(utilizacao=plano.tipo.utilizacao,
                                               data=f"{plano.recebimento:%d.%m.%Y}", hora=cfg.hora_recebimento)
        avisos += self._tratar_avisos(cid)
        self._verificar_status(cid, status, "cabeçalho da cotação")
        self._ok("cabecalho", f"utilização {plano.tipo.utilizacao} · recebido {plano.recebimento:%d/%m/%Y}")
        return lidas

    def _gravar_cotacao(self, cid, req, modo, plano_pastas, avisos, linhas, resumo) -> ResultadoCotacao:
        if self._cancelar is not None and self._cancelar.is_set():
            return self._falha(cid, Interrompido("Interrompido pelo usuário antes de gravar", etapa="gravacao"),
                               avisos, resumo)
        self._inicio("gravacao")
        # As linhas antes do envio: se o programa for morto no meio da gravação, a resolução manual
        # ("Cotação existe") ainda sabe os itens para criar os claims.
        self._db.registrar_linhas(cid, linhas)
        self._db.transitar(cid, E.AGUARDANDO_CONFIRMACAO, "gravação da cotação enviada")
        try:
            status = self._sap.gravar_cotacao_nova()
        except Exception as erro:  # noqa: BLE001 - resultado incerto
            return self._revisao_cotacao(cid, f"Sem confirmação da gravação ({erro})", avisos, linhas, resumo)
        self._db.registrar_evento(cid, f"STATUS_{status.tipo or '-'}", status.texto)
        for aviso in getattr(self._sap, "avisos_gravacao", []) or []:
            self._db.registrar_evento(cid, "AVISO_ACEITO", f"ao gravar: {aviso}")
        numero = numero_cotacao(status)
        if not numero:
            return self._revisao_cotacao(cid, f"Resposta do SAP sem confirmação: '{status.texto or 'vazia'}'",
                                         avisos, linhas, resumo)
        self._db.registrar_numero(cid, numero, linhas)
        self._ok("gravacao", f"cotação {numero}")

        pasta, aviso_pastas = "", ""
        self._inicio("pastas")
        if modo == "SIMULACAO" or plano_pastas is None:
            self._ok("pastas", "simulação: nenhuma pasta criada")
        else:
            try:
                pasta = str(self.criar_pastas(plano_pastas, numero))
                self._db.registrar_pasta(cid, pasta)
                self._ok("pastas", plano_pastas.base.name + " criada")
            except Exception as erro:  # noqa: BLE001 - a cotação já existe; só avisar
                aviso_pastas = (f"A cotação {numero} foi criada, mas as pastas não: {_sem_ponto(erro)}. "
                                "Crie a estrutura manualmente ou fale com o responsável pelo programa.")
                self._db.registrar_evento(cid, "FALHA_PASTAS", str(erro))
                self._avisar("pastas", "falha", "pastas não criadas")
        self._db.transitar(cid, E.CONCLUIDO, f"cotação {numero}" + (" (sem pastas)" if aviso_pastas else ""))
        try:
            self._sap.encerrar()
        except Exception:  # noqa: BLE001
            log.warning("[%s] Não foi possível fechar/manter a janela da automação", cid)
        itens = ", ".join(f"{l['item']} {l['equipamento']}" for l in linhas)
        return ResultadoCotacao(cid, E.CONCLUIDO, f"Cotação {numero} criada ({itens}).", avisos=avisos,
                                numero=numero, linhas=linhas, pasta=pasta, aviso_pastas=aviso_pastas,
                                resumo=resumo)

    # ------------------------------------------------------------------ falhas

    def _falha(self, cid, erro, avisos, resumo) -> ResultadoCotacao:
        etapa = getattr(erro, "etapa", "") or type(erro).__name__
        estado = (E.FALHA_DEFINITIVA if isinstance(erro, (ElementoNaoEncontrado, NotImplementedError))
                  else E.FALHA_RECUPERAVEL)
        self._db.registrar_falha(cid, etapa, str(erro))
        self._db.transitar(cid, estado, str(erro))
        self._avisar(self._atual or "validacao", "falha", str(erro))
        log.warning("[%s] %s na etapa '%s': %s", cid, estado.value, etapa, erro)
        return ResultadoCotacao(cid, estado, parado_nada_gravado(etapa, erro),
                                avisos=avisos, resumo=resumo)

    def _revisao_cotacao(self, cid, mensagem, avisos, linhas, resumo) -> ResultadoCotacao:
        self._db.registrar_linhas(cid, linhas)       # "Cotação existe…" depois precisa dos itens
        self._db.registrar_falha(cid, "gravar cotação", mensagem)
        self._db.transitar(cid, E.REVISAO_NECESSARIA, mensagem)
        self._avisar("gravacao", "falha", mensagem)
        log.warning("[%s] REVISAO_NECESSARIA: %s", cid, mensagem)
        return ResultadoCotacao(
            cid, E.REVISAO_NECESSARIA,
            f"{mensagem}. NÃO crie de novo: a cotação pode ter sido gravada. Confira na janela do SAP / VA23 "
            "e informe o resultado na aba Cotações (as pastas são criadas quando você informar o número).",
            avisos=avisos, linhas=linhas, resumo=resumo)
