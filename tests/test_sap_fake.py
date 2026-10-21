# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
from pathlib import Path

import pytest

from sap_fake import FakeSap
from sap_gateway import ElementoNaoEncontrado, ResultadoIncerto, SapGateway, SessaoIndisponivel


def test_implementa_o_contrato():
    contrato = {n for n in dir(SapGateway) if not n.startswith("_")}
    assert contrato <= set(dir(FakeSap))


def test_fluxo_simulado_completo():
    sap = FakeSap(popups_apos_enter=["O cliente CLIENTE X tem bloqueio de registro"])
    assert sap.sessao().sistema == "PRD"
    sap.abrir_criacao("Z1")
    sap.preencher_nota(descricao="d", texto_livre="t", causa_grupo="01", causa_codigo="0001",
                       prioridade="1", ordem="1", item="10")
    sap.enter()
    assert "bloqueio de registro" in sap.popup_aberto().texto
    sap.confirmar_popup()
    assert sap.popup_aberto() is None

    doc = sap.criar_documento(tipo="ZDC", descricao="a.pdf", laboratorio="L01",
                              arquivo=Path("a.pdf"), aplicacao="PDF")
    status = sap.gravar_nota()
    assert status.tipo == "S" and status.parametros == ("100063949",)
    assert sap.nota_existe("100063949")
    assert sap.gravacoes == [f"DOCUMENTO ZDC {doc}", "NOTA 100063949"]


def test_sem_sap_aberto():
    with pytest.raises(SessaoIndisponivel):
        FakeSap(sessao_info=None).sessao()


def test_falha_injetada_antes_de_gravar():
    sap = FakeSap(falhar_em={"criar_documento": ElementoNaoEncontrado("btnY1", etapa="criar_documento")})
    with pytest.raises(ElementoNaoEncontrado) as erro:
        sap.criar_documento(tipo="ZDC", descricao="a", laboratorio="L01", arquivo=Path("a"), aplicacao="PDF")
    assert erro.value.etapa == "criar_documento"
    assert sap.gravacoes == []


def test_resultado_incerto_na_gravacao():
    sap = FakeSap(falhar_em={"gravar_nota": ResultadoIncerto("conexão caiu")})
    with pytest.raises(ResultadoIncerto):
        sap.gravar_nota()
