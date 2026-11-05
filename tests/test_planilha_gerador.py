# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Planilha do Gerador copiada para Cotações\\Gerador ao criar as pastas (pedido de 04/11/2026)."""

import os
import time

from pastas import PlanoPastas, criar_pastas, planilha_gerador


def _arquivo(pasta, nome, idade=0):
    pasta.mkdir(parents=True, exist_ok=True)
    p = pasta / nome
    p.write_bytes(b"x")
    if idade:
        antigo = time.time() - idade
        os.utime(p, (antigo, antigo))
    return p


def test_nacional_pega_a_maior_versao(tmp_path):
    origem = tmp_path / "Oferta Brasil"
    _arquivo(origem, "PL_Padrão_(R9).xlsx")
    _arquivo(origem, "PL_Padrão_(R80).xlsx", idade=3600)        # mais velha, mas versão maior
    _arquivo(origem, "PL_Padrão_(R79).xlsm")
    _arquivo(origem, "~$PL_Padrão_(R99).xlsx")                    # temporário do Excel aberto
    _arquivo(origem, "Leia-me.txt")
    assert planilha_gerador(origem).name == "PL_Padrão_(R80).xlsx"


def test_exportacao_pega_o_unico_excel(tmp_path):
    origem = tmp_path / "Gerador"
    _arquivo(origem, "Custo Gerador Exportação.xlsm")
    assert planilha_gerador(origem).name == "Custo Gerador Exportação.xlsm"


def test_pasta_vazia_ou_inexistente_nao_quebra(tmp_path):
    assert planilha_gerador(tmp_path / "nao_existe") is None
    (tmp_path / "vazia").mkdir()
    assert planilha_gerador(tmp_path / "vazia") is None


def _plano(tmp_path, modelo, origem):
    base = tmp_path / "proj" / "R.0"
    return PlanoPastas(modelo, base, tmp_path / "proj" / "R.X", tmp_path / "TU", tmp_path / "TR", 2026, origem)


def test_criar_pastas_copia_para_cotacoes_gerador(tmp_path):
    origem = tmp_path / "Oferta Brasil"
    _arquivo(origem, "PL_Padrão_(R80).xlsx")
    base = criar_pastas(_plano(tmp_path, "TU", origem), "21800001", criar_atalho=lambda *a: None)
    assert (base / "Cotações" / "Gerador" / "PL_Padrão_(R80).xlsx").exists()
    assert not (base.parent / "R.X" / "Cotações" / "Gerador" / "PL_Padrão_(R80).xlsx").exists()   # só na R.0


def test_sem_origem_configurada_nao_copia(tmp_path):
    base = criar_pastas(_plano(tmp_path, "TR", None), "21800001", criar_atalho=lambda *a: None)
    assert list((base / "Cotações" / "Gerador").iterdir()) == []


def test_planejar_escolhe_a_origem_pelo_tipo(settings, tmp_path):
    from dataclasses import replace
    from cotacao import CotacaoRequest
    from pastas import planejar_pastas
    tu, tr = tmp_path / "TU", tmp_path / "TR"
    tu.mkdir()
    tr.mkdir()
    cfg = replace(settings.cotacao, raiz_produto_a=str(tu), raiz_produto_b=str(tr),
                  gerador_nacional=str(tmp_path / "BR"), gerador_exportacao=str(tmp_path / "EXP"))
    nao = lambda *_: False
    nac = planejar_pastas(CotacaoRequest.from_form(tipo="Nacional", regiao="Sul", cliente="A", projeto="P",
                                                   produto_a=True), cfg, nao, ano=2026)
    exp = planejar_pastas(CotacaoRequest.from_form(tipo="Exportação", regiao="Europa", pais="Alemanha",
                                                   cliente="B", projeto="P", produto_a=True), cfg, nao, ano=2026)
    especial = planejar_pastas(CotacaoRequest.from_form(tipo="Cliente Especial", projeto="K-1", produto_a=True), cfg, nao,
                            ano=2026)
    assert (nac.origem_gerador, exp.origem_gerador, especial.origem_gerador) == (tmp_path / "BR", tmp_path / "EXP", None)
