# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""REVISOR 4 (TESTADOR), RODADA 2: regras da tela (correções 2, 4, 6, 10), com a tela substituída por stubs.

Precisa de REV_STUBS (customtkinter/tkinter falsos). Sem eles, os testes deste arquivo não rodam.
"""

import os
import sys
from types import SimpleNamespace

_STUBS = os.environ.get("REV_STUBS", "")
if _STUBS and _STUBS not in sys.path:
    sys.path.insert(0, _STUBS)

import ui  # noqa: E402
import ui_cotacao  # noqa: E402


class _Caixa:
    """messagebox falso: registra as chamadas e responde o que o teste mandar."""

    def __init__(self, resposta=True):
        self.chamadas, self.resposta = [], resposta

    def __getattr__(self, nome):
        def f(*a, **k):
            self.chamadas.append((nome, a))
            return self.resposta
        return f


def _com_caixa(modulo, caixa):
    antigo = modulo.messagebox
    modulo.messagebox = caixa
    return antigo


class _Exec:
    def __init__(self, ocupado):
        self.ocupado = ocupado
        self.fechou_mantida = False
        self.janela_mantida = "/app/con[0]/ses[2]"

    def fechar_janela_mantida(self):
        self.fechou_mantida = True

    def interromper(self):
        pass


def test_rev2_resolver_claim_recusa_com_execucao_rodando():
    caixa = _Caixa()
    antigo = _com_caixa(ui, caixa)
    try:
        chamado = []
        fake = SimpleNamespace(executor=_Exec(True), tabela_pend=SimpleNamespace(selection=lambda: chamado.append(1)))
        ui.App._resolver(fake, False)
    finally:
        ui.messagebox = antigo
    assert chamado == [] and caixa.chamadas and caixa.chamadas[0][0] == "showinfo"


def test_rev2_resolver_cotacao_recusa_com_execucao_rodando():
    caixa = _Caixa()
    antigo = _com_caixa(ui_cotacao, caixa)
    try:
        chamado = []
        fake = SimpleNamespace(app=SimpleNamespace(executor=_Exec(True)), _selecionada=lambda: chamado.append(1))
        ui_cotacao.AbaCotacao._resolver(fake, True)
    finally:
        ui_cotacao.messagebox = antigo
    assert chamado == []


def test_rev2_preparar_claim_recusa_com_execucao_rodando():
    caixa = _Caixa()
    antigo = _com_caixa(ui, caixa)
    try:
        limpou = []
        fake = SimpleNamespace(executor=_Exec(True), _limpar_conteudo_claim=lambda: limpou.append(1))
        ui.App.preparar_claim(fake, "1234567", "20", "PRODUTO_A")
    finally:
        ui.messagebox = antigo
    assert limpou == []


def test_rev2_preparar_claim_com_dados_e_resposta_nao_preserva():
    caixa = _Caixa(resposta=False)
    antigo = _com_caixa(ui, caixa)
    try:
        limpou = []
        fake = SimpleNamespace(executor=_Exec(False), _limpar_conteudo_claim=lambda: limpou.append(1),
                               descricao=SimpleNamespace(get=lambda: "claim do item 10"),
                               texto=SimpleNamespace(get=lambda *a: ""), arquivo="",
                               sem_anexo=SimpleNamespace(get=lambda: False))
        ui.App.preparar_claim(fake, "1234567", "20", "PRODUTO_A")
    finally:
        ui.messagebox = antigo
    assert limpou == [] and caixa.chamadas[0][0] == "askyesno"


def test_rev2_fechar_depois_de_esperar_a_execucao_fecha_a_janela_mantida():
    """Fechar com execução rodando: a janela espera a thread e depois chama destroy() direto, sem
    fechar_janela_mantida(). A janela da automação fica aberta no SAP (minimizada, no menu)."""
    ex = _Exec(False)
    destruida = []
    fake = SimpleNamespace(executor=ex, destroy=lambda: destruida.append(1), after=lambda *a: None,
                           _espera_fechar=30, _ultimo_fim=None, _ocupado_para_fechar=lambda: False)
    fake._encerrar = lambda: ui.App._encerrar(fake)
    ui.App._fechar_quando_livre(fake)
    assert destruida and ex.fechou_mantida, "janela mantida da automação não foi fechada"


def test_rev2_confirmar_linha_extra_reexecuta_com_a_marca():
    from dataclasses import replace  # noqa: F401
    from claim_service import Resultado
    from models import ClaimRequest
    from state import Estado
    caixa = _Caixa(resposta=True)
    antigo = _com_caixa(ui, caixa)
    comecou = []
    req = ClaimRequest.from_form(tipo="PRODUTO_A", descricao="d", texto_livre="t", ordem="1", item="",
                                 arquivo="", sem_anexo=True, linha_nova=True)
    nulo = SimpleNamespace(configure=lambda *a, **k: None, delete=lambda *a: None, insert=lambda *a: None)
    fake = SimpleNamespace(
        _ultimo_pedido=(req, "AUTOMATICO"), _comecar=lambda r, m: comecou.append((r, m)),
        _mostrar_resultado_texto=lambda *a: None, detalhes=nulo, msg_resultado=nulo,
        _modo_escolhido=lambda: "AUTOMATICO", bell=lambda: None, _fechando=False)
    try:
        ui.App._mostrar_resultado(fake, Resultado("X", Estado.RECEBIDO, "linha recente", confirmar="linha_extra"))
    finally:
        ui.messagebox = antigo
    assert comecou and comecou[0][0].confirmar_linha_extra is True and comecou[0][0].linha_nova
