# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""REVISOR TESTADOR: limites de validação (claim e cotação) e pastas na rede."""

import unicodedata
from dataclasses import replace

import pytest

from cotacao import CotacaoRequest, validar_cotacao
from models import ClaimRequest
from pastas import MAX_CAMINHO, CaminhoMuitoLongo, ProjetoJaExiste, criar_pastas, planejar_pastas
from validators import validate


def _creq(**kw):
    base = dict(tipo="Nacional", regiao="Sul", cliente="Usina Boa Vista", projeto="Cogeração 2026", produto_a=True)
    base.update(kw)
    return CotacaoRequest.from_form(**base)


def _campos(problemas):
    return {p.campo for p in problemas}


# ------------------------------------------------------------------ cotação: cliente/projeto

_NOMES = [
    ("a" * 50, True), ("a" * 51, False), ("ç" * 50, True), ("ç" * 51, False),
    ("", False), ("     ", False), ("\t \n", False), ("...", False),
    ("a" * 50 + " . .", True),                     # pontos/espaços finais são removidos
    ("CON", False), ("con", False), ("Con.txt", False), ("COM1", False), ("LPT9", False), ("NUL.tar.gz", False),
    ("CONSULTA", True), ("Usina/Sul", False), ("A:B", False), ("A?", False), ("A*", False), ('A"B', False),
    ("Usina\x01", False), ("São João – 2ª fase", True),
]


@pytest.mark.parametrize("campo,valor,ok", [(c, v, o) for c in ("cliente", "projeto") for v, o in _NOMES])
def test_rev_limites_nome_cotacao(settings, campo, valor, ok):
    problemas = validar_cotacao(_creq(**{campo: valor}), settings)
    assert (campo not in _campos(problemas)) == ok, (repr(valor), problemas)


def test_rev_nome_decomposto_conta_como_o_usuario_ve(settings):
    """'ç' colado de PDF/Mac vem decomposto (c + cedilha): 30 letras visíveis não podem virar 60."""
    valor = unicodedata.normalize("NFD", "ç" * 30)
    assert len(valor) == 60
    assert "cliente" not in _campos(validar_cotacao(_creq(cliente=valor), settings))


def test_rev_especial_ignora_cliente_digitado(settings):
    req = CotacaoRequest.from_form(tipo="Cliente Especial", cliente="Qualquer", projeto="K-1", produto_a=True)
    assert req.cliente == "" and validar_cotacao(req, settings) == []


def test_rev_sem_equipamento(settings):
    assert "equipamentos" in _campos(validar_cotacao(_creq(produto_a=False, produto_b=False), settings))


@pytest.mark.parametrize("pais,ok", [("Alemanha", True), ("Brasil", False), ("", False), ("Argentina", False)])
def test_rev_pais_da_regiao(settings, pais, ok):
    req = _creq(tipo="Exportação", regiao="Europa", pais=pais)
    assert ("pais" not in _campos(validar_cotacao(req, settings))) == ok


# ------------------------------------------------------------------ claim: descrição, texto, ordem, item

def _claim(arq, **kw):
    base = dict(tipo="PRODUTO_A", descricao="Consulta", texto_livre="t", ordem="1234567", item="10",
                arquivo=str(arq))
    base.update(kw)
    return ClaimRequest.from_form(**base)


@pytest.mark.parametrize("descricao,ok", [
    ("a" * 40, True), ("a" * 41, False), ("ç" * 40, True), ("   ", False), ("", False),
    ("  " + "a" * 40 + "  ", True),
    ("\U0001F600" * 21, False),    # 21 caracteres fora do BMP = 42 posições UTF-16 no SAP (campo de 40)
])
def test_rev_limites_descricao_claim(settings, arquivo_pdf, descricao, ok):
    assert ("descricao" not in _campos(validate(_claim(arquivo_pdf, descricao=descricao), settings))) == ok


@pytest.mark.parametrize("texto,ok", [("   \n\n  ", False), ("\r\n\r\n", False), ("x", True)])
def test_rev_texto_livre_vazio(settings, arquivo_pdf, texto, ok):
    assert ("texto_livre" not in _campos(validate(_claim(arquivo_pdf, texto_livre=texto), settings))) == ok


@pytest.mark.parametrize("ordem,ok", [
    ("1" * 10, True), ("1" * 11, False), (" 1234567 ", True), ("2173 3814", False), ("２１７", False),
    ("²", False), ("-1", False), ("1234567\n", True),
])
def test_rev_limites_ordem(settings, arquivo_pdf, ordem, ok):
    assert ("ordem" not in _campos(validate(_claim(arquivo_pdf, ordem=ordem), settings))) == ok


@pytest.mark.parametrize("item,ok", [("1" * 6, True), ("1" * 7, False), ("", False), ("1O", False)])
def test_rev_limites_item(settings, arquivo_pdf, item, ok):
    assert ("item" not in _campos(validate(_claim(arquivo_pdf, item=item), settings))) == ok


def test_rev_nome_de_arquivo_no_limite(settings, tmp_path):
    # O limite vem do settings.ini (pode ser 255 no computador de desenvolvimento): fixado em 40 aqui.
    settings = replace(settings, limites=replace(settings.limites, descricao_documento_max=40))
    for n, ok in ((40, True), (41, False)):
        arq = tmp_path / ("a" * (n - 4) + ".pdf")
        arq.write_bytes(b"x")
        assert ("arquivo" not in _campos(validate(_claim(arq), settings))) == ok


def test_rev_caminho_entre_aspas(settings, arquivo_pdf):
    """'Copiar como caminho' do Windows põe aspas."""
    assert validate(_claim(arquivo_pdf, arquivo=f'"{arquivo_pdf}"'), settings) == []


# ------------------------------------------------------------------ pastas

def _rede(settings, raiz):
    tu, tr = raiz / "TU", raiz / "TR"
    tu.mkdir(parents=True, exist_ok=True)
    tr.mkdir(parents=True, exist_ok=True)
    return replace(settings.cotacao, raiz_produto_a=str(tu), raiz_produto_b=str(tr))


def _sul(raiz):
    return raiz / "TU" / "Propostas_2026" / "Brasil" / "Sul"


def test_rev_cliente_parecido_nao_cria_pasta_nova_ao_lado(settings, tmp_path):
    cfg = _rede(settings, tmp_path)
    (_sul(tmp_path) / "Usina Boa Vista S.A").mkdir(parents=True)
    plano = planejar_pastas(_creq(), cfg, perguntar=lambda t, x: False, ano=2026)
    assert plano.base == _sul(tmp_path) / "Usina Boa Vista" / "Cogeração 2026" / "R.0"
    assert not (_sul(tmp_path) / "Usina Boa Vista").exists()       # planejar não cria nada


def test_rev_cliente_parecido_sim_e_projeto_existente_para(settings, tmp_path):
    cfg = _rede(settings, tmp_path)
    (_sul(tmp_path) / "Usina Boa Vista S.A" / "COGERACAO 2026").mkdir(parents=True)
    with pytest.raises(ProjetoJaExiste):
        planejar_pastas(_creq(), cfg, perguntar=lambda t, x: True, ano=2026)


def test_rev_dois_clientes_parecidos_pergunta_por_cada_um(settings, tmp_path):
    cfg = _rede(settings, tmp_path)
    (_sul(tmp_path) / "Usina Boa Vista Ltda").mkdir(parents=True)
    (_sul(tmp_path) / "Usina Boa Vista S.A").mkdir(parents=True)
    perguntas = []
    planejar_pastas(_creq(), cfg, perguntar=lambda t, x: perguntas.append(x) or False, ano=2026)
    assert len(perguntas) == 2, f"só {len(perguntas)} pergunta(s): o 2º cliente parecido nunca é oferecido"


def test_rev_mesmo_cliente_com_caixa_diferente_nao_pergunta(settings, tmp_path):
    cfg = _rede(settings, tmp_path)
    (_sul(tmp_path) / "USINA BOA VISTA").mkdir(parents=True)
    perguntas = []
    plano = planejar_pastas(_creq(), cfg, perguntar=lambda t, x: perguntas.append(x) or True, ano=2026)
    assert perguntas == [] and "USINA BOA VISTA" in str(plano.base)


def _raiz_para(tmp_path, alvo):
    """Raiz cujo caminho R.0 (cliente de 40 'c', projeto 'P') tem exatamente `alvo` caracteres."""
    resto = len("/TU/Propostas_2026/Brasil/Sul/" + "c" * 40 + "/P/R.0")
    falta = alvo - len(str(tmp_path)) - resto - 1
    return tmp_path / ("r" * falta)


@pytest.mark.parametrize("alvo,ok", [(MAX_CAMINHO - 60, True), (MAX_CAMINHO - 59, False)])
def test_rev_caminho_longo_no_limite(settings, tmp_path, alvo, ok):
    raiz = _raiz_para(tmp_path, alvo)
    cfg = _rede(settings, raiz)
    req = _creq(cliente="c" * 40, projeto="P")
    if ok:
        plano = planejar_pastas(req, cfg, perguntar=lambda *a: False, ano=2026)
        assert len(str(plano.base)) == alvo
        base = criar_pastas(plano, "21800001", criar_atalho=lambda *a: None)   # nada pode estourar o limite
        assert (base / "Correspondências" / "interno" / "Engenharia").is_dir()
        assert max(len(str(p)) for p in plano.base.parent.rglob("*")) <= MAX_CAMINHO
    else:
        with pytest.raises(CaminhoMuitoLongo):
            planejar_pastas(req, cfg, perguntar=lambda *a: False, ano=2026)


def test_rev_criar_pastas_duas_vezes_preserva_arquivos(settings, tmp_path):
    cfg = _rede(settings, tmp_path)
    plano = planejar_pastas(_creq(), cfg, perguntar=lambda *a: False, ano=2026)
    base = criar_pastas(plano, "21800001", criar_atalho=lambda *a: None)
    (base / "Claim" / "Nº da Claim.txt").write_text("423", encoding="utf-8")
    criar_pastas(plano, "21800001", criar_atalho=lambda *a: None)
    assert (base / "Claim" / "Nº da Claim.txt").read_text(encoding="utf-8") == "423"


def test_rev_especial_caminho_longo(settings, tmp_path):
    raiz = tmp_path / ("r" * 150)
    cfg = _rede(settings, raiz)
    req = CotacaoRequest.from_form(tipo="Cliente Especial", projeto="P" * 50, produto_a=True)
    with pytest.raises(CaminhoMuitoLongo):
        planejar_pastas(req, cfg, perguntar=lambda *a: False, ano=2026)


def test_rev_so_produto_b_usa_a_rede_do_produto_b(settings, tmp_path):
    cfg = _rede(settings, tmp_path)
    plano = planejar_pastas(_creq(produto_a=False, produto_b=True), cfg, perguntar=lambda *a: False, ano=2026)
    assert str(plano.base).startswith(str(tmp_path / "TR" / "Propostas - 2026"))
