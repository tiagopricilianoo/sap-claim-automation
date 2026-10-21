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

TRANSACOES_MENU = frozenset({"SESSION_MANAGER", "SMEN", "S000"})
MAX_JANELAS_PADRAO = 6


def _numero_documento(texto: str) -> str:
    """'Documento ZDC 20000263669 000 00 criado' -> '20000263669'."""
    achado = re.search(r"Documento\s+\S+\s+(\d+)", texto or "")
    return achado.group(1) if achado else ""


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
                encontradas.append(SessaoEncontrada(c, s, _ler_info(conexao.Children(s))))
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

    def fechar_janela(self) -> None:
        """Fecha a janela da automação (nunca as do usuário)."""
        if self._conexao is not None and self._s is not None:
            self._conexao.CloseSession(self._s.Id)
            log.info("Janela da automação fechada")
        self._s = None

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
        for posicao, atividade in enumerate(atividades):
            self._conferir_linha(grade, posicao, atividade, "conferência final das atividades",
                                 com_responsavel=True)
        linhas = self._ler_grade(grade)

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
        if self._s.Children.Count > 1:          # o SAP pergunta a aplicação (ex.: PDF)
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
        passos = max(1, int(self._timeout / 0.1))
        for _ in range(passos):
            resultado = condicao()
            if resultado is not None:
                return resultado
            self._dormir(0.1)
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
        ordem = grade.ColumnOrder
        try:
            colunas = [str(ordem(i)) for i in range(ordem.Count)]
        except Exception:  # noqa: BLE001 - algumas versões expõem só iteração
            colunas = [str(c) for c in ordem]
        return [
            {c: str(grade.GetCellValue(linha, c) or "").strip() for c in colunas}
            for linha in range(int(grade.RowCount))
        ]

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
