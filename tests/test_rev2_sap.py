# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""REVISOR 4 (TESTADOR), RODADA 2: avisos ao gravar (correção 9) e janela reaproveitada (correção 14)."""

import pytest

import sap_client as sc
from sap_gateway import ResultadoIncerto, ValorRejeitado
from test_sap_client import _Conexao, _Sessao, _cliente
from test_sap_cotacao import _Tela, _cliente as _cli_va22


class _Texto:
    def __init__(self, t):
        self.Text = t


class _Area:
    def __init__(self, textos):
        self._t = [_Texto(t) for t in textos]

    class _C:
        def __init__(self, itens):
            self._i = itens

        @property
        def Count(self):
            return len(self._i)

        def __call__(self, i):
            return self._i[i]

    @property
    def Children(self):
        return self._C(self._t)


def _tela_com_lista_de_avisos(conteudo):
    """Ao gravar, o SAP mostra a 'lista de avisos' com o título da própria tela; Enter grava."""
    tela = _Tela()
    titulo = "Modificar Cotação 1234567: Síntese"

    class _Wnd0:
        Text = titulo
    tela.campos["wnd[0]"] = _Wnd0()

    class _Lista:
        Text = titulo

        def findById(self, id_):
            return _Area(conteudo)

        def sendVKey(self, tecla):
            tela.popup = ""
            tela.gravadas += 1
            tela.barra.MessageType, tela.barra.Text = "S", "Cotação 1234567 foi gravado(a)"
            tela.barra.MessageId, tela.barra.MessageNumber = "V1", "311"

    original = tela.findById

    def findById(id_):
        if id_ == sc.POPUP and tela.popup == titulo:
            return _Lista()
        return original(id_)
    tela.findById = findById
    tela.titulo_ao_gravar = titulo
    return tela


# DECISÃO PENDENTE DO DONO DO PRODUTO (2ª banca, 27/10/2026): não coletado de propósito (prefixo
# "pendente_"). Hoje a lista de avisos ao gravar recebe Enter como no programa de cotação anterior, com
# o conteúdo registrado no histórico. Exigir [avisos_aceitos] aqui precisa dos textos reais (975, 8710…).
def pendente_rev2_lista_de_avisos_desconhecida_ao_gravar_nao_e_confirmada(settings):
    """A lista de avisos é confirmada com Enter sem passar por [avisos_aceitos]: qualquer conteúdo grava."""
    tela = _tela_com_lista_de_avisos(["Cliente 4711 bloqueado para vendas", "Crédito excedido"])
    cliente = _cli_va22(settings, tela)
    with pytest.raises(ResultadoIncerto):
        cliente.gravar_cotacao("1234567")
    assert tela.gravadas == 0, f"gravou com aviso desconhecido; registrado só: {cliente.avisos_gravacao}"


# DECISÃO PENDENTE DO DONO DO PRODUTO (2ª banca, 27/10/2026): não coletado de propósito (prefixo
# "pendente_"). Hoje a lista de avisos ao gravar recebe Enter como no programa de cotação anterior, com
# o conteúdo registrado no histórico. Exigir [avisos_aceitos] aqui precisa dos textos reais (975, 8710…).
def pendente_rev2_lista_de_avisos_ilegivel_nao_e_confirmada(settings):
    tela = _tela_com_lista_de_avisos([])
    cliente = _cli_va22(settings, tela)
    with pytest.raises(ResultadoIncerto):
        cliente.gravar_cotacao("1234567")
    assert tela.gravadas == 0


def test_rev2_aviso_w_desconhecido_ao_gravar_e_incerto(settings):
    tela = _Tela()
    original = tela.apertou

    def apertou(id_):
        if id_ == sc.BOTAO_GRAVAR:
            tela.barra.MessageType, tela.barra.Text = "W", "Preço líquido abaixo do mínimo"
            return
        original(id_)
    tela.apertou = apertou
    with pytest.raises(ResultadoIncerto, match="não previsto"):
        _cli_va22(settings, tela).gravar_cotacao("1234567")
    assert 0 not in tela.vkeys


def test_rev2_aviso_w_aceito_com_texto_maior_nao_casa(settings):
    """'Entrar Condições pagamento' é aceito; 'Entrar Condições pagamento: cliente bloqueado' não pode ser."""
    tela = _Tela()
    original = tela.apertou

    def apertou(id_):
        if id_ == sc.BOTAO_GRAVAR:
            tela.barra.MessageType, tela.barra.Text = "W", "Entrar Condições pagamento: cliente bloqueado"
            return
        original(id_)
    tela.apertou = apertou
    with pytest.raises(ResultadoIncerto):
        _cli_va22(settings, tela).gravar_cotacao("1234567")


def test_rev2_padrao_com_asterisco_no_fim_aceita_qualquer_complemento(settings):
    """[avisos_aceitos] endereco_exportacao termina em '*': aceita 'Endereço ... da ordem BLOQUEADO'."""
    from claim_service import ClaimService
    svc = ClaimService(settings, None, None)
    assert not svc._aceito("Endereço de dds.mestre para o Emissor da ordem bloqueado para vendas")


# ------------------------------------------------------------------ janela reaproveitada (correção 14)

def _mantida(settings):
    conexao = _Conexao({})
    c = _cliente(settings, conexao)
    c.manter_janela = True
    c.sessao()
    janela = conexao.criadas[0]
    janela.Info.Transaction = "CLM1"
    janela.ao_vkey[0] = lambda: setattr(janela.Info, "Transaction", "SESSION_MANAGER")
    c.encerrar()
    return conexao, c, janela


# RISCO ACEITO (2ª banca): o SAP só reusa o Id se a janela da automação for fechada; a do usuário
# precisaria estar minimizada, no menu, sem nada aberto. Não coletado (prefixo "pendente_").
def pendente_rev2_janela_do_usuario_minimizada_com_o_mesmo_id_e_usada(settings):
    """O critério novo é 'minimizada e sem popup'. A janela do usuário que reaproveitou o Id e foi
    minimizada por ele no menu é tomada pela automação."""
    conexao, c, janela = _mantida(settings)
    conexao.criadas.remove(janela)
    do_usuario = _Sessao(conexao)
    do_usuario.Id = janela.Id
    conexao.sessoes.append(do_usuario)
    do_usuario.minimizada = True                      # o usuário minimizou a SUA janela
    segundo = _cliente(settings, conexao)
    segundo.reaproveitar = c.janela_mantida
    segundo.sessao()
    assert segundo._s is not do_usuario, "a automação passou a trabalhar na janela minimizada do usuário"


def test_rev2_aviso_novo_depois_do_enter_da_linha_nao_some(settings):
    """Veredito 2, item 3: W1 na troca de aba (aceito) -> Enter -> W2 diferente: tem que parar sem gravar."""
    import test_sap_cotacao as tsc
    from sap_gateway import ValorRejeitado
    tela = tsc._Tela(itens=("10",), centro_na_aba_itens=False, centro_padrao="")
    feito = {"aba": False}
    orig_select = tsc._Generico.select

    def select(self):
        orig_select(self)
        if self._id == sc.ABA_ITENS_2 and not feito["aba"]:
            feito["aba"] = True
            self._t.barra.MessageType, self._t.barra.Text = "W", "Entrar Condições pagamento"
    orig_tecla = tela.tecla

    def tecla(k):
        orig_tecla(k)
        if tela.vkeys.count(0) == 1:
            tela.barra.MessageType, tela.barra.Text = "W", "Cliente 4711 bloqueado para vendas"
    tela.tecla = tecla
    tsc._Generico.select = select
    try:
        with pytest.raises(ValorRejeitado, match="Dois avisos"):
            tsc._produto_a(tsc._cliente(settings, tela))
    finally:
        tsc._Generico.select = orig_select
    assert tela.gravadas == 0
