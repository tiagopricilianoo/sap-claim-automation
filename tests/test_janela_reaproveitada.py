# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Reaproveitamento da janela da automação entre claims (economia de ~2-3 s por claim)."""

from test_sap_client import _Conexao, _cliente

import sap_client as sc


def _primeiro_claim(settings):
    conexao = _Conexao({})
    cliente = _cliente(settings, conexao)
    cliente.manter_janela = True
    cliente.sessao()
    janela = conexao.criadas[0]
    janela.Info.Transaction = "CLM1"            # a execução trabalhou na CLM1
    janela.ao_vkey[0] = lambda: setattr(janela.Info, "Transaction", "SESSION_MANAGER")   # "/n" volta ao menu
    cliente.encerrar()
    return conexao, cliente, janela


def test_sucesso_mantem_a_janela_no_menu(settings):
    conexao, cliente, janela = _primeiro_claim(settings)
    assert cliente.janela_mantida == janela.Id
    assert janela.campo(sc.OKCODE).text == "/n"
    assert conexao.fechadas == []


def test_proximo_claim_reaproveita_sem_abrir_outra(settings):
    conexao, cliente, janela = _primeiro_claim(settings)
    segundo = _cliente(settings, conexao)
    segundo.reaproveitar = cliente.janela_mantida
    segundo.sessao()
    assert len(conexao.criadas) == 1 and segundo._s is janela


def test_janela_usada_pelo_usuario_nao_e_reaproveitada(settings):
    conexao, cliente, janela = _primeiro_claim(settings)
    janela.Info.Transaction = "VA02"            # o usuário abriu algo nela
    segundo = _cliente(settings, conexao)
    segundo.reaproveitar = cliente.janela_mantida
    segundo.sessao()
    assert len(conexao.criadas) == 2 and segundo._s is not janela


def test_janela_ocupada_nao_e_reaproveitada(settings):
    conexao, cliente, janela = _primeiro_claim(settings)
    janela.Busy = True
    segundo = _cliente(settings, conexao)
    segundo.reaproveitar = cliente.janela_mantida
    segundo.sessao()
    assert len(conexao.criadas) == 2


def test_sem_manter_fecha_como_antes(settings):
    conexao = _Conexao({})
    cliente = _cliente(settings, conexao)
    cliente.sessao()
    cliente.encerrar()
    assert conexao.fechadas == [conexao.criadas[0].Id] and cliente.janela_mantida is None


def test_janela_que_nao_volta_ao_menu_e_fechada(settings):
    conexao = _Conexao({})
    cliente = _cliente(settings, conexao)
    cliente.manter_janela = True
    cliente.sessao()
    conexao.criadas[0].Info.Transaction = "CLM1"      # "/n" não surtiu efeito
    cliente.encerrar()
    assert cliente.janela_mantida is None and conexao.fechadas == [conexao.criadas[0].Id]


def test_ao_fechar_o_programa_fecha_so_se_estiver_no_menu(settings):
    conexao, cliente, janela = _primeiro_claim(settings)
    janela.Info.Transaction = "VA02"
    assert _cliente(settings, conexao).fechar_por_id(janela.Id) is False
    janela.Info.Transaction = "SESSION_MANAGER"
    assert _cliente(settings, conexao).fechar_por_id(janela.Id) is True
    assert conexao.fechadas == [janela.Id]
