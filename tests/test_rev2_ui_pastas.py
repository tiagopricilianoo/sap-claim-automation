# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Revisão de 27/10/2026 (2ª banca): 'Criar cotação' em produção passa pela conferência de pastas em
segundo plano. Esse caminho não roda em simulação/ensaio, então precisa de teste próprio."""

import os
import sys
from dataclasses import replace

import pytest


def _app(settings, tmp_path):
    stubs = os.environ.get("REV_STUBS", "")
    if not stubs:
        pytest.skip("sem stubs de tela (REV_STUBS)")
    if stubs not in sys.path:
        sys.path.insert(0, stubs)
    import ui
    cfg = replace(settings, modo="AUTOMATICO", automatico_habilitado=True)
    return ui.App(cfg)


def test_rev2_em_segundo_plano_recusa_objeto_sem_after():
    import tema_ui
    rodou = []
    with pytest.raises(TypeError):
        tema_ui.EmSegundoPlano(object(), lambda p: rodou.append(1), lambda r: None, lambda e: None)
    assert rodou == []                       # a thread nem começou


def test_rev2_criar_cotacao_em_producao_inicia_conferencia_de_pastas(settings, tmp_path):
    from cotacao import CotacaoRequest
    app = _app(settings, tmp_path)
    aba = app.aba_cotacao
    if aba is None:
        pytest.skip("cotação desligada no settings de teste")
    aba._atualizar = lambda: []
    aba._request = lambda: CotacaoRequest.from_form(tipo="Nacional", regiao="Sul", cliente="Usina",
                                                    projeto="P1", produto_a=True)
    aba._modo = lambda: "AUTOMATICO"
    aba._criar()                              # antes da correção: AttributeError ('AbaCotacao' sem .after)


def test_rev2_segunda_janela_do_programa_e_recusada(tmp_path):
    from tema_ui import InstanciaUnica
    a, b = InstanciaUnica(tmp_path), InstanciaUnica(tmp_path)
    assert a.adquirir()
    assert not b.adquirir()                   # 2ª janela: recusada
    a.liberar()
    assert b.adquirir()                       # depois de fechar a 1ª, abre normalmente
    b.liberar()
