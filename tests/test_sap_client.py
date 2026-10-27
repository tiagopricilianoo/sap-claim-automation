# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Testes do cliente SAP com objetos COM simulados (rodam sem SAP e sem Windows)."""

import pytest

import sap_client as sc
from sap_client import SapClient, escolher_base, listar_sessoes
from sap_gateway import (
    ElementoNaoEncontrado,
    SapGateway,
    SessaoIndisponivel,
    SistemaIncorreto,
    ValorRejeitado,
)


# ================================================================ COM simulado

class _Colecao:
    def __init__(self, itens):
        self._itens = itens

    @property
    def Count(self):
        return len(self._itens)

    def __call__(self, i):
        return self._itens[i]


class _Info:
    def __init__(self, sistema, mandante, usuario, transacao):
        self.SystemName, self.Client, self.User = sistema, mandante, usuario
        self.Language, self.Transaction = "PT", transacao


class _Elemento:
    def __init__(self, dono, id_):
        self._dono, self._id = dono, id_
        self.text, self.key, self.prensado = "", "", 0

    # janela principal: minimizar / restaurar (a automação reconhece a janela que ela mesma minimizou)
    def iconify(self):
        self._dono.minimizada = True

    def maximize(self):
        self._dono.minimizada = False

    @property
    def Iconic(self):
        return getattr(self._dono, "minimizada", False)

    def sendVKey(self, tecla):
        self._dono.vkeys.append(tecla)
        gancho = self._dono.ao_vkey.get(tecla)
        if gancho:
            gancho()

    def selectNode(self, no):
        self._dono.acoes.append(f"selectNode {no.strip()}")

    def nodeContextMenu(self, no):
        self._dono.acoes.append("contexto")

    def selectContextMenuItem(self, item):
        self._dono.acoes.append(f"menu {item}")

    def select(self):
        self._dono.acoes.append(f"select {self._id}")

    def selectItem(self, *args):
        pass

    def clickLink(self, *args):
        self._dono.acoes.append("clickLink")

    def press(self):
        self.prensado += 1
        if self._id == sc.POPUP_OK and self._dono.popups:   # mesmo ID do OK da janela de arquivo
            self._dono.popups.pop(0)
        if self._id == sc.TRANSFERIR:
            self._dono.acoes.append("transferir")
        if self._id == sc.CRIAR_DOCUMENTO:
            self._dono.lista = list(self._dono.lista_tipos)
        if self._id == sc.ARQ_OK:
            self._dono.lista = list(self._dono.lista_aplicacoes)


# Árvore como no SAP real (prints de 20 e 21/10/2026): pastas com chave fixa,
# itens com chave SEQUENCIAL (muda quando a árvore muda).
PASTAS = {
    "10COMERCIAL": ("GRP-COM", ["PRODUTO_A", "PRODUTO_B", "SV TU", "SV TR", "SEG.CONTROLE"]),
    "20ENGENHARIA": ("GRP-ENG", ["PRODUTO_A", "PRODUTO_B", "ESTUDO 1", "ESTUDO 2",
                                   "ITEM AUXILIAR 1", "ITEM AUXILIAR 2", "ANALISE TECNICA"]),
    "30INDUSTRIAL": ("GRP-IND", ["SV TU", "SV TR", "TU", "TR"]),
    "40SUPRIMENTOS": ("GRP-SUP", ["SV TU", "SV TR", "TU", "TR"]),
    "50CUSTOS": ("GRP-CUS", ["TU", "TR", "SV"]),
}


class _Arvore:
    def __init__(self, sessao, deslocamento=0):
        self._s, self.selectedNode, self.expandidos = sessao, "", []
        self.itens: dict[str, tuple[str, str, str]] = {}   # chave -> (pasta, sub grupo, texto)
        contador = 600 + deslocamento
        for pasta, (sub, textos) in PASTAS.items():
            for texto in textos:
                contador += 1
                self.itens[f"{contador:012d}"] = (pasta, sub, texto)

    def chave_de(self, pasta, texto):
        return next(k for k, (p, _, t) in self.itens.items() if p == pasta and t == texto)

    def expandNode(self, chave):
        if chave in self._s.pastas_ausentes:
            raise RuntimeError("node not found")
        self.expandidos.append(chave)

    def GetSubNodesCol(self, pasta):
        return _Colecao([k for k, (p, _, _) in self.itens.items() if p == pasta])

    def GetNodeTextByKey(self, chave):
        return self.itens[chave][2]

    def doubleClickNode(self, chave):
        pasta, sub, texto = self.itens[chave]
        if texto in self._s.nos_mudos:      # clique que não gera linha
            return
        self._s.linhas.append({"SUB_GRUPO": sub, "DS_ATIVIDADE": texto,
                               "RESP": "GRUPO-ENG" if texto == "ANALISE TECNICA" else ""})


class _Ordem:
    def __init__(self, nomes):
        self._n = nomes

    @property
    def Count(self):
        return len(self._n)

    def __call__(self, i):
        return self._n[i]


class _Grade:
    def __init__(self, sessao):
        self._s = sessao

    @property
    def RowCount(self):
        return len(self._s.linhas)

    @property
    def ColumnOrder(self):
        return _Ordem(["SUB_GRUPO", "DS_ATIVIDADE", "RESP"])

    def GetCellValue(self, linha, coluna):
        return self._s.linhas[linha][coluna]

    def modifyCell(self, linha, coluna, valor):
        self._s.linhas[linha][coluna] = valor

    def setCurrentCell(self, *a):
        pass

    def selectAll(self):
        self._s.acoes.append("selectAll")


class _Barra:
    def __init__(self):
        self.MessageType, self.Text, self.MessageId, self.MessageNumber = "", "", "", ""


class _Janela:
    def __init__(self, sessao):
        self._s = sessao

    @property
    def Text(self):
        return "Informação"

    @property
    def PopupDialogText(self):
        return self._s.popups[0] if self._s.popups else ""

    def sendVKey(self, tecla):
        self._s.escolhidos.append(self._s.foco)
        self._s.lista = []


class _Rotulo:
    def __init__(self, sessao, texto):
        self._s, self.Text = sessao, texto

    def setFocus(self):
        self._s.foco = self.Text.strip()


class _Area:
    def __init__(self, sessao):
        self.Children = _Colecao([_Rotulo(sessao, x) for x in sessao.lista])


class _Sessao:
    _contador = 0

    def __init__(self, conexao=None, sistema="PRD", mandante="100", usuario="USUARIO1",
                 transacao="SESSION_MANAGER", ocupada=False, sem=()):
        _Sessao._contador += 1
        self.Id = f"/app/con[0]/ses[{_Sessao._contador}]"
        self._conexao = conexao
        self.Info = _Info(sistema, mandante, usuario, transacao)
        self.Busy = ocupada
        self.sem = set(sem)          # IDs que "não existem" na tela
        self.popups: list[str] = []
        self.vkeys: list[int] = []
        self.barra = _Barra()
        self._elementos: dict[str, _Elemento] = {}
        self.linhas: list[dict] = []
        self.acoes: list[str] = []
        self.pastas_ausentes: set[str] = set()
        self.nos_mudos: set[str] = set()
        self.arvore = _Arvore(self)
        self.lista: list[str] = []
        self.lista_tipos = ["Tipo  Descrição", "ZDC   Anexo Geral", "ZPR   Proposta"]
        self.lista_aplicacoes: list[str] = []
        self.escolhidos: list[str] = []
        self.foco = ""
        self.ao_vkey: dict = {}

    @property
    def Children(self):
        return _Colecao([None] * (2 if (self.popups or self.lista) else 1))

    def findById(self, id_):
        if id_ in self.sem:
            raise RuntimeError("The control could not be found by id.")
        if id_ == sc.STATUS:
            return self.barra
        if id_ == sc.POPUP:
            return _Janela(self)
        if id_ == sc.LISTA_POPUP:
            return _Area(self)
        if id_ == sc.ARVORE:
            return self.arvore
        if id_ == sc.GRADE:
            if not self.linhas:   # como no SAP real: a grade só existe após a 1ª atividade
                raise RuntimeError("The control could not be found by id.")
            return _Grade(self)
        return self._elementos.setdefault(id_, _Elemento(self, id_))

    def CreateSession(self):
        self._conexao.criadas.append(_Sessao(self._conexao))

    def campo(self, id_):
        return self._elementos[id_]


class _Conexao:
    def __init__(self, *sessoes_kw):
        self.sessoes = [_Sessao(self, **kw) for kw in sessoes_kw]
        self.criadas: list[_Sessao] = []
        self.fechadas: list[str] = []

    @property
    def Children(self):
        return _Colecao(self.sessoes + self.criadas)

    def CloseSession(self, id_):
        self.fechadas.append(id_)


def _engine(*conexoes):
    class _Engine:
        Children = _Colecao(list(conexoes))
    return _Engine()


def _cliente(settings, *conexoes, **kw):
    return SapClient(settings, engine_factory=lambda: _engine(*conexoes), dormir=lambda s: None, **kw)


# ================================================================ escolha da base

def test_base_pode_estar_em_transacao(settings):
    base = escolher_base(listar_sessoes(_engine(_Conexao({"transacao": "CLM1"}))), settings)
    assert base.info.transacao == "CLM1"


def test_base_prefere_menu_principal(settings):
    base = escolher_base(listar_sessoes(_engine(_Conexao({"transacao": "CLM1"}, {}))), settings)
    assert base.sessao == 1


def test_base_nao_pode_estar_ocupada(settings):
    with pytest.raises(SessaoIndisponivel, match="processando"):
        escolher_base(listar_sessoes(_engine(_Conexao({"ocupada": True}))), settings)


def test_sistema_errado(settings):
    with pytest.raises(SistemaIncorreto, match="EQ0/100"):
        escolher_base(listar_sessoes(_engine(_Conexao({"sistema": "EQ0"}))), settings)


def test_tela_de_login(settings):
    with pytest.raises(SessaoIndisponivel, match="login"):
        escolher_base(listar_sessoes(_engine(_Conexao({"usuario": ""}))), settings)


def test_usuarios_diferentes(settings):
    with pytest.raises(SessaoIndisponivel, match="usuários diferentes"):
        escolher_base(listar_sessoes(_engine(_Conexao({}), _Conexao({"usuario": "OUTRO"}))), settings)


def test_sem_sessoes(settings):
    with pytest.raises(SessaoIndisponivel, match="Nenhuma sessão"):
        escolher_base([], settings)


# ================================================================ janela própria

def test_abre_janela_nova_e_nao_usa_a_do_usuario(settings):
    conexao = _Conexao({"transacao": "CLM1"})
    cliente = _cliente(settings, conexao)
    info = cliente.sessao()
    assert len(conexao.criadas) == 1
    assert info.usuario == "USUARIO1"
    cliente.abrir_criacao("Z1")
    assert conexao.sessoes[0].vkeys == []            # janela do usuário intocada
    assert conexao.criadas[0].vkeys == [0, 0]        # tudo aconteceu na janela nova


def test_fecha_so_a_janela_da_automacao(settings):
    conexao = _Conexao({})
    cliente = _cliente(settings, conexao)
    cliente.sessao()
    cliente.fechar_janela()
    assert conexao.fechadas == [conexao.criadas[0].Id]


def test_limite_de_janelas(settings):
    conexao = _Conexao(*[{} for _ in range(6)])
    with pytest.raises(SessaoIndisponivel, match="Limite de 6"):
        _cliente(settings, conexao).sessao()
    assert conexao.criadas == []


def test_janela_nova_que_nao_aparece(settings):
    conexao = _Conexao({})
    conexao.sessoes[0].CreateSession = lambda: None
    with pytest.raises(SessaoIndisponivel, match="abertura da janela"):
        _cliente(settings, conexao, timeout_s=0.3).sessao()


def test_diagnostico_nao_abre_janela(settings):
    conexao = _Conexao({})
    _cliente(settings, conexao).diagnostico()
    assert conexao.criadas == []


# ================================================================ Fase 1

def _pronto(settings):
    conexao = _Conexao({})
    cliente = _cliente(settings, conexao)
    cliente.sessao()
    return cliente, conexao.criadas[0]


def test_abre_clm1_com_tipo_zo(settings):
    cliente, janela = _pronto(settings)
    cliente.abrir_criacao("Z1")
    assert janela.campo(sc.OKCODE).text == "/nCLM1"
    assert janela.campo(sc.TIPO_NOTA).key == "Z1"


def test_preenche_campos_com_ids_da_gravacao(settings):
    cliente, janela = _pronto(settings)
    cliente.preencher_nota(descricao="Desc", texto_livre="linha 1\nlinha 2", causa_grupo="01",
                           causa_codigo="0001", prioridade="1", ordem="1234567", item="10")
    assert janela.campo(sc.DESCRICAO).text == "Desc"
    assert janela.campo(sc.TEXTO_LIVRE).text == "linha 1\rlinha 2"
    assert (janela.campo(sc.CAUSA_GRUPO).text, janela.campo(sc.CAUSA_CODIGO).text) == ("01", "0001")
    assert janela.campo(sc.PRIORIDADE).key == "1"
    assert (janela.campo(sc.ORDEM).text, janela.campo(sc.ITEM).text) == ("1234567", "10")
    assert "VIQMEL-LS_KDAUF" in sc.ORDEM and "RIWO00-HEADKTXT" in sc.DESCRICAO


def test_campo_ausente_vira_erro_claro(settings):
    cliente, janela = _pronto(settings)
    janela.sem.add(sc.ORDEM)
    with pytest.raises(ElementoNaoEncontrado) as erro:
        cliente.preencher_nota(descricao="d", texto_livre="t", causa_grupo="01", causa_codigo="0001",
                               prioridade="1", ordem="1", item="10")
    assert erro.value.etapa == "ordem do cliente"


def test_erro_do_sap_ao_abrir(settings):
    cliente, janela = _pronto(settings)
    janela.barra.MessageType, janela.barra.Text = "E", "Sem autorização para CLM1"
    with pytest.raises(ValorRejeitado, match="Sem autorização"):
        cliente.abrir_criacao("Z1")


def test_le_e_confirma_janela_de_aviso(settings):
    cliente, janela = _pronto(settings)
    janela.popups.append("O cliente CLIENTE X tem bloqueio de registro")
    popup = cliente.popup_aberto()
    assert "bloqueio de registro" in popup.texto
    cliente.confirmar_popup()
    assert cliente.popup_aberto() is None


def test_status_lido_da_barra(settings):
    cliente, janela = _pronto(settings)
    janela.barra.MessageType, janela.barra.Text = "S", "Nota 100063949 gravada"
    assert cliente.status().texto == "Nota 100063949 gravada"


def test_sem_janela_aberta_nao_age(settings):
    with pytest.raises(SessaoIndisponivel):
        _cliente(settings, _Conexao({})).abrir_criacao("Z1")


# ================================================================ Fase 3: atividades

def _rota(settings, chave, usuario="USUARIO1"):
    from sap_gateway import AtividadeSelecionada
    return [AtividadeSelecionada(a.descricao, a.subgrupo, a.pasta, a.no, a.responsavel_para(usuario))
            for a in settings.rota(chave).atividades]


def test_produto_b_custo_responsaveis_nas_linhas_certas(settings):
    cliente, janela = _pronto(settings)
    linhas = cliente.selecionar_atividades(_rota(settings, "PRODUTO_B_CUSTO"), "ROOT")
    assert [l["DS_ATIVIDADE"] for l in linhas] == ["ANALISE TECNICA", "TR", "TR", "TR", "PRODUTO_B"]
    assert [l["SUB_GRUPO"] for l in linhas] == ["GRP-ENG", "GRP-IND", "GRP-SUP", "GRP-CUS", "GRP-COM"]
    assert [l["RESP"] for l in linhas] == ["GRUPO-ENG", "USUARIO_IND", "USUARIO_SUP", "USUARIO_CUS", "USUARIO1"]
    assert janela.arvore.expandidos[0] == "ROOT"
    assert janela.acoes[-2:] == ["selectAll", "transferir"]


def test_grade_inexistente_antes_do_primeiro_clique(settings):
    """Regressão do ensaio real de 20/10: CONTAINER2 não existe com zero atividades."""
    cliente, janela = _pronto(settings)
    assert janela.linhas == []
    linhas = cliente.selecionar_atividades(_rota(settings, "PRODUTO_B"), "ROOT")
    assert len(linhas) == 2


def test_transferir_que_nao_fecha_a_janela_e_erro(settings):
    cliente, janela = _pronto(settings)
    janela.popups.append("janela de atividades ainda aberta")   # simula wnd[1] que não fechou
    with pytest.raises(ValorRejeitado, match="continuou aberta"):
        cliente.selecionar_atividades(_rota(settings, "PRODUTO_A"), "ROOT")


def test_produto_a(settings):
    cliente, _ = _pronto(settings)
    linhas = cliente.selecionar_atividades(_rota(settings, "PRODUTO_A"), "ROOT")
    assert [(l["DS_ATIVIDADE"], l["RESP"]) for l in linhas] == [("ANALISE TECNICA", "GRUPO-ENG"), ("PRODUTO_A", "USUARIO1")]


def test_clique_que_nao_gera_linha_para_tudo(settings):
    cliente, janela = _pronto(settings)
    janela.nos_mudos.add("TR")
    with pytest.raises(ValorRejeitado, match="esperado 2"):
        cliente.selecionar_atividades(_rota(settings, "PRODUTO_B_CUSTO"), "ROOT")
    assert "transferir" not in janela.acoes
    assert all(l["RESP"] != "USUARIO_CUS" for l in janela.linhas)


def test_pasta_ausente(settings):
    cliente, janela = _pronto(settings)
    janela.pastas_ausentes.add("50CUSTOS")
    with pytest.raises(ElementoNaoEncontrado, match="50CUSTOS"):
        cliente.selecionar_atividades(_rota(settings, "PRODUTO_B_CUSTO"), "ROOT")
    assert "transferir" not in janela.acoes


def test_grade_ja_preenchida_e_recusada(settings):
    cliente, janela = _pronto(settings)
    janela.linhas.append({"SUB_GRUPO": "X", "DS_ATIVIDADE": "Y", "RESP": ""})
    with pytest.raises(ValorRejeitado, match="já tinha"):
        cliente.selecionar_atividades(_rota(settings, "PRODUTO_A"), "ROOT")


@pytest.mark.parametrize("deslocamento", [-1, 1, 37])
def test_codigos_dos_itens_mudaram_e_mesmo_assim_acerta(settings, deslocamento):
    """Regressão de 21/10/2026: os códigos dos itens deslocaram uma posição.
    A automação acha cada item pelo texto dentro da pasta, então não depende deles."""
    cliente, janela = _pronto(settings)
    janela.arvore = _Arvore(janela, deslocamento=deslocamento)
    linhas = cliente.selecionar_atividades(_rota(settings, "PRODUTO_B_CUSTO"), "ROOT")
    assert [(l["DS_ATIVIDADE"], l["SUB_GRUPO"], l["RESP"]) for l in linhas] == [
        ("ANALISE TECNICA", "GRP-ENG", "GRUPO-ENG"), ("TR", "GRP-IND", "USUARIO_IND"),
        ("TR", "GRP-SUP", "USUARIO_SUP"), ("TR", "GRP-CUS", "USUARIO_CUS"), ("PRODUTO_B", "GRP-COM", "USUARIO1")]


def test_nao_usa_o_codigo_do_settings(settings):
    """Mesmo com códigos errados no settings.ini, o item certo é clicado."""
    from dataclasses import replace
    cliente, janela = _pronto(settings)
    rota = [replace(a, no="000000000001") for a in _rota(settings, "PRODUTO_A")]
    linhas = cliente.selecionar_atividades(rota, "ROOT")
    assert [l["DS_ATIVIDADE"] for l in linhas] == ["ANALISE TECNICA", "PRODUTO_A"]


def test_item_inexistente_na_pasta_para_antes_de_clicar(settings):
    from dataclasses import replace
    cliente, janela = _pronto(settings)
    rota = _rota(settings, "PRODUTO_A")
    rota[0] = replace(rota[0], descricao="ENG. APLIC. ANALISE")
    with pytest.raises(ElementoNaoEncontrado, match="Itens da pasta"):
        cliente.selecionar_atividades(rota, "ROOT")
    assert janela.linhas == [] and "transferir" not in janela.acoes


def test_linha_com_texto_errado_para_antes_de_transferir(settings):
    """Se o SAP criar uma linha diferente do item clicado, nada é transferido."""
    cliente, janela = _pronto(settings)
    original = janela.arvore.doubleClickNode

    def clique_trocado(chave):
        original(chave)
        janela.linhas[-1]["DS_ATIVIDADE"] = "ITEM AUXILIAR 2"
    janela.arvore.doubleClickNode = clique_trocado
    with pytest.raises(ValorRejeitado, match="ITEM AUXILIAR 2"):
        cliente.selecionar_atividades(_rota(settings, "PRODUTO_A"), "ROOT")
    assert "transferir" not in janela.acoes


def test_responsavel_nao_aplicado_para_antes_de_transferir(settings):
    cliente, janela = _pronto(settings)
    janela_grade_modify = _Grade.modifyCell
    _Grade.modifyCell = lambda self, linha, coluna, valor: None     # SAP ignora a edição
    try:
        with pytest.raises(ValorRejeitado, match="RESP"):
            cliente.selecionar_atividades(_rota(settings, "PRODUTO_A"), "ROOT")
    finally:
        _Grade.modifyCell = janela_grade_modify
    assert "transferir" not in janela.acoes


# ================================================================ pôr em processamento

def test_bandeira_clicada_quando_a_dica_confere(settings):
    cliente, janela = _pronto(settings)
    botao = janela.findById(sc.BANDEIRA_PROCESSAMENTO)
    botao.Tooltip = "Pôr em processamento  (Shift+F2)"
    cliente.por_em_processamento()
    assert botao.prensado == 1


def test_bandeira_nao_clica_botao_desconhecido(settings):
    cliente, janela = _pronto(settings)
    botao = janela.findById(sc.BANDEIRA_PROCESSAMENTO)
    botao.Tooltip = "Encerrar nota"
    with pytest.raises(ElementoNaoEncontrado, match="Nada foi clicado"):
        cliente.por_em_processamento()
    assert botao.prensado == 0


def test_bandeira_com_erro_do_sap(settings):
    cliente, janela = _pronto(settings)
    janela.findById(sc.BANDEIRA_PROCESSAMENTO).Tooltip = "Pôr em processamento"
    janela.barra.MessageType, janela.barra.Text = "E", "Status não permitido"
    with pytest.raises(ValorRejeitado, match="Status não permitido"):
        cliente.por_em_processamento()


def test_cliente_cobre_o_contrato(settings):
    contrato = {n for n in dir(SapGateway) if not n.startswith("_")}
    assert contrato <= set(dir(SapClient))


# ================================================================ Fase 2: documento ZDC

from pathlib import PureWindowsPath  # noqa: E402

from sap_gateway import ResultadoIncerto  # noqa: E402

ARQUIVO = PureWindowsPath(r"C:\Users\usuario\Downloads\Proposta.pdf")


def _doc_ok(janela):
    def gravar():
        janela.barra.MessageType, janela.barra.Text = "S", "Documento ZDC 20000263669 000 00 criado"
    janela.ao_vkey[sc.TECLA_GRAVAR] = gravar


def _criar(cliente, aplicacao="PDF"):
    return cliente.criar_documento(tipo="ZDC", descricao="Proposta.pdf", laboratorio="L01",
                                   arquivo=ARQUIVO, aplicacao=aplicacao)


def test_documento_pdf_completo(settings):
    cliente, janela = _pronto(settings)
    janela.lista_aplicacoes = ["Apl Descrição", "DDE PDF German", "P3D Acrobat Reader 3D", "PDF Acrobat Reader"]
    _doc_ok(janela)
    assert _criar(cliente) == "20000263669"
    assert janela.escolhidos == ["ZDC   Anexo Geral", "PDF Acrobat Reader"]
    assert janela.campo(sc.DOC_DESCRICAO).text == "Proposta.pdf"
    assert janela.campo(sc.DOC_LABORATORIO).text == "L01"
    assert janela.campo(sc.ARQ_PASTA).text == "C:\\Users\\usuario\\Downloads\\"
    assert janela.campo(sc.ARQ_NOME).text == "Proposta.pdf"
    assert "menu CF_IMPORT" in janela.acoes
    assert janela.vkeys[-1] == sc.TECLA_GRAVAR


def test_escolhe_pdf_pelo_texto_e_nao_pela_posicao(settings):
    cliente, janela = _pronto(settings)
    janela.lista_aplicacoes = ["PDF Acrobat Reader", "DDE PDF German"]   # ordem diferente da gravação
    _doc_ok(janela)
    _criar(cliente)
    assert janela.escolhidos[-1].upper().startswith("PDF ")


def test_zip_escolhe_zip_pelo_texto(settings):
    """Script5 (22/10/2026): o ZIP também abre a janela de aplicações."""
    from pathlib import PureWindowsPath
    cliente, janela = _pronto(settings)
    janela.lista_aplicacoes = ["Apl Descrição", "DDE PDF German", "TXT Editor", "ZIP Arquivo compactado"]
    _doc_ok(janela)
    numero = cliente.criar_documento(tipo="ZDC", descricao="anexos.zip", laboratorio="L01",
                                     arquivo=PureWindowsPath(r"C:\Users\usuario\Downloads\anexos.zip"), aplicacao="ZIP")
    assert numero == "20000263669"
    assert janela.escolhidos[-1] == "ZIP Arquivo compactado"


def test_tipo_nao_configurado_que_abre_janela_para_antes_de_gravar(settings):
    from pathlib import PureWindowsPath
    cliente, janela = _pronto(settings)
    janela.lista_aplicacoes = ["DWG AutoCAD", "TIF Imagem"]
    with pytest.raises(ValorRejeitado, match="aplicacao_por_extensao"):
        cliente.criar_documento(tipo="ZDC", descricao="desenho.dwg", laboratorio="L01",
                                arquivo=PureWindowsPath(r"C:\x\desenho.dwg"), aplicacao="")
    assert sc.TECLA_GRAVAR not in janela.vkeys


def test_sem_janela_de_aplicacao_para_excel(settings):
    cliente, janela = _pronto(settings)
    _doc_ok(janela)                       # lista_aplicacoes vazia: SAP atribui sozinho (XLS)
    assert _criar(cliente) == "20000263669"
    assert len(janela.escolhidos) == 1


def test_tipo_ausente_para_antes_de_gravar(settings):
    cliente, janela = _pronto(settings)
    janela.lista_tipos = ["ZPR Proposta"]
    with pytest.raises(ValorRejeitado, match="ZDC"):
        _criar(cliente)
    assert sc.TECLA_GRAVAR not in janela.vkeys


def test_aplicacao_pdf_ausente_para_antes_de_gravar(settings):
    cliente, janela = _pronto(settings)
    janela.lista_aplicacoes = ["DDE PDF German", "P3D Acrobat Reader 3D"]
    with pytest.raises(ValorRejeitado, match="PDF"):
        _criar(cliente)
    assert sc.TECLA_GRAVAR not in janela.vkeys


def test_campo_de_pasta_ausente_para_antes_de_gravar(settings):
    cliente, janela = _pronto(settings)
    janela.sem.add(sc.ARQ_PASTA)
    with pytest.raises(ElementoNaoEncontrado):
        _criar(cliente)
    assert sc.TECLA_GRAVAR not in janela.vkeys


def test_documento_sem_mensagem_de_sucesso_e_incerto(settings):
    cliente, janela = _pronto(settings)
    with pytest.raises(ResultadoIncerto):
        _criar(cliente)                   # Ctrl+S enviado, barra vazia


# ================================================================ gravação do claim

def test_gravar_nota_retorna_status(settings):
    cliente, janela = _pronto(settings)
    def gravar():
        janela.barra.MessageType, janela.barra.Text = "S", "Nota 100064300 gravada"
    janela.ao_vkey[sc.TECLA_GRAVAR] = gravar
    assert cliente.gravar_nota().texto == "Nota 100064300 gravada"


def test_gravar_nota_com_queda_e_incerto(settings):
    cliente, janela = _pronto(settings)
    def cair():
        raise RuntimeError("RPC server unavailable")
    janela.ao_vkey[sc.TECLA_GRAVAR] = cair
    with pytest.raises(ResultadoIncerto):
        cliente.gravar_nota()


def test_numero_do_documento():
    assert sc._numero_documento("Documento ZDC 20000263669 000 00 criado") == "20000263669"
    assert sc._numero_documento("Dados gravados") == ""
