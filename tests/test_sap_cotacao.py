# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Linha nova na cotação (VA22) com uma tela de itens simulada (sem SAP, sem Windows).

A simulação segue o script gravado em 22/10/2026 ("VA21.vbs") e os prints:
lista de itens com rolagem, coluna do centro pelo NOME, janela "Gravar documento
incompleto" e mensagem V1/311 "Cotação ... foi gravado(a)".
"""

import pytest

import sap_client as sc
from sap_client import SapClient
from sap_gateway import ElementoNaoEncontrado, PopupInesperado, ResultadoIncerto, ValorRejeitado


class _Celula:
    def __init__(self, grade, linha, nome):
        self._g, self._l, self.Name = grade, linha, nome

    @property
    def Changeable(self):
        return (self._l, self.Name) not in self._g.bloqueadas

    @property
    def Text(self):
        return self._g.linha(self._l).get(self.Name, "")

    @Text.setter
    def Text(self, valor):
        self._g.linha(self._l)[self.Name] = valor

    text = Text


class _Barra:
    def __init__(self, tela):
        self._t = tela

    @property
    def Position(self):
        return self._t.rolagem

    @Position.setter
    def Position(self, valor):
        self._t.rolagem = valor

    @property
    def Maximum(self):
        return max(0, len(self._t.linhas) + 3 - self._t.visiveis)


_PREFIXO = {sc.COL_ITEM: "txt", sc.COL_MATERIAL: "ctxt", sc.COL_QUANTIDADE: "txt", sc.COL_CENTRO: "ctxt"}


class _Ref:
    def __init__(self, id_):
        self.Id = id_


class _Lista:
    def __init__(self, itens):
        self._i = itens

    @property
    def Count(self):
        return len(self._i)

    def __call__(self, i):
        return self._i[i]


class _Tabela:
    def __init__(self, tela, colunas, id_):
        self._t, self._colunas, self.Id = tela, colunas, id_

    @property
    def Children(self):
        if not self._t.celulas_enumeraveis:
            raise RuntimeError("not supported")
        self._t.enumeracoes += 1
        return _Lista([_Ref(f"{self.Id}/{_PREFIXO.get(n, 'txt')}{n}[{c},{r}]")
                       for r in range(self._t.visiveis) for c, n in enumerate(self._colunas)])

    def celula(self, nome, c, r):
        if r >= self._t.visiveis or c >= len(self._colunas) or self._colunas[c] != nome:
            raise RuntimeError("The control could not be found by id.")
        return _Celula(self._t, self._t.rolagem + r, nome)

    class _Cols:
        def __init__(self, n):
            self.Count = n

    @property
    def Columns(self):
        return self._Cols(len(self._colunas))

    @property
    def VisibleRowCount(self):
        return self._t.visiveis

    @property
    def VerticalScrollbar(self):
        return _Barra(self._t)

    def GetCell(self, r, c):
        if getattr(self._t, "sem_getcell", False):
            raise RuntimeError("not supported")
        if r >= self._t.visiveis:
            raise RuntimeError("bad index")
        return _Celula(self._t, self._t.rolagem + r, self._colunas[c])


class _Status:
    MessageType = Text = MessageId = MessageNumber = ""


class _Generico:
    def __init__(self, tela, id_):
        self._t, self._id, self.text = tela, id_, ""

    def select(self):
        self._t.abas.append(self._id)

    def press(self):
        self._t.apertou(self._id)

    def sendVKey(self, tecla):
        self._t.tecla(tecla)


class _Janela:
    def __init__(self, titulo):
        self.Text = titulo


class _Tela:
    """Sessão SAP na VA22 com a lista de itens."""

    def __init__(self, itens=("10",), visiveis=6, centro_na_aba_itens=True, centro_padrao="1001"):
        self.Busy = False
        self.visiveis, self.rolagem = visiveis, 0
        self.linhas = [{sc.COL_ITEM: i, sc.COL_MATERIAL: "10000001", sc.COL_QUANTIDADE: "1",
                        sc.COL_CENTRO: "1001"} for i in itens]
        self.centro_padrao = centro_padrao
        colunas = [sc.COL_ITEM, sc.COL_MATERIAL, sc.COL_QUANTIDADE, "VBAP-ARKTX"]
        self.colunas_02 = colunas + ([sc.COL_CENTRO] if centro_na_aba_itens else [])
        # Aba Venda: centro na coluna 7, como no programa de cotação (ctxtVBAP-WERKS[7,0])
        self.colunas_01 = [sc.COL_ITEM, sc.COL_MATERIAL, "RV45A-KWMENG", "VBAP-VRKME", "VBAP-ARKTX",
                           "VBAP-PSTYV", "VBAP-UEPOS", sc.COL_CENTRO]
        self.enumeracoes = 0
        self.barra = _Status()
        self.popup = ""
        self.abas: list[str] = []
        self.campos: dict[str, _Generico] = {}
        self.vkeys: list[int] = []
        self.erro_no_enter = ""
        self.janela_no_enter = ""
        self.resposta_gravar: tuple[str, str, str, str] | None = None
        self.titulo_ao_gravar = "Gravar documento incompleto"
        self.gravadas = 0
        self.celulas_enumeraveis = True
        self.aviso_na_venda = 0         # quantos Enter na aba Venda respondem com aviso W
        self.bloqueadas: set = set()      # (linha absoluta, campo) sem edição

    def linha(self, i):
        while len(self.linhas) <= i:
            self.linhas.append({})
        return self.linhas[i]

    @property
    def Children(self):
        class _C:
            Count = 2 if self.popup else 1
        return _C()

    def findById(self, id_):
        if id_ == sc.STATUS:
            return self.barra
        if id_ == sc._VISAO:
            tela = self

            class _Abas:
                @property
                def SelectedTab(self):
                    return _Ref("/app/con[0]/ses[1]/" + (tela.abas[-1] if tela.abas else sc.ABA_ITENS))
            return _Abas()
        if id_ == sc.POPUP:
            return _Janela(self.popup)
        for tabela_id, colunas in ((sc.TABELA_ITENS, self.colunas_02), (sc.TABELA_ITENS_2, self.colunas_01)):
            if id_ == tabela_id:
                return _Tabela(self, colunas, tabela_id)
            if id_.startswith(tabela_id + "/"):
                achado = sc._ID_CELULA.match(id_[len(tabela_id) + 1:])
                return _Tabela(self, colunas, tabela_id).celula(
                    achado.group(2), int(achado.group(3)), int(achado.group(4)))
        return self.campos.setdefault(id_, _Generico(self, id_))

    def tecla(self, tecla):
        self.vkeys.append(tecla)
        self.barra.MessageType = self.barra.Text = ""
        if self.aviso_na_venda and self.abas and self.abas[-1] == sc.ABA_ITENS_2:
            self.aviso_na_venda -= 1
            self.barra.MessageType, self.barra.Text = "W", "Entrar Condições pagamento"
            return
        if self.erro_no_enter:
            self.barra.MessageType, self.barra.Text = "E", self.erro_no_enter
            return
        if self.janela_no_enter:
            self.popup = self.janela_no_enter
        for l in self.linhas:
            if l.get(sc.COL_MATERIAL) and not l.get(sc.COL_CENTRO):
                l[sc.COL_CENTRO] = self.centro_padrao   # o que o SAP faria sozinho (às vezes errado)

    def apertou(self, id_):
        if id_ == sc.BOTAO_GRAVAR:
            self.popup = self.titulo_ao_gravar
        elif id_ == sc.GRAVAR_INCOMPLETO:
            self.popup = ""
            self.gravadas += 1
            tipo, texto, idm, num = self.resposta_gravar or ("S", "Cotação 1234567 foi gravado(a)", "V1", "311")
            self.barra.MessageType, self.barra.Text = tipo, texto
            self.barra.MessageId, self.barra.MessageNumber = idm, num


def _cliente(settings, tela):
    cliente = SapClient(settings, engine_factory=lambda: None, dormir=lambda s: None, timeout_s=0.2)
    cliente._s = tela
    return cliente


def _produto_a(cliente):
    return cliente.preencher_linha(material="10000001", centro="1001", quantidade="1")


def _produto_b(cliente):
    return cliente.preencher_linha(material="10000002", centro="1002", quantidade="1")


# ---------------------------------------------------------------- abrir

def test_abre_va22_com_a_cotacao(settings):
    tela = _Tela()
    cliente = _cliente(settings, tela)
    cliente.abrir_cotacao("1234567")
    assert tela.campos[sc.OKCODE].text == "/nVA22"
    assert tela.campos[sc.COTACAO_NUMERO].text == "1234567"
    assert tela.vkeys == [0, 0]


def test_cotacao_bloqueada_para(settings):
    tela = _Tela()
    tela.erro_no_enter = "Cotação 1234567 está sendo processada pelo usuário FULANO"
    with pytest.raises(ValorRejeitado, match="FULANO"):
        _cliente(settings, tela).abrir_cotacao("1234567")


# ---------------------------------------------------------------- preencher

def test_proxima_linha_depois_dos_itens_do_print(settings):
    # Print de 22/10/2026: itens 10, 20, 30 e 40 -> a próxima é 50
    tela = _Tela(itens=("10", "20", "30", "40"))
    linha = _produto_b(_cliente(settings, tela))
    assert (linha.item, linha.material, linha.centro) == ("50", "10000002", "1002")
    assert tela.linhas[4] == {sc.COL_ITEM: "50", sc.COL_MATERIAL: "10000002",
                              sc.COL_QUANTIDADE: "1", sc.COL_CENTRO: "1002"}


def test_centro_sempre_digitado_mesmo_quando_o_sap_preencheria(settings):
    tela = _Tela(centro_padrao="1001")       # o SAP poria 1001 também no produto_b (caso real)
    linha = _produto_b(_cliente(settings, tela))
    assert linha.centro == "1002"


def test_cotacao_sem_itens_comeca_no_10(settings):
    linha = _produto_a(_cliente(settings, _Tela(itens=())))
    assert linha.item == "10"


def test_lista_longa_rola_ate_achar_a_linha_livre(settings):
    itens = tuple(str(10 * i) for i in range(1, 15))      # 10..140, com 6 linhas visíveis
    tela = _Tela(itens=itens, visiveis=6)
    linha = _produto_a(_cliente(settings, tela))
    assert linha.item == "150"
    assert tela.linhas[14][sc.COL_MATERIAL] == "10000001"


def test_centro_na_outra_aba_quando_nao_esta_na_lista(settings):
    # Como no programa de cotação: o centro pode estar só na aba T\01
    tela = _Tela(centro_na_aba_itens=False, centro_padrao="")
    linha = _produto_b(_cliente(settings, tela))
    assert linha.centro == "1002"
    assert sc.ABA_ITENS_2 in tela.abas


def test_erro_do_sap_no_enter_para_sem_gravar(settings):
    tela = _Tela()
    tela.erro_no_enter = "Material 10000002 não existe"
    with pytest.raises(ValorRejeitado, match="não existe"):
        _produto_b(_cliente(settings, tela))
    assert tela.gravadas == 0


def test_janela_depois_do_enter_volta_para_o_servico_decidir(settings):
    tela = _Tela()
    tela.janela_no_enter = "Informação"
    linha = _produto_a(_cliente(settings, tela))
    assert linha.material == "" and tela.gravadas == 0      # o serviço vai parar na conferência


def test_coluna_de_item_ausente_e_erro_claro(settings):
    tela = _Tela()
    tela.colunas_02 = [sc.COL_MATERIAL, sc.COL_QUANTIDADE]
    with pytest.raises(ElementoNaoEncontrado, match="VBAP-POSNR.*Colunas vistas: RV45A-KWMENG, RV45A-MABNR"):
        _produto_a(_cliente(settings, tela))


def test_ids_das_celulas_como_na_gravacao(settings):
    # Script de 22/10/2026: .../txtVBAP-POSNR[0,1], .../ctxtRV45A-MABNR[1,1], .../txtRV45A-KWMENG[2,1]
    tela = _Tela(itens=("10",), centro_na_aba_itens=False, centro_padrao="")
    cliente = _cliente(settings, tela)
    mapa = cliente._mapa_colunas(sc.TABELA_ITENS)
    assert mapa[sc.COL_ITEM] == (0, "txtVBAP-POSNR")
    assert mapa[sc.COL_MATERIAL] == (1, "ctxtRV45A-MABNR")
    assert mapa[sc.COL_QUANTIDADE] == (2, "txtRV45A-KWMENG")
    assert sc.COL_CENTRO not in mapa                      # como no print: sem centro na Síntese de itens


def test_tabela_sem_celulas_enumeraveis_usa_getcell(settings):
    tela = _Tela(itens=("10", "20"))
    tela.celulas_enumeraveis = False
    assert _produto_b(_cliente(settings, tela)).item == "30"


def test_sem_children_nem_getcell_usa_os_ids_da_gravacao(settings):
    tela = _Tela(itens=("10", "20"))
    tela.celulas_enumeraveis = False
    tela.sem_getcell = True
    assert _produto_b(_cliente(settings, tela)).item == "30"


def test_centro_pela_aba_venda_como_no_print(settings):
    # Print de 26/10/2026: "Síntese de itens" sem coluna de centro; o SAP poria 1001 no produto_b
    tela = _Tela(itens=("10", "20", "30", "40"), centro_na_aba_itens=False, centro_padrao="")
    linha = _produto_b(_cliente(settings, tela))
    assert (linha.item, linha.material, linha.centro) == ("50", "10000002", "1002")
    assert tela.linhas[4][sc.COL_CENTRO] == "1002"


# ---------------------------------------------------------------- gravar

def test_grava_e_confirma_documento_incompleto(settings):
    tela = _Tela()
    cliente = _cliente(settings, tela)
    _produto_a(cliente)
    msg = cliente.gravar_cotacao("1234567")
    assert (msg.tipo, msg.id_mensagem, msg.numero_mensagem) == ("S", "V1", "311")
    assert tela.gravadas == 1


def test_outra_janela_ao_gravar_e_incerto(settings):
    tela = _Tela()
    tela.titulo_ao_gravar = "Determinação de preço"
    with pytest.raises(ResultadoIncerto, match="Determinação"):
        _cliente(settings, tela).gravar_cotacao("1234567")
    assert tela.gravadas == 0


def test_janela_aberta_antes_de_gravar_nao_grava(settings):
    tela = _Tela()
    tela.popup = "Informação"
    with pytest.raises(PopupInesperado):
        _cliente(settings, tela).gravar_cotacao("1234567")
    assert sc.BOTAO_GRAVAR not in tela.campos


def test_layout_da_gravacao_nao_precisa_mapear_a_tabela(settings):
    """Rapidez: com as colunas nas posições gravadas, nenhuma varredura completa da tabela."""
    tela = _Tela(itens=("10", "20", "30", "40"), centro_na_aba_itens=False, centro_padrao="")
    linha = _produto_b(_cliente(settings, tela))
    assert (linha.item, linha.material, linha.centro) == ("50", "10000002", "1002")
    assert tela.enumeracoes == 0
    assert tela.abas == [sc.ABA_ITENS_2]      # a VA22 já abre na Síntese: só a aba Venda é clicada
    assert tela.vkeys == [0]                  # só o Enter do centro (a troca de aba confirma a linha)


def test_layout_diferente_mapeia_uma_vez_por_tabela(settings):
    tela = _Tela(itens=("10",), centro_na_aba_itens=False, centro_padrao="")
    tela.colunas_01 = [sc.COL_ITEM, sc.COL_CENTRO, sc.COL_MATERIAL]       # centro fora da posição 7
    linha = _produto_b(_cliente(settings, tela))
    assert linha.centro == "1002" and tela.enumeracoes == 1


def test_celula_sem_edicao_vira_erro_claro_sem_gravar(settings):
    tela = _Tela(itens=("10", "20"), centro_na_aba_itens=False, centro_padrao="")
    tela.bloqueadas.add((2, sc.COL_CENTRO))          # a linha do item novo (30) não aceita centro
    with pytest.raises(ValorRejeitado, match="VBAP-WERKS da linha visível 2 não aceita edição"):
        _produto_b(_cliente(settings, tela))
    assert tela.gravadas == 0


def test_aviso_de_condicoes_de_pagamento_segundo_enter(settings):
    # Log de 26/10/2026: Enter na aba Venda -> W "Entrar Condições pagamento"
    tela = _Tela(itens=("10",), centro_na_aba_itens=False, centro_padrao="")
    tela.aviso_na_venda = 1
    linha = _produto_a(_cliente(settings, tela))
    assert linha.status.tipo == "W" and "Condições pagamento" in linha.status.texto   # o serviço decide
    assert (linha.item, linha.centro) == ("20", "1001")
    assert tela.vkeys.count(0) == 2          # Enter do centro + segundo Enter (a linha é confirmada pela troca de aba)


def test_avisos_diferentes_seguidos_param(settings):
    tela = _Tela(itens=("10",), centro_na_aba_itens=False, centro_padrao="")
    tela.aviso_na_venda = 1
    original = tela.tecla

    def tecla(t):
        original(t)
        if tela.vkeys.count(0) == 2:
            tela.barra.MessageType, tela.barra.Text = "W", "Data no passado"
    tela.tecla = tecla
    with pytest.raises(ValorRejeitado, match="Dois avisos"):
        _produto_a(_cliente(settings, tela))
