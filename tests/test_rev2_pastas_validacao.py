# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""REVISOR 4 (TESTADOR), RODADA 2: pastas (Especial, clientes parecidos, raízes TU/TR) e validações Unicode."""

import unicodedata
from dataclasses import replace

import pytest

from cotacao import CotacaoRequest, validar_cotacao
from models import ClaimRequest
from pastas import ProjetoJaExiste, corpo_email, planejar_pastas
from validators import validate


def _rede(settings, raiz):
    tu, tr = raiz / "TU", raiz / "TR"
    tu.mkdir(parents=True, exist_ok=True)
    tr.mkdir(parents=True, exist_ok=True)
    return replace(settings.cotacao, raiz_produto_a=str(tu), raiz_produto_b=str(tr))


def _creq(**kw):
    base = dict(tipo="Nacional", regiao="Sul", cliente="Usina Boa Vista", projeto="Cogeração 2026",
                produto_a=True, produto_b=False)
    base.update(kw)
    return CotacaoRequest.from_form(**base)


def _sul(raiz, rede="TU"):
    pasta = "Propostas_2026" if rede == "TU" else "Propostas - 2026"
    return raiz / rede / pasta / "Brasil" / "Sul"


def _especial(raiz, rede="TU"):
    pasta = "Propostas_2026" if rede == "TU" else "Propostas - 2026"
    return raiz / rede / pasta / "Exportação" / "Europa" / "Cliente Especial"


NAO = lambda *a: False      # noqa: E731
SIM = lambda *a: True       # noqa: E731


# ------------------------------------------------------------------ Especial (correção 5)

@pytest.mark.parametrize("nome_no_disco", ["K-77", "k-77", "k-77 "])
def test_rev2_especial_projeto_existente_com_caixa_diferente_para(settings, tmp_path, nome_no_disco):
    cfg = _rede(settings, tmp_path)
    (_especial(tmp_path) / nome_no_disco.strip()).mkdir(parents=True)
    req = CotacaoRequest.from_form(tipo="Cliente Especial", projeto="K-77", produto_a=True)
    with pytest.raises(ProjetoJaExiste):
        planejar_pastas(req, cfg, perguntar=NAO, ano=2026)


def test_rev2_especial_projeto_decomposto_no_disco_para(settings, tmp_path):
    cfg = _rede(settings, tmp_path)
    (_especial(tmp_path) / unicodedata.normalize("NFD", "Ação 7")).mkdir(parents=True)
    req = CotacaoRequest.from_form(tipo="Cliente Especial", projeto="Ação 7", produto_a=True)
    with pytest.raises(ProjetoJaExiste):
        planejar_pastas(req, cfg, perguntar=NAO, ano=2026)


def test_rev2_especial_projeto_existente_na_rede_do_produto_b_nao_e_visto(settings, tmp_path):
    """Especial 'K-77' criada como Produto B (rede TR). Outra cotação K-77 com Produto A olha só a rede TU."""
    cfg = _rede(settings, tmp_path)
    (_especial(tmp_path, "TR") / "K-77" / "R.0").mkdir(parents=True)
    req = CotacaoRequest.from_form(tipo="Cliente Especial", projeto="K-77", produto_a=True, produto_b=True)
    with pytest.raises(ProjetoJaExiste):
        planejar_pastas(req, cfg, perguntar=NAO, ano=2026)


def test_rev2_projeto_existente_na_outra_rede_nao_e_visto(settings, tmp_path):
    """Mesmo cliente/projeto já cotado só com Produto B (pasta na rede TR); agora Produto A+Produto B (rede TU):
    nenhuma checagem entre usuários. O histórico local (chave sem equipamento) bloquearia: as duas regras
    discordam."""
    cfg = _rede(settings, tmp_path)
    (_sul(tmp_path, "TR") / "Usina Boa Vista" / "Cogeração 2026" / "R.0").mkdir(parents=True)
    with pytest.raises(ProjetoJaExiste):
        planejar_pastas(_creq(produto_b=True), cfg, perguntar=NAO, ano=2026)


# ------------------------------------------------------------------ clientes parecidos (correção 11)

def test_rev2_cliente_exato_existe_e_projeto_esta_no_parecido(settings, tmp_path):
    """'Usina Boa Vista' existe (vazia) E 'Usina Boa Vista S.A' já tem o projeto: a checagem em todos os
    parecidos só roda quando o exato NÃO existe."""
    cfg = _rede(settings, tmp_path)
    (_sul(tmp_path) / "Usina Boa Vista").mkdir(parents=True)
    (_sul(tmp_path) / "Usina Boa Vista S.A" / "Cogeração 2026").mkdir(parents=True)
    with pytest.raises(ProjetoJaExiste):
        planejar_pastas(_creq(), cfg, perguntar=NAO, ano=2026)


def test_rev2_projeto_no_segundo_parecido_para_mesmo_respondendo_nao(settings, tmp_path):
    cfg = _rede(settings, tmp_path)
    (_sul(tmp_path) / "Usina Boa Vista Ltda").mkdir(parents=True)
    (_sul(tmp_path) / "Usina Boa Vista S.A" / "COGERAÇÃO 2026").mkdir(parents=True)
    with pytest.raises(ProjetoJaExiste):
        planejar_pastas(_creq(), cfg, perguntar=NAO, ano=2026)


def test_rev2_pasta_inacessivel_no_parecido_nao_derruba(settings, tmp_path):
    cfg = _rede(settings, tmp_path)
    _sul(tmp_path).mkdir(parents=True)
    (_sul(tmp_path) / "Usina Boa Vista Ltda").write_text("arquivo, não pasta")
    plano = planejar_pastas(_creq(), cfg, perguntar=NAO, ano=2026)
    assert plano.base.name == "R.0"


# ------------------------------------------------------------------ nomes (correção 18)

@pytest.mark.parametrize("nome", ["COM¹", "LPT³", "CONIN$", "conout$", "nul.txt", "Aux", "COM0", "LPT0"])
def test_rev2_nomes_reservados(settings, nome):
    assert any(p.campo == "projeto" for p in validar_cotacao(_creq(projeto=nome), settings))


@pytest.mark.parametrize("nome", ["CON ", " CON", "CON.", "CON..", "NUL .txt"])
def test_rev2_nomes_reservados_com_espaco_ou_ponto(settings, nome):
    """O Windows ignora espaços/pontos no fim: 'NUL .txt' e 'CON.' também são o dispositivo."""
    assert any(p.campo == "projeto" for p in validar_cotacao(_creq(projeto=nome), settings))


def test_rev2_email_com_caracteres_especiais(tmp_path):
    corpo = corpo_email("21800001", tmp_path / "A&B <x>" / "P#1 'q'", "Produto A")
    assert "<x>" not in corpo and "&amp;" in corpo and "%23" in corpo


# ------------------------------------------------------------------ claim: Unicode no anexo e na descrição

def test_rev2_anexo_com_nome_decomposto_e_encontrado(settings, tmp_path):
    """O caminho passa por NFC (correção 18). Um arquivo com nome em NFD no disco (zip do Mac, download)
    deixa de ser encontrado: o NTFS, como o ext4, não normaliza nomes."""
    nome = unicodedata.normalize("NFD", "Cotação.pdf")
    arquivo = tmp_path / nome
    arquivo.write_bytes(b"%PDF-1.4 x")
    req = ClaimRequest.from_form(tipo="PRODUTO_A", descricao="d", texto_livre="t", ordem="1234567", item="10",
                                 arquivo=str(arquivo))
    problemas = [p for p in validate(req, settings) if p.campo == "arquivo"]
    assert problemas == [], problemas


def test_rev2_nome_do_anexo_com_emoji_conta_como_o_sap(settings, tmp_path):
    """A descrição conta UTF-16 (emoji = 2); o nome do arquivo, que VIRA a descrição do documento, não."""
    # Limite fixado em 40 (o settings.ini local pode ter 255, e um nome de 255+ não cabe no Windows).
    settings = replace(settings, limites=replace(settings.limites, descricao_documento_max=40))
    maximo = 40
    nome = "a" * (maximo - 5) + "😀.pdf"           # len() == maximo, UTF-16 == maximo + 1
    arquivo = tmp_path / nome
    arquivo.write_bytes(b"%PDF-1.4 x")
    req = ClaimRequest.from_form(tipo="PRODUTO_A", descricao="d", texto_livre="t", ordem="1234567", item="10",
                                 arquivo=str(arquivo))
    assert any(p.campo == "arquivo" for p in validate(req, settings))


@pytest.mark.parametrize("descricao", ["linha 1\nlinha 2", "tab\taqui", "nulo\x00x"])
def test_rev2_descricao_de_uma_linha_recusa_controle(settings, arquivo_pdf, descricao):
    req = ClaimRequest.from_form(tipo="PRODUTO_A", descricao=descricao, texto_livre="t", ordem="1234567",
                                 item="10", arquivo=str(arquivo_pdf))
    assert any(p.campo == "descricao" for p in validate(req, settings))


def test_rev2_descricao_no_limite_com_emoji(settings, arquivo_pdf):
    maximo = settings.limites.descricao_max
    ok = ClaimRequest.from_form(tipo="PRODUTO_A", descricao="a" * (maximo - 2) + "😀", texto_livre="t",
                                ordem="1", item="10", arquivo=str(arquivo_pdf))
    estoura = replace(ok, descricao="a" * (maximo - 1) + "😀")
    assert not [p for p in validate(ok, settings) if p.campo == "descricao"]
    assert [p for p in validate(estoura, settings) if p.campo == "descricao"]
