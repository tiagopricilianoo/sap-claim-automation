# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""REVISOR TESTADOR: sap_client (tabela, rolagem, janela ao gravar) e reaproveitamento da janela."""

import pytest

import sap_client as sc
from sap_gateway import ElementoNaoEncontrado, PopupInesperado, ResultadoIncerto
from test_sap_cotacao import _Barra, _Tela, _cliente as _cli_va22, _produto_a
from test_sap_client import _Conexao, _Sessao, _cliente


# ------------------------------------------------------------------ tabela de itens

def test_rev_tabela_sem_linhas_visiveis_para_sem_gravar(settings):
    tela = _Tela(itens=(), visiveis=0)
    with pytest.raises(ElementoNaoEncontrado):
        _produto_a(_cli_va22(settings, tela))
    assert tela.gravadas == 0


@pytest.mark.parametrize("n,visiveis", [(6, 6), (5, 6), (7, 6), (12, 6), (11, 6), (30, 4), (1, 1)])
def test_rev_rolagem_nas_bordas_da_pagina(settings, n, visiveis):
    itens = tuple(str(10 * i) for i in range(1, n + 1))
    tela = _Tela(itens=itens, visiveis=visiveis)
    linha = _produto_a(_cli_va22(settings, tela))
    assert linha.item == str(10 * (n + 1))
    assert tela.linhas[n][sc.COL_MATERIAL] == "10000001"           # escrita na linha absoluta certa
    assert [l[sc.COL_ITEM] for l in tela.linhas[:n]] == list(itens)  # nenhuma linha existente alterada


def test_rev_tabela_cheia_sem_linha_livre_para(settings):
    class _BarraCheia(_Barra):
        @property
        def Maximum(self):
            return max(0, len(self._t.linhas) - self._t.visiveis)

    tela = _Tela(itens=tuple(str(10 * i) for i in range(1, 13)), visiveis=6)
    import test_sap_cotacao as tsc
    original = tsc._Barra
    tsc._Barra = _BarraCheia
    try:
        with pytest.raises(ElementoNaoEncontrado, match="linha livre"):
            _produto_a(_cli_va22(settings, tela))
    finally:
        tsc._Barra = original
    assert tela.gravadas == 0 and len(tela.linhas) == 12


def test_rev_itens_fora_de_ordem_e_com_buraco(settings):
    tela = _Tela(itens=("10", "30", "20", "25"))
    assert _produto_a(_cli_va22(settings, tela)).item == "40"


# ------------------------------------------------------------------ janela inesperada ao gravar

def test_rev_janela_depois_de_confirmar_incompleto_e_incerta(settings):
    tela = _Tela()
    original = tela.apertou

    def apertou(id_):
        original(id_)
        if id_ == sc.GRAVAR_INCOMPLETO:
            tela.popup = "Informação"          # outra janela surge depois de gravar
    tela.apertou = apertou
    with pytest.raises(ResultadoIncerto):
        _cli_va22(settings, tela).gravar_cotacao("1234567")
    assert tela.gravadas == 1


def test_rev_janela_que_nao_fecha_nao_e_confirmada_em_laco(settings):
    """Lista de avisos (título igual ao da tela) que nunca fecha: no máximo N Enter, depois incerto."""
    tela = _Tela()
    tela.titulo_ao_gravar = "Modificar Cotação"
    tela.campos["wnd[0]"] = type("W", (), {"Text": "Modificar Cotação", "sendVKey": lambda s, t: None})()
    with pytest.raises(ResultadoIncerto):
        _cli_va22(settings, tela).gravar_cotacao("1234567")
    assert tela.gravadas == 0


def test_rev_queda_no_clique_de_gravar_e_incerta(settings):
    tela = _Tela()

    def apertou(id_):
        raise RuntimeError("RPC server unavailable")
    tela.apertou = apertou
    with pytest.raises(ResultadoIncerto):
        _cli_va22(settings, tela).gravar_cotacao("1234567")


def test_rev_popup_aberto_antes_de_gravar_nao_clica(settings):
    tela = _Tela()
    tela.popup = "Informação"
    with pytest.raises(PopupInesperado):
        _cli_va22(settings, tela).gravar_cotacao_nova()
    assert tela.gravadas == 0


# ------------------------------------------------------------------ reaproveitamento da janela

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


def test_rev_janela_mantida_com_popup_aberto_nao_e_reaproveitada(settings):
    conexao, c, janela = _mantida(settings)
    janela.popups.append("Deseja sair?")              # algo abriu uma janela modal nela
    segundo = _cliente(settings, conexao)
    segundo.reaproveitar = c.janela_mantida
    segundo.sessao()
    assert segundo._s is not janela


def test_rev_janela_do_usuario_com_o_mesmo_id_nao_e_usada_nem_fechada(settings):
    """O usuário fechou a janela mantida e abriu outra; o SAP GUI reaproveita o índice ses[n]."""
    conexao, c, janela = _mantida(settings)
    conexao.criadas.remove(janela)
    do_usuario = _Sessao(conexao)
    do_usuario.Id = janela.Id                          # mesmo /app/con[0]/ses[n]
    conexao.sessoes.append(do_usuario)
    segundo = _cliente(settings, conexao)
    segundo.reaproveitar = c.janela_mantida
    segundo.sessao()
    assert segundo._s is not do_usuario, "a automação passou a trabalhar na janela do usuário"
    assert _cliente(settings, conexao).fechar_por_id(janela.Id) is False, "fechou a janela do usuário"


def test_rev_janela_mantida_em_outro_mandante_nao_e_reaproveitada(settings):
    conexao, c, janela = _mantida(settings)
    janela.Info.Client = "200"
    segundo = _cliente(settings, conexao)
    segundo.reaproveitar = c.janela_mantida
    segundo.sessao()
    assert segundo._s is not janela


def test_rev_reaproveitar_id_inexistente_abre_nova(settings):
    conexao = _Conexao({})
    c = _cliente(settings, conexao)
    c.reaproveitar = "/app/con[0]/ses[99]"
    c.sessao()
    assert len(conexao.criadas) == 1
