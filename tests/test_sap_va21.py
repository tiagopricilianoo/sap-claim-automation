# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Cotação nova na VA21 com a tela simulada da lista de itens (sem SAP, sem Windows).

IDs e sequência do programa "Criar Cotação" (em produção até out/2026), com o centro
digitado na aba Venda também para a Produto A (decisão de 26/10/2026).
"""

import pytest

import sap_client as sc
from sap_gateway import ElementoNaoEncontrado, ResultadoIncerto, ValorRejeitado
from test_sap_cotacao import _Tela, _cliente


class _TelaVA21(_Tela):
    def __init__(self, **kw):
        super().__init__(itens=(), centro_na_aba_itens=False, centro_padrao="", **kw)
        self.sem_emissor = False

    def findById(self, id_):
        if id_ == sc.VA21_EMISSOR and self.sem_emissor:
            raise RuntimeError("The control could not be found by id.")
        return super().findById(id_)

    def tecla(self, tecla):
        emissor = self.campos.get(sc.VA21_EMISSOR)
        abrir_endereco = tecla == 0 and emissor is not None and emissor.text and not getattr(self, "_endereco", False)
        super().tecla(tecla)
        if abrir_endereco:
            self._endereco = True
            self.popup = "Endereço"
        proximo = 10
        for l in self.linhas:                    # o SAP numera as linhas com material
            if l.get(sc.COL_MATERIAL) and not l.get(sc.COL_ITEM):
                l[sc.COL_ITEM] = str(proximo)
            if l.get(sc.COL_ITEM):
                proximo = int(l[sc.COL_ITEM]) + 10

    def apertou(self, id_):
        if id_ == sc.END_OK:
            self.popup = ""
            return
        super().apertou(id_)


def _criar(cliente, linhas=(("10000001", "1001", "1"), ("10000002", "1002", "1"))):
    cliente.iniciar_cotacao(tipo_documento="ZQT1", organizacao="1000", canal="30", setor="20",
                            escritorio="X001", equipe="E10")
    janela = cliente.preencher_cliente(emissor="CLIENTE X", titulo="0008", nome="Usina Boa Vista",
                                       cidade="Cogeração 2026", codigo_postal="")
    cliente.preencher_validade(validade="26.10.2027", referencia="Usina Boa Vista - Cogeração 2026")
    lidas = cliente.preencher_linhas_novas(list(linhas))
    cliente.preencher_cabecalho(utilizacao="003", data="26.10.2026", hora="12:00:00")
    return janela, lidas


def test_va21_completa_com_duas_linhas(settings):
    tela = _TelaVA21()
    cliente = _cliente(settings, tela)
    janela, lidas = _criar(cliente)
    assert janela is None
    assert tela.campos[sc.OKCODE].text == "/nVA21"
    valores = {k: tela.campos[k].text for k in (sc.VA21_TIPO, sc.VA21_ORGANIZDCAO, sc.VA21_CANAL, sc.VA21_SETOR,
                                                sc.VA21_ESCRITORIO, sc.VA21_EQUIPE)}
    assert list(valores.values()) == ["ZQT1", "1000", "30", "20", "X001", "E10"]
    assert tela.campos[sc.END_TITULO].key == "0008" and tela.campos[sc.END_NOME].text == "Usina Boa Vista"
    assert tela.campos[sc.VA21_VALIDADE].text == "26.10.2027"
    assert tela.campos[sc.VA21_REFERENCIA].text == "Usina Boa Vista - Cogeração 2026"
    assert [(l.item, l.material, l.centro) for l in lidas] == [("10", "10000001", "1001"), ("20", "10000002", "1002")]
    assert tela.campos[sc.VA21_UTILIZDCAO].key == "003"
    assert tela.campos[sc.VA21_HORA_RECEBIMENTO].text == "12:00:00"
    assert tela.gravadas == 0                    # nada gravado até aqui


def test_grava_cotacao_nova(settings):
    tela = _TelaVA21()
    tela.resposta_gravar = ("S", "Cotação 21800001 foi gravado(a)", "V1", "311")
    cliente = _cliente(settings, tela)
    _criar(cliente, linhas=(("10000002", "1002", "1"),))
    msg = cliente.gravar_cotacao_nova()
    assert msg.texto == "Cotação 21800001 foi gravado(a)" and tela.gravadas == 1


def test_aviso_ao_gravar_segue_com_enter_como_o_programa_anterior(settings):
    tela = _TelaVA21()
    cliente = _cliente(settings, tela)
    _criar(cliente)
    original = tela.apertou

    def apertou(id_):
        if id_ == sc.BOTAO_GRAVAR:      # primeiro um aviso; a janela vem depois do Enter
            tela.barra.MessageType, tela.barra.Text = "W", "Entrar Condições pagamento"
            tela.depois_do_enter = "Gravar documento incompleto"
            return
        original(id_)
    tela.apertou = apertou
    tecla_original = tela.tecla

    def tecla(t):
        tecla_original(t)
        if getattr(tela, "depois_do_enter", ""):
            tela.popup, tela.depois_do_enter = tela.depois_do_enter, ""
    tela.tecla = tecla
    cliente.gravar_cotacao_nova()
    assert tela.gravadas == 1


def test_sem_acesso_ao_emissor_para_sem_gravar(settings):
    tela = _TelaVA21()
    tela.sem_emissor = True
    with pytest.raises(ElementoNaoEncontrado, match="não ter acesso"):
        _cliente(settings, tela).iniciar_cotacao(tipo_documento="ZQT1", organizacao="1000", canal="30",
                                                 setor="20", escritorio="X001", equipe="E10")


def test_janela_de_endereco_que_nao_abre(settings):
    tela = _TelaVA21()
    tela._endereco = True                    # o Enter não abre a janela
    cliente = _cliente(settings, tela)
    with pytest.raises(ElementoNaoEncontrado, match="endereço"):
        cliente.preencher_cliente(emissor="CLIENTE X", titulo="0008", nome="x", cidade="y", codigo_postal="")


def test_erro_na_linha_para_sem_gravar(settings):
    tela = _TelaVA21()
    cliente = _cliente(settings, tela)
    cliente.iniciar_cotacao(tipo_documento="ZQT1", organizacao="1000", canal="30", setor="20",
                            escritorio="X001", equipe="E10")
    tela.erro_no_enter = "Material 10000009 não existe"
    with pytest.raises(ValorRejeitado):
        cliente.preencher_linhas_novas([("10000009", "1001", "1")])
    assert tela.gravadas == 0


def test_gravar_cotacao_nova_com_janela_estranha_e_incerto(settings):
    tela = _TelaVA21()
    tela.titulo_ao_gravar = "Saldo de crédito"
    cliente = _cliente(settings, tela)
    with pytest.raises(ResultadoIncerto):
        cliente.gravar_cotacao_nova()


def test_lista_de_avisos_ao_gravar_segue_com_enter(settings):
    # Print de 26/10/2026: depois do Ctrl+S, lista "criar Cotação: dados cabeçalho" (975, 8710);
    # depois do Enter, "Gravar documento incompleto".
    tela = _TelaVA21()
    tela.findById("wnd[0]").Text = "criar Cotação: dados cabeçalho"
    tela.titulo_ao_gravar = "criar Cotação: dados cabeçalho"
    tecla_original = tela.tecla

    class _Lista:
        Text = "criar Cotação: dados cabeçalho"

        def sendVKey(self, t):
            tela.popup = "Gravar documento incompleto"
    original_find = tela.findById
    tela.findById = lambda id_: _Lista() if id_ == sc.POPUP and tela.popup == _Lista.Text else original_find(id_)
    cliente = _cliente(settings, tela)
    cliente.gravar_cotacao_nova()
    assert tela.gravadas == 1


def test_janela_desconhecida_ao_gravar_continua_incerta(settings):
    tela = _TelaVA21()
    tela.findById("wnd[0]").Text = "criar Cotação: dados cabeçalho"
    tela.titulo_ao_gravar = "Bloqueio de crédito"
    with pytest.raises(ResultadoIncerto, match="Bloqueio"):
        _cliente(settings, tela).gravar_cotacao_nova()
    assert tela.gravadas == 0


def test_aviso_desconhecido_ao_gravar_nao_e_confirmado(settings):
    tela = _TelaVA21()
    cliente = _cliente(settings, tela)
    original = tela.apertou

    def apertou(id_):
        if id_ == sc.BOTAO_GRAVAR:
            tela.barra.MessageType, tela.barra.Text = "W", "Preço não encontrado para o item 10"
            return
        original(id_)
    tela.apertou = apertou
    with pytest.raises(ResultadoIncerto, match="Preço não encontrado"):
        cliente.gravar_cotacao_nova()
    assert tela.gravadas == 0 and 0 not in tela.vkeys
