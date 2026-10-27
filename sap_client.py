# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Cliente do SAP GUI real, via SAP GUI Scripting (pywin32).

Janela própria (decisão do projeto, opção B):
    A automação SEMPRE abre uma janela nova (novo modo) na conexão já logada
    e trabalha só nela. As janelas do usuário nunca são usadas nem alteradas.
    Nenhum login é feito: a janela nova herda a sessão autenticada.

Implementado: janela própria, CLM1, nota, avisos, atividades, documento ZDC
(anexo + arquivar + gravar) e gravação do claim. Consulta na CLM3: pendente.

Todos os IDs técnicos vieram de gravações de script reais (Script1/Script2).
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from config import Settings
from sap_gateway import (
    AtividadeSelecionada,
    LinhaPreenchida,
    ElementoNaoEncontrado,
    Popup,
    PopupInesperado,
    ResultadoIncerto,
    SessaoIndisponivel,
    SessionInfo,
    SistemaIncorreto,
    StatusMessage,
    ValorRejeitado,
)

log = logging.getLogger("claim.sap")

# ----------------------------------------------------------------------- IDs técnicos
OKCODE = "wnd[0]/tbar[0]/okcd"
STATUS = "wnd[0]/sbar"
TIPO_NOTA = "wnd[0]/usr/cmbRIWO00-QMART"
_T1 = ("wnd[0]/usr/tabsTAB_GROUP_10/tabp10\\TAB01/ssubSUB_GROUP_10:SAPLIQS0:7235"
       "/subCUSTOM_SCREEN:SAPLIQS0:7212")
TEXTO_LIVRE = _T1 + "/subSUBSCREEN_1:SAPLIQS0:7715/cntlTEXT/shellcont/shell"
DESCRICAO = _T1 + "/subSUBSCREEN_1:SAPLIQS0:7715/txtRIWO00-HEADKTXT"
CAUSA_GRUPO = _T1 + "/subSUBSCREEN_2:SAPMCLAIM:7800/ctxtCLAIM-URGRP"
CAUSA_CODIGO = _T1 + "/subSUBSCREEN_2:SAPMCLAIM:7800/ctxtCLAIM-URCOD"
PRIORIDADE = _T1 + "/subSUBSCREEN_2:SAPMCLAIM:7800/cmbVIQMEL-PRIOK"
ORDEM = _T1 + "/subSUBSCREEN_3:SAPLIQS0:7740/subBELEG:SAPMCLAIM:3071/ctxtVIQMEL-LS_KDAUF"
ITEM = _T1 + "/subSUBSCREEN_3:SAPLIQS0:7740/subBELEG:SAPMCLAIM:3071/ctxtVIQMEL-LS_KDPOS"
POPUP = "wnd[1]"
POPUP_OK = "wnd[1]/tbar[0]/btn[0]"
ABA_SINTESE = "wnd[0]/usr/tabsTAB_GROUP_10/tabp10\\TAB17"
BARRA_ATIVIDADES = "wnd[0]/shellcont/shell"
LINK_SELECAO_MULTIPLA = ("0010", "Column01")
ARVORE = "wnd[1]/usr/cntlCONTAINER/shellcont/shell[0]"
GRADE = "wnd[1]/usr/cntlCONTAINER2/shellcont/shell"
COLUNA_RESPONSAVEL = "RESP"
COLUNA_DESCRICAO = "DS_ATIVIDADE"
COLUNA_SUBGRUPO = "SUB_GRUPO"
COLUNAS_GRADE = ("GRUPO", COLUNA_SUBGRUPO, COLUNA_DESCRICAO, COLUNA_RESPONSAVEL)
TRANSFERIR = "wnd[1]/tbar[0]/btn[44]"
# Bandeira verde "Pôr em processamento" (Script4, 21/10/2026). btn[14] é só a POSIÇÃO
# na barra: antes de clicar, a dica do botão precisa mencionar "processamento".
BANDEIRA_PROCESSAMENTO = "wnd[0]/tbar[1]/btn[14]"
DICA_PROCESSAMENTO = "PROCESS"

# Fase 2: documento ZDC (Script1, 20/10/2026)
ABA_COMPLEMENTARES = "wnd[0]/usr/tabsTAB_GROUP_10/tabp10\\TAB02"
_DVS = ("wnd[0]/usr/tabsTAB_GROUP_10/tabp10\\TAB02/ssubSUB_GROUP_10:SAPLIQS0:7235"
        "/subCUSTOM_SCREEN:SAPLIQS0:7212/subSUBSCREEN_2:SAPLIQS0:7801/ssubDVS:SAPLCV140:0204")
TODAS_VERSOES = _DVS + "/subBUTTON:SAPLCV140:0203/radGF_ALLE"
CRIAR_DOCUMENTO = _DVS + "/subDOC_ALV:SAPLCV140:0207/btnY1"
_DOC = "wnd[0]/usr/tabsTAB_MAIN/tabpTSMAIN/ssubSCR_MAIN:SAPLCV110:0102"
DOC_DESCRICAO = _DOC + "/txtDRAT-DKTXT"
DOC_LABORATORIO = _DOC + "/ctxtDRAW-LABOR"
DOC_PROCURAR_ARQUIVO = _DOC + "/btnPB_FILE_BROWSER"
ARQ_PASTA = "wnd[1]/usr/ctxtDY_PATH"        # A CONFIRMAR: não apareceu na gravação (já vinha preenchido)
ARQ_NOME = "wnd[1]/usr/ctxtDY_FILENAME"
ARQ_OK = "wnd[1]/tbar[0]/btn[0]"
ORIGINAIS = _DOC + "/cntlCTL_FILES1/shellcont/shell/shellcont[1]/shell"
NO_PRIMEIRO_ORIGINAL = "          1"
MENU_ARQUIVAR = "CF_IMPORT"
LISTA_POPUP = "wnd[1]/usr"
TECLA_GRAVAR = 11
TECLA_ESCOLHER = 2

# Cotação: linha nova na VA22 (script "VA21.vbs" e prints de 22/10/2026; tabela e centro
# vêm também do programa de criação de cotação, já usado em produção).
COTACAO_NUMERO = "wnd[0]/usr/ctxtVBAK-VBELN"
_VISAO = "wnd[0]/usr/tabsTAXI_TABSTRIP_OVERVIEW"
ABA_ITENS = _VISAO + "/tabpT\\02"
TABELA_ITENS = (ABA_ITENS + "/ssubSUBSCREEN_BODY:SAPMV45A:4411/subSUBSCREEN_TC:SAPMV45A:4912"
                "/tblSAPMV45ATCTRL_U_ERF_ANGEBOT")
ABA_ITENS_2 = _VISAO + "/tabpT\\01"      # onde o programa de cotação digita o centro, se não estiver na outra
TABELA_ITENS_2 = (ABA_ITENS_2 + "/ssubSUBSCREEN_BODY:SAPMV45A:4400/subSUBSCREEN_TC:SAPMV45A:4900"
                  "/tblSAPMV45ATCTRL_U_ERF_AUFTRAG")
COL_ITEM, COL_MATERIAL, COL_QUANTIDADE, COL_CENTRO = "VBAP-POSNR", "RV45A-MABNR", "RV45A-KWMENG", "VBAP-WERKS"
BOTAO_GRAVAR = "wnd[0]/tbar[0]/btn[11]"
GRAVAR_INCOMPLETO = "wnd[1]/usr/btnSPOP-VAROPTION1"     # botão "Gravar"
TITULO_INCOMPLETO = "GRAVAR DOCUMENTO INCOMPLETO"
MAX_PAGINAS_TABELA = 50
MAX_JANELAS_AO_GRAVAR = 4    # avisos + "Gravar documento incompleto"
# Cotação nova (VA21): IDs do programa "Criar Cotação" (em produção até out/2026)
VA21_TIPO = "wnd[0]/usr/ctxtVBAK-AUART"
VA21_ORGANIZDCAO = "wnd[0]/usr/ctxtVBAK-VKORG"
VA21_CANAL = "wnd[0]/usr/ctxtVBAK-VTa empresa"
VA21_SETOR = "wnd[0]/usr/ctxtVBAK-SPART"
VA21_ESCRITORIO = "wnd[0]/usr/ctxtVBAK-VKBUR"
VA21_EQUIPE = "wnd[0]/usr/ctxtVBAK-VKGRP"
_CAB_VENDAS = "wnd[0]/usr/subSUBSCREEN_HEADER:SAPMV45A:4021"
VA21_EMISSOR = _CAB_VENDAS + "/subPART-SUB:SAPMV45A:4701/ctxtKUAGV-KUNNR"
VA21_REFERENCIA = _CAB_VENDAS + "/txtVBKD-BSTKD"
VA21_BOTAO_CABECALHO = _CAB_VENDAS + "/btnBT_HEAD"
_END = "wnd[1]/usr/subGCS_ADDRESS:SAPLSZA1:0300/subCOUNTRY_SCREEN:SAPLSZA1:0301"
END_TITULO = _END + "/cmbSZA1_D0100-TITLE_MEDI"
END_NOME = _END + "/txtADDR1_DATA-NAME1"
END_CIDADE = _END + "/txtADDR1_DATA-CITY1"
END_CEP = _END + "/txtADDR1_DATA-POST_CODE1"
END_OK = "wnd[1]/tbar[0]/btn[0]"
VA21_VALIDADE = ABA_ITENS + "/ssubSUBSCREEN_BODY:SAPMV45A:4411/ctxtVBAK-BNDDT"
_CAB = "wnd[0]/usr/tabsTAXI_TABSTRIP_HEAD"
VA21_UTILIZDCAO = _CAB + "/tabpT\\01/ssubSUBSCREEN_BODY:SAPMV45A:4301/cmbVBAK-ABRVW"
VA21_ABA_ADICIONAIS = _CAB + "/tabpT\\12"
_ADIC = (VA21_ABA_ADICIONAIS + "/ssubSUBSCREEN_BODY:SAPMV45A:4312/sub8309:SAPMV45A:8309"
         "/subSUB_8309:SAPMV45A:9989/tblSAPMV45ATC_9989")
VA21_DATA_RECEBIMENTO = _ADIC + "/txtWA_ZTBSD_005-DT_RECEB_PEDIDO[6,0]"
VA21_HORA_RECEBIMENTO = _ADIC + "/txtWA_ZTBSD_005-HR_RECEB_PEDIDO[7,0]"
MAX_COLUNAS_PROCURA = 25
# Prefixo de cada campo como apareceu na gravação (txt = texto, ctxt = texto com ajuda F4)
CAMPOS_GRAVADOS = {COL_ITEM: "txt", COL_MATERIAL: "ctxt", COL_QUANTIDADE: "txt", COL_CENTRO: "ctxt"}
# Posição em que cada campo apareceu (script de 22/10 e programa de cotação: centro na coluna 7).
# Só um palpite para ganhar tempo: se não bater, as colunas são mapeadas pelo nome.
POSICOES_GRAVADAS = {COL_ITEM: (0,), COL_MATERIAL: (1,), COL_QUANTIDADE: (2,),
                     COL_CENTRO: (8, 7)}     # 8 = aba Venda do USUARIO1 (log de 26/10); 7 = programa de cotação
# Último trecho do ID de uma célula de tabela: prefixo do tipo + campo + [coluna,linha]
_ID_CELULA = re.compile(r"^(txt|ctxt|chk|cmb|lbl|btn|rad|pwd)?([A-Za-z0-9_\-]+)\[(\d+),(\d+)\]$")

INTERVALO_ESPERA = 0.03      # s entre consultas enquanto o SAP responde (era 0.1)

TRANSACOES_MENU = frozenset({"SESSION_MANAGER", "SMEN", "S000"})
MAX_JANELAS_PADRAO = 6


def _numero_documento(texto: str) -> str:
    """'Documento ZDC 20000263669 000 00 criado' -> '20000263669'."""
    achado = re.search(r"Documento\s+\S+\s+(\d+)", texto or "")
    return achado.group(1) if achado else ""


def _id_relativo(id_completo: str) -> str:
    """'/app/con[0]/ses[2]/wnd[0]/usr/...' -> 'wnd[0]/usr/...' (formato usado no findById)."""
    posicao = id_completo.find("wnd[")
    return id_completo[posicao:] if posicao >= 0 else id_completo


def _itens(colecao: Any) -> list[Any]:
    """Lista os itens de uma coleção COM (Count + índice) ou de um iterável."""
    try:
        return [colecao(i) for i in range(colecao.Count)]
    except Exception:  # noqa: BLE001
        pass
    try:
        return [colecao.Item(i) for i in range(colecao.Count)]
    except Exception:  # noqa: BLE001
        return list(colecao)


# ----------------------------------------------------------------------- acesso ao COM

def engine_padrao() -> Any:
    """Obtém o motor de scripting do SAP GUI. Cada falha vira uma mensagem clara."""
    try:
        import win32com.client  # importado aqui para os testes rodarem fora do Windows
    except ImportError as erro:
        raise SessaoIndisponivel(
            "pywin32 não está instalado. Rode: python -m pip install pywin32", etapa="conexao"
        ) from erro
    try:
        gui = win32com.client.GetObject("SAPGUI")
    except Exception as erro:
        raise SessaoIndisponivel(
            "SAP GUI não está aberto. Abra o SAP Logon e faça login.", etapa="conexao"
        ) from erro
    try:
        return gui.GetScriptingEngine
    except Exception as erro:
        raise SessaoIndisponivel(
            "SAP GUI Scripting indisponível (desabilitado no cliente ou no servidor).", etapa="conexao"
        ) from erro


# ----------------------------------------------------------------------- leitura de sessões

@dataclass(frozen=True)
class SessaoEncontrada:
    conexao: int
    sessao: int
    info: SessionInfo
    id: str = ""

    @property
    def rotulo(self) -> str:
        return f"conexão {self.conexao}, sessão {self.sessao}"


def _ler_info(sessao_com: Any) -> SessionInfo:
    info = sessao_com.Info
    return SessionInfo(
        sistema=str(info.SystemName).strip().upper(),
        mandante=str(info.Client).strip(),
        usuario=str(info.User).strip().upper(),
        idioma=str(info.Language).strip().upper(),
        transacao=str(info.Transaction).strip().upper(),
        ocupada=bool(sessao_com.Busy),
    )


def listar_sessoes(engine: Any) -> list[SessaoEncontrada]:
    """Lista todas as sessões abertas. Sessões ilegíveis são ignoradas e registradas."""
    encontradas: list[SessaoEncontrada] = []
    for c in range(engine.Children.Count):
        conexao = engine.Children(c)
        for s in range(conexao.Children.Count):
            try:
                sessao_com = conexao.Children(s)
                encontradas.append(SessaoEncontrada(c, s, _ler_info(sessao_com), str(getattr(sessao_com, "Id", ""))))
            except Exception as erro:  # noqa: BLE001 - COM pode falhar de formas variadas
                log.warning("Sessão %s/%s ignorada: não foi possível ler (%s)", c, s, erro)
    return encontradas


def escolher_base(sessoes: list[SessaoEncontrada], settings: Settings) -> SessaoEncontrada:
    """Escolhe a sessão a partir da qual a janela nova será aberta.

    A base só serve para "Criar novo modo": não é lida, clicada nem alterada,
    então pode estar em qualquer transação. Precisa estar logada e não ocupada.
    """
    alvo = f"{settings.sistema}/{settings.mandante}"
    if not sessoes:
        raise SessaoIndisponivel("Nenhuma sessão SAP aberta. Faça login no SAP.", etapa="sessao")

    do_sistema = [s for s in sessoes
                  if s.info.sistema == settings.sistema and s.info.mandante == settings.mandante]
    if not do_sistema:
        abertas = ", ".join(sorted({f"{s.info.sistema}/{s.info.mandante}" for s in sessoes}))
        raise SistemaIncorreto(f"Nenhuma sessão em {alvo}. Sessões abertas: {abertas}.", etapa="sessao")

    logadas = [s for s in do_sistema if s.info.usuario]
    if not logadas:
        raise SessaoIndisponivel(f"A sessão {alvo} está na tela de login. Faça login.", etapa="sessao")

    usuarios = {s.info.usuario for s in logadas}
    if len(usuarios) > 1:
        raise SessaoIndisponivel(
            f"Sessões de usuários diferentes em {alvo} ({', '.join(sorted(usuarios))}). "
            "Feche as que não são suas.",
            etapa="sessao",
        )

    livres = [s for s in logadas if not s.info.ocupada]
    if not livres:
        raise SessaoIndisponivel(
            f"Todas as janelas de {alvo} estão processando. Aguarde e tente de novo.", etapa="sessao"
        )
    # Prefere uma janela no menu principal; senão, qualquer uma livre.
    no_menu = [s for s in livres if s.info.transacao in TRANSACOES_MENU]
    return (no_menu or livres)[0]


# ----------------------------------------------------------------------- cliente

class SapClient:
    """Implementação real do SapGateway."""

    def __init__(
        self,
        settings: Settings,
        engine_factory: Callable[[], Any] = engine_padrao,
        max_janelas: int = MAX_JANELAS_PADRAO,
        timeout_s: float = 30.0,
        dormir: Callable[[float], None] = time.sleep,
    ):
        self._settings = settings
        self._engine_factory = engine_factory
        self._max_janelas = max_janelas
        self._timeout = timeout_s
        self._dormir = dormir
        self._conexao: Any = None
        self._s: Any = None          # a janela da automação
        self._colunas_cache: dict[str, dict[str, tuple[int, str]]] = {}
        # Reaproveitamento da janela da automação entre claims (economiza a abertura, ~2-3 s):
        self.reaproveitar: str | None = None    # Id da janela deixada pela execução anterior
        self.manter_janela = False              # no sucesso, deixar a janela no menu (minimizada)
        self.janela_mantida: str | None = None  # Id da janela mantida (para a próxima execução)
        self._campos_cache: dict[tuple[str, str], tuple[int, str]] = {}
        self._aba_atual = ""
        self.base: SessaoEncontrada | None = None
        self.todas: list[SessaoEncontrada] = []

    # ------------------------------------------------------------- diagnóstico (só leitura)

    def diagnostico(self) -> SessaoEncontrada:
        """Lista as sessões e escolhe a base, SEM abrir janela."""
        self.todas = listar_sessoes(self._engine_factory())
        self.base = escolher_base(self.todas, self._settings)
        return self.base

    # ------------------------------------------------------------- janela própria

    def sessao(self) -> SessionInfo:
        """Abre a janela da automação e devolve os dados dela."""
        engine = self._engine_factory()
        self.todas = listar_sessoes(engine)
        self.base = escolher_base(self.todas, self._settings)
        reaproveitada = self._janela_reaproveitavel()
        if reaproveitada is not None:
            self._conexao = engine.Children(reaproveitada.conexao)
            self._s = self._conexao.Children(reaproveitada.sessao)
            try:
                self._s.findById("wnd[0]").maximize()
            except Exception:  # noqa: BLE001 - só aparência
                pass
            log.info("Janela da automação reaproveitada: %s", reaproveitada.id)
            return reaproveitada.info
        conexao = engine.Children(self.base.conexao)

        abertas = conexao.Children.Count
        if abertas >= self._max_janelas:
            raise SessaoIndisponivel(
                f"Limite de {self._max_janelas} janelas do SAP atingido. Feche uma janela e tente de novo.",
                etapa="sessao",
            )
        ids_antes = {conexao.Children(i).Id for i in range(abertas)}
        conexao.Children(self.base.sessao).CreateSession()

        nova = self._aguardar(lambda: self._nova_janela(conexao, ids_antes), "abertura da janela")
        self._conexao, self._s = conexao, nova
        self._esperar_livre()

        info = _ler_info(nova)
        if (info.sistema, info.mandante) != (self._settings.sistema, self._settings.mandante):
            raise SistemaIncorreto(
                f"A janela nova está em {info.sistema}/{info.mandante}, esperado "
                f"{self._settings.sistema}/{self._settings.mandante}.",
                etapa="sessao",
            )
        log.info("Janela da automação aberta: %s (%s/%s, usuário %s)",
                 nova.Id, info.sistema, info.mandante, info.usuario)
        return info

    def _janela_reaproveitavel(self) -> SessaoEncontrada | None:
        """A janela deixada pela execução anterior, SÓ se ainda estiver parada no menu principal.

        Se o usuário mexeu nela (está em alguma transação), nunca é usada: abre-se outra.
        """
        if not self.reaproveitar or self.base is None:
            return None
        for s in self.todas:
            if s.id != self.reaproveitar:
                continue
            mesma_conta = ((s.info.sistema, s.info.mandante, s.info.usuario)
                           == (self._settings.sistema, self._settings.mandante, self.base.info.usuario))
            if (mesma_conta and not s.info.ocupada and s.info.transacao in TRANSACOES_MENU
                    and self._e_a_janela_mantida(s)):
                return s
            log.info("Janela anterior %s não reaproveitada (transação %s)", s.id, s.info.transacao)
        return None

    def _e_a_janela_mantida(self, s: SessaoEncontrada) -> bool:
        """A janela com aquele Id ainda é a NOSSA? O SAP reaproveita o número ses[n] quando o usuário
        fecha uma janela e abre outra. A nossa ficou minimizada e sem janela modal; uma do usuário
        aberta depois não está minimizada. Na dúvida (propriedade ilegível), não é."""
        try:
            sessao_com = self._engine_factory().Children(s.conexao).Children(s.sessao)
            if int(sessao_com.Children.Count) > 1:
                return False
            return bool(getattr(sessao_com.findById("wnd[0]"), "Iconic"))
        except Exception:  # noqa: BLE001
            return False

    def fechar_por_id(self, janela_id: str) -> bool:
        """Fecha a janela mantida da automação, se ela ainda estiver parada no menu (ao fechar o programa)."""
        engine = self._engine_factory()
        for s in listar_sessoes(engine):
            if (s.id == janela_id and s.info.transacao in TRANSACOES_MENU and not s.info.ocupada
                    and self._e_a_janela_mantida(s)):
                engine.Children(s.conexao).CloseSession(janela_id)
                log.info("Janela mantida da automação fechada: %s", janela_id)
                return True
        return False

    def fechar_janela(self) -> None:
        """Fecha a janela da automação (nunca as do usuário)."""
        if self._conexao is not None and self._s is not None:
            self._conexao.CloseSession(self._s.Id)
            log.info("Janela da automação fechada")
        self._s = None

    # ------------------------------------------------------------- cotação: linha nova (VA22)

    def abrir_cotacao(self, cotacao: str) -> None:
        self._exigir_janela()
        self._colunas_cache.clear()
        self._campos_cache.clear()
        self._aba_atual = ""
        self._el(OKCODE, "abrir VA22").text = "/nVA22"
        self._vkey(0)
        self._falhar_se_erro("abrir VA22")
        self._el(COTACAO_NUMERO, "número da cotação").text = cotacao
        self._vkey(0)
        msg = self.status()                        # ex.: cotação inexistente ou bloqueada por outro usuário
        if msg.e_erro:
            dica = (" Feche as janelas do SAP que estão com esta cotação aberta (inclusive janelas antigas "
                    "da automação, saindo SEM gravar) e tente de novo.") if "processamento" in msg.texto.lower() else ""
            raise ValorRejeitado(f"SAP: {msg.texto}.{dica}", etapa="abrir cotação")
        if self._s.Children.Count > 1:
            return                                 # o serviço lê a janela de aviso e decide
        self._abrir_aba(ABA_ITENS)
        self._el(TABELA_ITENS, "lista de itens da cotação")

    def preencher_linha(self, *, material: str, centro: str, quantidade: str) -> LinhaPreenchida:
        """Digita a linha no primeiro item livre, com o número seguinte ao maior existente.

        Como no programa de criação de cotação: item, material e quantidade na
        "Síntese de itens"; o centro na aba "Venda" (a Síntese não tem a coluna).
        Nada é gravado aqui. No fim, a linha é relida na aba Venda PELO NÚMERO do
        item (item, material e centro), para o serviço conferir.
        """
        self._exigir_janela()
        etapa = "linha nova da cotação"
        self._abrir_aba(ABA_ITENS)
        existentes, livre = self._mapear_itens(TABELA_ITENS)
        if livre is None:
            raise ElementoNaoEncontrado("Não há linha livre na lista de itens da cotação.", etapa=etapa)
        numeros = [int(n) for n in existentes]
        item = str((max(numeros) // 10 + 1) * 10 if numeros else 10)

        log.info("VA22 Síntese de itens: itens existentes %s; linha livre visível %s; item novo %s",
                 existentes, livre, item)
        self._escrever(TABELA_ITENS, COL_ITEM, livre, item, etapa)
        self._escrever(TABELA_ITENS, COL_MATERIAL, livre, material, etapa)
        self._escrever(TABELA_ITENS, COL_QUANTIDADE, livre, quantidade, etapa)
        # Ir direto para a aba Venda: a troca de aba já confirma a linha (economiza um Enter).
        self._abrir_aba(ABA_ITENS_2)
        status = self.status()
        if status.e_erro:
            raise ValorRejeitado(f"SAP: {status.texto}", etapa=etapa)
        if self._s.Children.Count > 1:
            return LinhaPreenchida(item, "", "", status)    # o serviço trata a janela antes de seguir
        aviso_linha = status if status.tipo == "W" else None
        if aviso_linha is not None or self._aba_selecionada() not in ("", ABA_ITENS_2):
            # Aviso na linha segurou a troca de aba: Enter para seguir e clicar na aba de novo.
            self._vkey(0)
            status = self.status()
            if status.e_erro:
                raise ValorRejeitado(f"SAP: {status.texto}", etapa=etapa)
            # Um aviso novo depois do Enter não pode sumir: dois avisos diferentes param aqui.
            aviso_linha = self._um_aviso(aviso_linha, status, etapa) if aviso_linha is not None else (
                status if status.tipo == "W" else None)
            self._el(ABA_ITENS_2, "aba Venda").select()
            self._esperar_livre()
            self._aba_atual = ABA_ITENS_2

        linha = self._linha_do_item(TABELA_ITENS_2, item, etapa)
        log.info("VA22 aba Venda: item %s na linha visível %s; colunas %s", item, linha,
                 {n: self._coluna(TABELA_ITENS_2, n) for n in (COL_ITEM, COL_CENTRO)})
        self._escrever(TABELA_ITENS_2, COL_CENTRO, linha, centro, etapa)
        # Aviso do cabeçalho na aba Venda (ex.: "Entrar Condições pagamento"): segundo Enter, a mesma
        # rotina da VA21. O serviço ainda decide se o aviso é aceito.
        status = self._enter_com_aviso("centro da linha nova")
        if self._s.Children.Count > 1:
            return LinhaPreenchida(item, "", "", status)

        # Releitura na aba Venda: a mesma linha, se o item ainda estiver nela; senão, procura de novo.
        if self._valor(TABELA_ITENS_2, COL_ITEM, linha).lstrip("0") != item:
            linha = self._linha_do_item(TABELA_ITENS_2, item, etapa)
        lidos = {nome: self._valor(TABELA_ITENS_2, nome, linha) for nome in (COL_ITEM, COL_CENTRO)}
        if self._coluna(TABELA_ITENS_2, COL_MATERIAL) is not None:
            lidos[COL_MATERIAL] = self._valor(TABELA_ITENS_2, COL_MATERIAL, linha)
        else:
            lidos[COL_MATERIAL] = self._ler_item(TABELA_ITENS, ABA_ITENS, item, etapa).get(COL_MATERIAL, "")
        return LinhaPreenchida(item=lidos[COL_ITEM], material=lidos[COL_MATERIAL],
                               centro=lidos[COL_CENTRO], status=self._um_aviso(aviso_linha, status, etapa))

    def gravar_cotacao(self, cotacao: str) -> StatusMessage:
        """Grava a cotação alterada (VA22). Ver _gravar_documento_vendas."""
        msg = self._gravar_documento_vendas("gravar cotação")
        log.info("Cotação %s gravada: %s", cotacao, msg.texto)
        return msg

    def _gravar_documento_vendas(self, etapa: str) -> StatusMessage:
        """Ctrl+S de cotação (VA21/VA22). Só confirma a janela se ela for "Gravar documento incompleto".

        Como no programa de cotação: se o SAP mostrar um aviso em vez da janela, um Enter
        segue com a gravação. A partir do clique em gravar, qualquer dúvida vira ResultadoIncerto.
        """
        self._exigir_janela()
        if self._s.Children.Count > 1:
            raise PopupInesperado("Há uma janela aberta antes de gravar a cotação.", etapa=etapa)
        botao = self._el(BOTAO_GRAVAR, etapa)
        titulo_tela = " ".join(str(getattr(self._s.findById("wnd[0]"), "Text", "") or "").split()).upper()
        self.avisos_gravacao = []          # tudo o que foi confirmado nesta gravação (vai para o histórico)
        try:
            botao.press()
            self._esperar_livre()
            for _ in range(MAX_JANELAS_AO_GRAVAR):
                if self._s.Children.Count > 1:
                    janela = self._s.findById(POPUP)
                    titulo = " ".join(str(janela.Text).split()).upper()
                    if titulo == TITULO_INCOMPLETO:
                        self._s.findById(GRAVAR_INCOMPLETO).press()
                        self._esperar_livre()
                        break
                    if titulo_tela and titulo == titulo_tela:
                        # Lista de avisos do SAP (ex.: 975 impostos, 8710 lista de preços), com o título
                        # da própria tela. O programa de cotação seguia com Enter ("confirmar salvar").
                        conteudo = self._texto_da_janela(janela) or "(conteúdo não legível)"
                        log.info("Lista de avisos ao gravar ('%s'): Enter para seguir", janela.Text)
                        self.avisos_gravacao.append(f"lista de avisos '{janela.Text}': {conteudo}")
                        janela.sendVKey(0)
                        self._esperar_livre()
                        continue
                    raise ResultadoIncerto(f"Janela inesperada ao gravar a cotação: '{janela.Text}'", etapa=etapa)
                aviso = self.status()
                if aviso.tipo == "W":
                    if not self._aviso_aceito(aviso.texto):
                        # Aviso desconhecido no meio da gravação: não confirma; quem decide é a pessoa.
                        raise ResultadoIncerto(f"Aviso não previsto ao gravar: '{aviso.texto}'", etapa=etapa)
                    self.avisos_gravacao.append(f"aviso aceito: {aviso.texto}")
                    self._vkey(0)                   # aviso da lista de aceitos: Enter segue com a gravação
                    continue
                break
            msg = self.status()
        except ResultadoIncerto:
            raise
        except Exception as erro:  # noqa: BLE001
            raise ResultadoIncerto(f"Sem resposta após gravar a cotação ({erro})", etapa=etapa) from erro
        if self._s.Children.Count > 1:
            raise ResultadoIncerto(f"Janela aberta depois de gravar a cotação (status: '{msg.texto}')", etapa=etapa)
        return msg

    # ------------------------------------------------------------- cotação nova (VA21)

    def iniciar_cotacao(self, *, tipo_documento: str, organizacao: str, canal: str, setor: str,
                        escritorio: str, equipe: str) -> None:
        """VA21 -> dados organizacionais -> Enter. Nada é gravado."""
        self._exigir_janela()
        self._colunas_cache.clear()
        self._campos_cache.clear()
        self._aba_atual = ""
        self._el(OKCODE, "abrir VA21").text = "/nVA21"
        self._vkey(0)
        self._falhar_se_erro("abrir VA21")
        for campo, valor, nome in ((VA21_TIPO, tipo_documento, "tipo de cotação"),
                                   (VA21_ORGANIZDCAO, organizacao, "organização de vendas"),
                                   (VA21_CANAL, canal, "canal"), (VA21_SETOR, setor, "setor"),
                                   (VA21_ESCRITORIO, escritorio, "escritório"), (VA21_EQUIPE, equipe, "equipe")):
            self._el(campo, nome).text = valor
        self._vkey(0)
        self._falhar_se_erro("dados iniciais da cotação")
        try:
            self._s.findById(VA21_EMISSOR)
        except Exception as erro:  # noqa: BLE001
            raise ElementoNaoEncontrado(
                "O campo do emissor não apareceu: o usuário pode não ter acesso a este tipo de cotação, "
                "ou a tela do SAP está diferente. Nada foi gravado.", etapa="dados iniciais da cotação") from erro

    def preencher_cliente(self, *, emissor: str, titulo: str, nome: str, cidade: str,
                          codigo_postal: str) -> Popup | None:
        """Emissor genérico + janela de endereço. Devolve a janela que sobrar aberta (o serviço decide)."""
        self._exigir_janela()
        self._el(VA21_EMISSOR, "emissor").text = emissor
        self._vkey(0)
        self._falhar_se_erro("emissor")
        if self._s.Children.Count < 2:
            raise ElementoNaoEncontrado("A janela de endereço do cliente não abriu.", etapa="endereço do cliente")
        self._el(END_TITULO, "título do endereço").key = titulo
        self._el(END_NOME, "nome do cliente").text = nome
        self._el(END_CIDADE, "cidade/projeto").text = cidade
        if codigo_postal:
            self._el(END_CEP, "código postal").text = codigo_postal
        self._el(END_OK, "confirmar endereço").press()
        self._esperar_livre()
        self._falhar_se_erro("endereço do cliente")
        return self.popup_aberto()

    def preencher_validade(self, *, validade: str, referencia: str) -> StatusMessage:
        """Validade (Síntese de itens) + referência do cliente. Devolve o 1º aviso, se houver."""
        self._exigir_janela()
        self._vkey(0)                                # "avançar para dados de validade"
        self._falhar_se_erro("validade da cotação")
        self._abrir_aba(ABA_ITENS)
        self._campo_por_sufixo(VA21_VALIDADE, "ctxtVBAK-BNDDT", "validade").text = validade
        self._vkey(0)
        primeiro = self.status()
        if primeiro.e_erro:
            raise ValorRejeitado(f"SAP: {primeiro.texto}", etapa="validade da cotação")
        self._vkey(0)                                # o programa de cotação confirma duas vezes
        segundo = self.status()
        if segundo.e_erro:
            raise ValorRejeitado(f"SAP: {segundo.texto}", etapa="validade da cotação")
        if primeiro.tipo == "W" and segundo.tipo == "W" and segundo.texto != primeiro.texto:
            raise ValorRejeitado(f"Dois avisos seguidos na validade: '{primeiro.texto}' e '{segundo.texto}'. "
                                 "Nada foi gravado", etapa="validade da cotação")
        self._el(VA21_REFERENCIA, "referência cliente/projeto").text = referencia
        return primeiro if primeiro.tipo == "W" else segundo

    def preencher_linhas_novas(self, linhas: list[tuple[str, str, str]]) -> list[LinhaPreenchida]:
        """Linhas (material, centro, quantidade) da cotação nova; o SAP numera (10, 20...).

        Material e quantidade na Síntese de itens; centro na aba Venda (como na VA22).
        Nada é gravado. Cada linha é relida (item, material, centro) para o serviço conferir.
        """
        self._exigir_janela()
        etapa = "linhas da cotação"
        self._abrir_aba(ABA_ITENS)
        for r, (material, _, quantidade) in enumerate(linhas):
            self._escrever(TABELA_ITENS, COL_MATERIAL, r, material, etapa)
            self._escrever(TABELA_ITENS, COL_QUANTIDADE, r, quantidade, etapa)
        self._vkey(0)                                # "confirmar item"
        status = self.status()
        if status.e_erro:
            raise ValorRejeitado(f"SAP: {status.texto}", etapa=etapa)
        if self._s.Children.Count > 1:
            return [LinhaPreenchida("", "", "", status)]
        itens = [self._valor(TABELA_ITENS, COL_ITEM, r) for r in range(len(linhas))]
        if not all(i.isdigit() for i in itens):
            raise ValorRejeitado(f"O SAP não numerou as linhas como esperado: {itens}. Nada foi gravado.",
                                 etapa=etapa)
        aviso = status if status.tipo == "W" else None

        self._abrir_aba(ABA_ITENS_2)
        for item, (_, centro, _) in zip(itens, linhas):
            self._escrever(TABELA_ITENS_2, COL_CENTRO, self._linha_do_item(TABELA_ITENS_2, item, etapa), centro, etapa)
        status = self._enter_com_aviso(etapa)
        if self._s.Children.Count > 1:
            return [LinhaPreenchida("", "", "", status)]
        aviso = self._um_aviso(aviso, status, etapa)

        lidas = []
        tem_material = self._coluna(TABELA_ITENS_2, COL_MATERIAL) is not None
        for item in itens:
            r = self._linha_do_item(TABELA_ITENS_2, item, etapa)
            material = self._valor(TABELA_ITENS_2, COL_MATERIAL, r) if tem_material else ""
            lidas.append(LinhaPreenchida(self._valor(TABELA_ITENS_2, COL_ITEM, r), material,
                                         self._valor(TABELA_ITENS_2, COL_CENTRO, r), aviso))
        if not tem_material:
            for i, item in enumerate(itens):
                material = self._ler_item(TABELA_ITENS, ABA_ITENS, item, etapa).get(COL_MATERIAL, "")
                lidas[i] = LinhaPreenchida(lidas[i].item, material, lidas[i].centro, lidas[i].status)
        return lidas

    def preencher_cabecalho(self, *, utilizacao: str, data: str, hora: str) -> StatusMessage:
        """Cabeçalho: tipo de utilização e data/hora de recebimento do pedido. Nada é gravado."""
        self._exigir_janela()
        self._el(VA21_BOTAO_CABECALHO, "abrir cabeçalho").press()
        self._esperar_livre()
        self._falhar_se_erro("cabeçalho da cotação")
        self._el(VA21_UTILIZDCAO, "tipo de utilização").key = utilizacao
        self._el(VA21_ABA_ADICIONAIS, "aba dados adicionais").select()
        self._esperar_livre()
        self._falhar_se_erro("dados adicionais")
        self._el(VA21_DATA_RECEBIMENTO, "data de recebimento do pedido").text = data
        self._el(VA21_HORA_RECEBIMENTO, "hora de recebimento do pedido").text = hora
        return self.status()

    def gravar_cotacao_nova(self) -> StatusMessage:
        msg = self._gravar_documento_vendas("gravar cotação nova")
        log.info("Cotação nova gravada: %s", msg.texto)
        return msg

    def _enter_com_aviso(self, etapa: str) -> StatusMessage:
        """Enter; se vier aviso (ex.: condições de pagamento), segundo Enter. Devolve o aviso."""
        self._vkey(0)
        status = self.status()
        if status.e_erro:
            raise ValorRejeitado(f"SAP: {status.texto}", etapa=etapa)
        if status.tipo == "W" and self._s.Children.Count < 2:
            log.info("Aviso '%s'; segundo Enter", status.texto)
            self._vkey(0)
            segundo = self.status()
            if segundo.e_erro:
                raise ValorRejeitado(f"SAP: {segundo.texto}", etapa=etapa)
            if segundo.tipo == "W" and segundo.texto != status.texto:
                raise ValorRejeitado(f"Dois avisos seguidos: '{status.texto}' e '{segundo.texto}'. Nada foi gravado.",
                                     etapa=etapa)
        return status

    @staticmethod
    def _um_aviso(primeiro: StatusMessage | None, segundo: StatusMessage, etapa: str) -> StatusMessage:
        """O serviço confere UM status. Dois avisos W diferentes no mesmo passo: o segundo não pode sumir
        sem passar pela lista de avisos aceitos, então para aqui (nada foi gravado ainda)."""
        if primeiro is None or primeiro.tipo != "W":
            return segundo
        if segundo.tipo == "W" and " ".join(segundo.texto.split()) != " ".join(primeiro.texto.split()):
            raise ValorRejeitado(f"Dois avisos seguidos: '{primeiro.texto}' e '{segundo.texto}'. Nada foi gravado.",
                                 etapa=etapa)
        return primeiro

    def _aviso_aceito(self, texto: str) -> bool:
        """Mesmo critério do serviço: [avisos_aceitos] do settings.ini (* = qualquer trecho)."""
        import fnmatch
        texto = " ".join((texto or "").split())
        return any(fnmatch.fnmatchcase(texto, padrao) for padrao in self._settings.avisos_aceitos)

    def _campo_por_sufixo(self, id_tecnico: str, sufixo: str, etapa: str) -> Any:
        """O campo pelo ID gravado; se a tela mudou, procura pelo final do ID (como o programa de cotação)."""
        try:
            return self._s.findById(id_tecnico)
        except Exception:  # noqa: BLE001
            pass
        achado = self._procurar_sufixo(self._s.findById("wnd[0]"), sufixo)
        if achado is None:
            raise ElementoNaoEncontrado(f"Campo {sufixo} não encontrado na tela.", etapa=etapa)
        return achado

    def _procurar_sufixo(self, controle: Any, sufixo: str) -> Any:
        if str(getattr(controle, "Id", "")).endswith(sufixo):
            return controle
        try:
            filhos = _itens(controle.Children)
        except Exception:  # noqa: BLE001
            return None
        for filho in filhos:
            achado = self._procurar_sufixo(filho, sufixo)
            if achado is not None:
                return achado
        return None

    # ------------------------------------------------------------- tabela de itens da cotação

    def _abrir_aba(self, aba: str) -> None:
        if self._aba_atual == aba:
            return
        if not self._aba_atual and self._aba_selecionada() == aba:    # a VA22 já abriu nesta aba
            self._aba_atual = aba
            return
        self._el(aba, "aba da lista de itens").select()
        self._esperar_livre()
        self._aba_atual = aba

    def _aba_selecionada(self) -> str:
        """Id da aba ativa da VA22 ("" se não der para saber: nesse caso a aba é clicada)."""
        try:
            return _id_relativo(str(self._s.findById(_VISAO).SelectedTab.Id))
        except Exception:  # noqa: BLE001
            return ""

    def _mapa_colunas(self, tabela_id: str) -> dict[str, tuple[int, str]]:
        """Colunas da tabela PELO NOME do campo: nome -> (índice, prefixo do ID).

        A posição muda com o layout do usuário, por isso nunca é fixa. Lê os IDs das
        células visíveis (ex.: .../txtVBAP-POSNR[0,3]); se a tabela não expuser as
        células, usa GetCell(0, c).Name (prefixo vazio).
        """
        if tabela_id in self._colunas_cache:
            return self._colunas_cache[tabela_id]
        tabela = self._el(tabela_id, "lista de itens")
        mapa: dict[str, tuple[int, str]] = {}
        try:
            for celula in _itens(tabela.Children):
                ultimo = str(getattr(celula, "Id", "") or "").rsplit("/", 1)[-1]
                achado = _ID_CELULA.match(ultimo)
                if achado:
                    prefixo, nome, coluna = achado.group(1), achado.group(2).upper(), int(achado.group(3))
                    mapa.setdefault(nome, (coluna, prefixo + achado.group(2)))
        except Exception as erro:  # noqa: BLE001
            log.info("Células da tabela %s não enumeráveis (%s); usando GetCell", tabela_id, erro)
        if mapa:
            self._colunas_cache[tabela_id] = mapa
            return mapa
        try:
            total = int(tabela.Columns.Count)
        except Exception:  # noqa: BLE001
            total = 0
        for c in range(total):
            try:
                mapa.setdefault(str(tabela.GetCell(0, c).Name).strip().upper(), (c, ""))
            except Exception:  # noqa: BLE001
                continue
        if not mapa:
            # Último recurso: os IDs exatos da gravação (prefixo + campo), procurando a coluna.
            for nome, prefixo in CAMPOS_GRAVADOS.items():
                for c in range(MAX_COLUNAS_PROCURA):
                    try:
                        self._s.findById(f"{tabela_id}/{prefixo}{nome}[{c},0]")
                    except Exception:  # noqa: BLE001
                        continue
                    mapa[nome] = (c, prefixo + nome)
                    break
        if mapa:
            self._colunas_cache[tabela_id] = mapa
        return mapa

    def _campo(self, tabela_id: str, nome: str) -> tuple[int, str] | None:
        """Coluna de um campo: primeiro a posição da gravação (1 consulta), senão o mapa completo."""
        chave = (tabela_id, nome)
        if chave in self._campos_cache:
            return self._campos_cache[chave]
        achado = None
        prefixo = CAMPOS_GRAVADOS.get(nome, "")
        if prefixo and tabela_id not in self._colunas_cache:
            for posicao in POSICOES_GRAVADAS.get(nome, ()):
                try:
                    self._s.findById(f"{tabela_id}/{prefixo}{nome}[{posicao},0]")
                except Exception:  # noqa: BLE001 - layout diferente
                    continue
                achado = (posicao, prefixo + nome)
                break
        if achado is None:
            achado = self._mapa_colunas(tabela_id).get(nome)
        if achado is not None:
            self._campos_cache[chave] = achado
        return achado

    def _coluna(self, tabela_id: str, nome: str) -> int | None:
        achado = self._campo(tabela_id, nome)
        return achado[0] if achado else None

    def _valor(self, tabela_id: str, nome: str, linha: int) -> str:
        return str(self._celula(tabela_id, nome, linha, "lista de itens").Text or "").strip()

    def _escrever(self, tabela_id: str, nome: str, linha: int, valor: str, etapa: str) -> None:
        """Escreve numa célula só se ela aceitar edição; senão, erro claro (nada gravado)."""
        celula = self._celula(tabela_id, nome, linha, etapa)
        atual = str(getattr(celula, "Text", "") or "").strip()
        if not bool(getattr(celula, "Changeable", True)):
            raise ValorRejeitado(
                f"A célula {nome} da linha visível {linha} não aceita edição (valor atual: '{atual or 'vazio'}'). "
                "Nada foi gravado.", etapa=etapa)
        try:
            celula.text = valor
        except Exception as erro:  # noqa: BLE001
            raise ValorRejeitado(
                f"O SAP recusou '{valor}' em {nome}, linha visível {linha} (valor atual: '{atual or 'vazio'}'; "
                f"{erro}). Nada foi gravado.", etapa=etapa) from erro

    def _celula(self, tabela_id: str, nome: str, linha: int, etapa: str) -> Any:
        achado = self._campo(tabela_id, nome)
        if achado is None:
            vistas = ", ".join(sorted(self._mapa_colunas(tabela_id))) or "nenhuma"
            raise ElementoNaoEncontrado(f"Coluna {nome} não encontrada na lista de itens. Colunas vistas: {vistas}.",
                                        etapa=etapa)
        coluna, campo = achado
        try:
            if campo:
                return self._s.findById(f"{tabela_id}/{campo}[{coluna},{linha}]")
            return self._el(tabela_id, etapa).GetCell(linha, coluna)
        except Exception as erro:  # noqa: BLE001
            raise ElementoNaoEncontrado(f"Célula {nome} da linha {linha} não encontrada ({erro})",
                                        etapa=etapa) from erro

    def _paginas(self, tabela_id: str):
        """Percorre a tabela página a página (rolando), devolvendo (tabela, linha visível, item)."""
        tabela = self._el(tabela_id, "lista de itens")
        barra = tabela.VerticalScrollbar
        if int(barra.Position) != 0:
            barra.Position = 0
            self._esperar_livre()
            tabela = self._el(tabela_id, "lista de itens")
        for _ in range(MAX_PAGINAS_TABELA):
            self._celula(tabela_id, COL_ITEM, 0, "lista de itens")    # coluna do item tem que existir
            visiveis = int(tabela.VisibleRowCount)
            for r in range(visiveis):
                try:
                    valor = str(self._celula(tabela_id, COL_ITEM, r, "lista de itens").Text or "").strip()
                except ElementoNaoEncontrado:   # linha além do fim da tabela
                    return
                yield tabela, r, valor
            barra = tabela.VerticalScrollbar
            posicao, maximo = int(barra.Position), int(barra.Maximum)
            if posicao >= maximo or visiveis < 1:
                return
            # Repete a última linha da página (sobreposição); com 1 linha visível, anda de 1 em 1.
            barra.Position = min(maximo, posicao + max(1, visiveis - 1))
            self._esperar_livre()
            tabela = self._el(tabela_id, "lista de itens")

    def _mapear_itens(self, tabela_id: str) -> tuple[list[str], int | None]:
        """Itens existentes e a primeira linha visível livre (na página em que a busca parou)."""
        existentes: list[str] = []
        for _, r, valor in self._paginas(tabela_id):
            if not valor:
                return existentes, r
            if valor.isdigit() and valor not in existentes:
                existentes.append(valor)
        return existentes, None

    def _linha_do_item(self, tabela_id: str, item: str, etapa: str) -> int:
        alvo = item.lstrip("0")
        for _, r, valor in self._paginas(tabela_id):
            if valor.lstrip("0") == alvo:
                return r
            if not valor:
                break
        raise ValorRejeitado(f"O item {item} não aparece na lista de itens da cotação.", etapa=etapa)

    def _ler_item(self, tabela_id: str, aba: str, item: str, etapa: str) -> dict[str, str]:
        self._abrir_aba(aba)
        linha = self._linha_do_item(tabela_id, item, etapa)
        return {nome: self._valor(tabela_id, nome, linha)
                for nome in (COL_ITEM, COL_MATERIAL) if self._coluna(tabela_id, nome) is not None}

    # ------------------------------------------------------------- Fase 1: nota

    def abrir_criacao(self, tipo_nota: str) -> None:
        self._exigir_janela()
        self._el(OKCODE, "abrir CLM1").text = "/nCLM1"
        self._vkey(0)
        self._falhar_se_erro("abrir CLM1")

        combo = self._el(TIPO_NOTA, "tipo de nota")
        combo.key = tipo_nota
        self._vkey(0)
        self._falhar_se_erro("tipo de nota")
        self._el(DESCRICAO, "tela principal da nota")  # confirma que a tela abriu

    def preencher_nota(self, *, descricao: str, texto_livre: str, causa_grupo: str,
                       causa_codigo: str, prioridade: str, ordem: str, item: str) -> None:
        self._exigir_janela()
        # Texto livre escrito UMA vez (o SAP acrescenta data/hora/usuário sozinho).
        self._el(TEXTO_LIVRE, "texto livre").text = texto_livre.replace("\n", "\r")
        self._el(DESCRICAO, "descrição").text = descricao
        self._el(CAUSA_GRUPO, "causa - grupo").text = causa_grupo
        self._el(CAUSA_CODIGO, "causa - código").text = causa_codigo
        self._el(PRIORIDADE, "prioridade").key = prioridade
        self._el(ORDEM, "ordem do cliente").text = ordem
        self._el(ITEM, "item da ordem").text = item

    def enter(self) -> StatusMessage:
        self._exigir_janela()
        self._vkey(0)
        return self.status()

    def status(self) -> StatusMessage:
        barra = self._el(STATUS, "barra de status")
        return StatusMessage(
            tipo=str(getattr(barra, "MessageType", "") or "").strip().upper(),
            texto=str(getattr(barra, "Text", "") or "").strip(),
            id_mensagem=str(getattr(barra, "MessageId", "") or "").strip(),
            numero_mensagem=str(getattr(barra, "MessageNumber", "") or "").strip(),
        )

    def popup_aberto(self) -> Popup | None:
        self._exigir_janela()
        if self._s.Children.Count < 2:
            return None
        janela = self._s.findById(POPUP)
        texto = str(getattr(janela, "PopupDialogText", "") or "").strip()
        if not texto:
            texto = self._texto_da_janela(janela)
        return Popup(titulo=str(janela.Text).strip(), texto=texto)

    def confirmar_popup(self) -> None:
        self._el(POPUP_OK, "OK da janela de aviso").press()
        self._esperar_livre()

    # ------------------------------------------------------------- Fase 3: atividades

    def selecionar_atividades(self, atividades: list[AtividadeSelecionada], raiz: str) -> list[dict[str, str]]:
        """Seleciona as atividades PELO TEXTO dentro da pasta e confere cada linha.

        Os códigos dos itens da árvore (ex.: 000000000660) são sequenciais e mudam
        quando a árvore muda: nunca são usados. Só as pastas têm código estável.

        Garantias, todas ANTES de Transferir:
        - o item é localizado pelo texto exato dentro da pasta (precisa ser único);
        - cada duplo clique cria exatamente uma linha nova;
        - a linha nova tem a descrição e o sub grupo esperados;
        - no fim, toda a grade (descrição, sub grupo e responsável) bate com a rota.
        Qualquer divergência para tudo sem transferir.
        """
        self._exigir_janela()
        if not atividades:      # rota sem atividades no settings.ini: nunca transferir uma grade vazia
            raise ValorRejeitado("A rota não tem atividades configuradas.", etapa="grade de atividades")
        self._el(ABA_SINTESE, "aba Síntese da nota").select()
        self._esperar_livre()
        barra = self._el(BARRA_ATIVIDADES, "barra de atividades")
        barra.selectItem(*LINK_SELECAO_MULTIPLA)
        barra.clickLink(*LINK_SELECAO_MULTIPLA)
        self._esperar_livre()

        arvore = self._el(ARVORE, "árvore de atividades")
        # A grade só é criada pelo SAP depois da primeira atividade: ausente = vazia.
        iniciais = self._linhas_na_grade()
        if iniciais != 0:
            raise ValorRejeitado(
                f"A grade de atividades já tinha {iniciais} linha(s). Esperado: vazia.",
                etapa="grade de atividades",
            )
        self._expandir(arvore, raiz)

        for posicao, atividade in enumerate(atividades):
            etapa = f"atividade {posicao + 1} ({atividade.descricao} · {atividade.subgrupo or atividade.pasta})"
            self._expandir(arvore, atividade.pasta)
            chave = self._achar_item(arvore, atividade.pasta, atividade.descricao, etapa)
            try:
                arvore.selectedNode = chave
                arvore.doubleClickNode(chave)
            except Exception as erro:  # noqa: BLE001
                raise ElementoNaoEncontrado(f"Não foi possível clicar em '{atividade.descricao}' ({erro})",
                                            etapa=etapa) from erro
            self._esperar_livre()
            esperado = posicao + 1
            try:
                self._aguardar(lambda: True if self._linhas_na_grade() >= esperado else None,
                               f"linha nova na grade ({etapa})")
            except SessaoIndisponivel:
                pass  # a conferência abaixo explica o problema
            linhas_agora = self._linhas_na_grade()
            if linhas_agora != esperado:
                raise ValorRejeitado(
                    f"Após clicar em '{atividade.descricao}', a grade tem {linhas_agora} linha(s); "
                    f"esperado {esperado}.",
                    etapa=etapa,
                )
            grade = self._el(GRADE, "grade de atividades")
            self._conferir_linha(grade, posicao, atividade, etapa, com_responsavel=False)
            if atividade.responsavel:
                grade.modifyCell(posicao, COLUNA_RESPONSAVEL, atividade.responsavel)

        grade.setCurrentCell(-1, "")   # confirma a edição da última célula
        self._esperar_livre()
        grade = self._el(GRADE, "grade de atividades")
        if int(grade.RowCount) != len(atividades):
            raise ValorRejeitado(f"A grade tem {grade.RowCount} linha(s); esperado {len(atividades)}.",
                                 etapa="conferência final das atividades")
        linhas = self._ler_grade(grade)          # uma leitura só, usada na conferência e no registro
        for posicao, atividade in enumerate(atividades):
            self._conferir_valores(linhas[posicao], posicao, atividade, "conferência final das atividades",
                                   com_responsavel=True)

        grade.selectAll()
        self._el(TRANSFERIR, "Transferir atividades").press()
        self._esperar_livre()
        if self._s.Children.Count > 1:
            raise ValorRejeitado(
                "A janela de atividades continuou aberta depois de Transferir.",
                etapa="Transferir atividades",
            )
        return linhas

    # ------------------------------------------------------------- árvore e grade

    def _achar_item(self, arvore: Any, pasta: str, texto: str, etapa: str) -> str:
        """Chave do item da pasta cujo texto é exatamente `texto` (único)."""
        alvo = " ".join(texto.split()).upper()
        filhos = self._filhos(arvore, pasta)
        textos = {chave: " ".join(self._texto_no(arvore, chave).split()) for chave in filhos}
        achados = [chave for chave, txt in textos.items() if txt.upper() == alvo]
        if len(achados) == 1:
            return achados[0]
        disponiveis = ", ".join(sorted(t for t in textos.values() if t)) or "nenhum item"
        if not achados:
            raise ElementoNaoEncontrado(
                f"'{texto}' não existe na pasta {pasta}. Itens da pasta: {disponiveis}.", etapa=etapa)
        raise ValorRejeitado(f"'{texto}' aparece {len(achados)} vezes na pasta {pasta}.", etapa=etapa)

    @staticmethod
    def _filhos(arvore: Any, pasta: str) -> list[str]:
        try:
            colecao = arvore.GetSubNodesCol(pasta)
            if colecao is not None:
                return [str(k) for k in _itens(colecao)]
        except Exception:  # noqa: BLE001 - nem toda árvore expõe GetSubNodesCol
            pass
        try:
            return [str(k) for k in _itens(arvore.GetAllNodeKeys()) if str(arvore.GetParent(k)) == pasta]
        except Exception as erro:  # noqa: BLE001
            raise ElementoNaoEncontrado(f"Não foi possível ler os itens da pasta {pasta} ({erro})",
                                        etapa="árvore de atividades") from erro

    @staticmethod
    def _texto_no(arvore: Any, chave: str) -> str:
        for leitura in (lambda: arvore.GetNodeTextByKey(chave),
                        lambda: arvore.GetItemText(chave, arvore.GetColumnNames()(0))):
            try:
                texto = str(leitura() or "").strip()
                if texto:
                    return texto
            except Exception:  # noqa: BLE001
                continue
        return ""

    @staticmethod
    def _conferir_linha(grade: Any, linha: int, atividade: AtividadeSelecionada, etapa: str,
                        com_responsavel: bool) -> None:
        def valor(coluna: str) -> str:
            try:
                return " ".join(str(grade.GetCellValue(linha, coluna) or "").split()).upper()
            except Exception:  # noqa: BLE001
                return ""
        esperados = [(COLUNA_DESCRICAO, atividade.descricao)]
        if atividade.subgrupo:
            esperados.append((COLUNA_SUBGRUPO, atividade.subgrupo))
        if com_responsavel and atividade.responsavel:
            esperados.append((COLUNA_RESPONSAVEL, atividade.responsavel))
        for coluna, esperado in esperados:
            atual = valor(coluna)
            if atual != " ".join(esperado.split()).upper():
                raise ValorRejeitado(
                    f"Linha {linha + 1} da grade: {coluna} = '{atual or 'vazio'}', esperado '{esperado}'. "
                    "Nada foi transferido.",
                    etapa=etapa,
                )

    # ------------------------------------------------------------- Fase 2: documento ZDC

    def criar_documento(self, *, tipo: str, descricao: str, laboratorio: str,
                        arquivo: Path, aplicacao: str) -> str:
        """Cria o documento, anexa e arquiva o original e GRAVA o documento.

        Tudo antes do Ctrl+S é desfazível (nada gravado). A partir do Ctrl+S,
        qualquer falha vira ResultadoIncerto: o documento pode já existir.
        """
        self._exigir_janela()
        self._el(ABA_COMPLEMENTARES, "aba Dados complementares").select()
        self._esperar_livre()
        self._el(TODAS_VERSOES, "todas versões").select()
        self._el(CRIAR_DOCUMENTO, "criar documento").press()
        self._esperar_livre()
        self._escolher_na_lista(tipo, "tipo de documento")
        self._vkey(0)
        self._falhar_se_erro("1ª tela do documento")

        self._el(DOC_DESCRICAO, "descrição do documento").text = descricao
        self._el(DOC_LABORATORIO, "Lab./escr.").text = laboratorio
        self._vkey(0)
        self._falhar_se_erro("dados do documento")

        self._el(DOC_PROCURAR_ARQUIVO, "procurar arquivo").press()
        self._esperar_livre()
        self._el(ARQ_PASTA, "pasta do arquivo").text = str(arquivo.parent) + "\\"
        self._el(ARQ_NOME, "nome do arquivo").text = arquivo.name
        self._el(ARQ_OK, "confirmar arquivo").press()
        self._esperar_livre()
        if self._s.Children.Count > 1:          # o SAP pergunta a aplicação (ex.: PDF, ZIP)
            if not aplicacao:
                raise ValorRejeitado(
                    f"O SAP pediu a aplicação para '{arquivo.suffix or arquivo.name}', mas esse tipo não está em "
                    "[aplicacao_por_extensao] do settings.ini. Nada foi gravado.",
                    etapa="aplicação do original",
                )
            self._escolher_na_lista(aplicacao, "aplicação do original")
        self._falhar_se_erro("anexar arquivo")

        originais = self._el(ORIGINAIS, "lista de originais")
        try:
            originais.selectNode(NO_PRIMEIRO_ORIGINAL)
            originais.nodeContextMenu(NO_PRIMEIRO_ORIGINAL)
            originais.selectContextMenuItem(MENU_ARQUIVAR)
        except Exception as erro:  # noqa: BLE001
            raise ElementoNaoEncontrado(f"Não foi possível arquivar o original ({erro})",
                                        etapa="arquivar original") from erro
        self._esperar_livre()
        self._falhar_se_erro("arquivar original")
        if self._s.Children.Count > 1:
            raise PopupInesperado("Janela inesperada após arquivar o original.", etapa="arquivar original")

        # ---- a partir daqui o documento pode ter sido gravado
        try:
            self._vkey(TECLA_GRAVAR)
            msg = self.status()
        except Exception as erro:  # noqa: BLE001
            raise ResultadoIncerto(f"Sem resposta após gravar o documento ({erro})",
                                   etapa="gravar documento") from erro
        numero = _numero_documento(msg.texto)
        if msg.tipo != "S" or not numero:
            raise ResultadoIncerto(f"Gravação do documento sem confirmação: '{msg.texto}'",
                                   etapa="gravar documento")
        log.info("Documento %s %s criado", tipo, numero)
        return numero

    # ------------------------------------------------------------- pôr em processamento

    def por_em_processamento(self) -> StatusMessage:
        """Clica na bandeira verde, só se o botão for mesmo o de processamento."""
        self._exigir_janela()
        if self._s.Children.Count > 1:
            raise PopupInesperado("Há uma janela aberta antes de pôr em processamento.",
                                  etapa="pôr em processamento")
        botao = self._el(BANDEIRA_PROCESSAMENTO, "pôr em processamento")
        dica = " ".join(str(getattr(botao, campo, "") or "") for campo in ("Tooltip", "Text", "IconName"))
        if DICA_PROCESSAMENTO not in dica.upper():
            raise ElementoNaoEncontrado(
                f"O botão {BANDEIRA_PROCESSAMENTO} não parece ser 'Pôr em processamento' (dica: '{dica.strip()}'). "
                "Nada foi clicado.",
                etapa="pôr em processamento",
            )
        if not bool(getattr(botao, "Changeable", True)):
            raise ValorRejeitado("A bandeira 'Pôr em processamento' está desabilitada.", etapa="pôr em processamento")
        botao.press()
        self._esperar_livre()
        msg = self.status()
        if msg.e_erro:
            raise ValorRejeitado(f"SAP: {msg.texto}", etapa="pôr em processamento")
        return msg

    # ------------------------------------------------------------- gravação do claim

    def gravar_nota(self) -> StatusMessage:
        """Envia o Ctrl+S do claim. Qualquer falha a partir daqui é ResultadoIncerto."""
        self._exigir_janela()
        try:
            self._vkey(TECLA_GRAVAR)
            return self.status()
        except Exception as erro:  # noqa: BLE001
            raise ResultadoIncerto(f"Sem resposta após gravar o claim ({erro})", etapa="gravar claim") from erro

    def nota_existe(self, numero: str) -> bool:
        raise NotImplementedError("Consulta na CLM3: aguardando a gravação de script com o ID do campo.")

    def encerrar(self) -> None:
        """Fim com sucesso: fecha a janela ou, se pedido, deixa-a no menu, minimizada, para o próximo claim."""
        if not self.manter_janela or self._s is None:
            self.fechar_janela()
            return
        try:
            self._el(OKCODE, "voltar ao menu").text = "/n"
            self._vkey(0)
            if self._s.Children.Count > 1 or _ler_info(self._s).transacao not in TRANSACOES_MENU:
                raise RuntimeError("a janela não voltou ao menu")
            try:
                self._s.findById("wnd[0]").iconify()
            except Exception:  # noqa: BLE001 - só aparência
                pass
            self.janela_mantida = str(self._s.Id)
            log.info("Janela da automação mantida no menu para o próximo claim: %s", self.janela_mantida)
        except Exception as erro:  # noqa: BLE001
            log.info("Janela não mantida (%s); fechando", erro)
            self.janela_mantida = None
            self.fechar_janela()

    def sair_sem_gravar(self) -> None:
        raise NotImplementedError("Não usado: a janela da automação é deixada aberta para conferência.")

    # ------------------------------------------------------------- interno

    def _exigir_janela(self) -> None:
        if self._s is None:
            raise SessaoIndisponivel("Janela da automação não foi aberta.", etapa="sessao")

    def _el(self, id_tecnico: str, etapa: str) -> Any:
        try:
            return self._s.findById(id_tecnico)
        except Exception as erro:  # noqa: BLE001 - com_error do SAP
            raise ElementoNaoEncontrado(f"Elemento não encontrado: {id_tecnico} ({erro})", etapa=etapa) from erro

    def _vkey(self, tecla: int) -> None:
        self._s.findById("wnd[0]").sendVKey(tecla)
        self._esperar_livre()

    def _falhar_se_erro(self, etapa: str) -> None:
        msg = self.status()
        if msg.e_erro:
            raise ValorRejeitado(f"SAP: {msg.texto}", etapa=etapa)

    def _esperar_livre(self) -> None:
        self._aguardar(lambda: None if self._s.Busy else True, "resposta do SAP")

    def _aguardar(self, condicao: Callable[[], Any], o_que: str) -> Any:
        passos = max(1, int(self._timeout / INTERVALO_ESPERA))
        for _ in range(passos):
            resultado = condicao()
            if resultado is not None:
                return resultado
            self._dormir(INTERVALO_ESPERA)
        raise SessaoIndisponivel(f"Tempo esgotado aguardando {o_que} ({self._timeout:.0f}s).", etapa=o_que)

    def _escolher_na_lista(self, texto: str, etapa: str) -> None:
        """Escolhe numa lista de popup PELO TEXTO (nunca pela posição na tela)."""
        area = self._el(LISTA_POPUP, etapa)
        alvo = texto.strip().upper()
        for i in range(area.Children.Count):
            item = area.Children(i)
            valor = str(getattr(item, "Text", "") or "").strip().upper()
            if valor == alvo or valor.startswith(alvo + " "):
                item.setFocus()
                self._s.findById(POPUP).sendVKey(TECLA_ESCOLHER)
                self._esperar_livre()
                return
        raise ValorRejeitado(f"'{texto}' não está na lista do SAP.", etapa=etapa)

    def _linhas_na_grade(self) -> int:
        """Quantidade de linhas da grade de atividades; 0 se ela ainda não existe."""
        try:
            return int(self._s.findById(GRADE).RowCount)
        except Exception:  # noqa: BLE001 - controle ainda não criado pelo SAP
            return 0

    def _expandir(self, arvore: Any, chave: str) -> None:
        try:
            arvore.expandNode(chave)
        except Exception as erro:  # noqa: BLE001
            raise ElementoNaoEncontrado(f"Pasta {chave} não encontrada na árvore ({erro})",
                                        etapa="árvore de atividades") from erro
        self._esperar_livre()

    @staticmethod
    def _ler_grade(grade: Any) -> list[dict[str, str]]:
        """Só as colunas usadas na conferência e no histórico (antes: todas as colunas da grade)."""
        linhas: list[dict[str, str]] = []
        for linha in range(int(grade.RowCount)):
            valores: dict[str, str] = {}
            for coluna in COLUNAS_GRADE:
                try:
                    valores[coluna] = str(grade.GetCellValue(linha, coluna) or "").strip()
                except Exception:  # noqa: BLE001 - coluna que não existe nesta grade
                    continue
            linhas.append(valores)
        return linhas

    @staticmethod
    def _conferir_valores(valores: dict[str, str], linha: int, atividade: AtividadeSelecionada, etapa: str,
                          com_responsavel: bool) -> None:
        esperados = [(COLUNA_DESCRICAO, atividade.descricao)]
        if atividade.subgrupo:
            esperados.append((COLUNA_SUBGRUPO, atividade.subgrupo))
        if com_responsavel and atividade.responsavel:
            esperados.append((COLUNA_RESPONSAVEL, atividade.responsavel))
        for coluna, esperado in esperados:
            atual = " ".join(valores.get(coluna, "").split()).upper()
            if atual != " ".join(esperado.split()).upper():
                raise ValorRejeitado(
                    f"Linha {linha + 1} da grade: {coluna} = '{atual or 'vazio'}', esperado '{esperado}'. "
                    "Nada foi transferido.",
                    etapa=etapa,
                )

    @staticmethod
    def _nova_janela(conexao: Any, ids_antes: set[str]) -> Any:
        for i in range(conexao.Children.Count):
            candidata = conexao.Children(i)
            if candidata.Id not in ids_antes:
                return candidata
        return None

    @staticmethod
    def _texto_da_janela(janela: Any) -> str:
        try:
            area = janela.findById("usr")
            partes = [str(area.Children(i).Text).strip() for i in range(area.Children.Count)]
            return " ".join(p for p in partes if p)
        except Exception:  # noqa: BLE001
            return ""
