# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
from models import ClaimRequest
from validators import validate


def campos(problemas):
    return {p.campo for p in problemas}


# ------------------------------------------------------------ normalização

def test_remove_espacos_so_nas_pontas():
    req = ClaimRequest.from_form(tipo=" PRODUTO_A ", descricao="  Motor  com ruído ", texto_livre="  a  \n  b  ",
                                 ordem=" 123 ", item=" 10 ", arquivo='  "C:\\x\\a.pdf"  ')
    assert req.tipo == "PRODUTO_A"
    assert req.descricao == "Motor  com ruído"      # espaço interno preservado
    assert req.texto_livre == "a  \n  b"
    assert (req.ordem, req.item) == ("123", "10")
    assert req.nome_arquivo.endswith("a.pdf")       # aspas do "copiar como caminho" removidas


def test_quebras_de_linha_padronizadas():
    req = ClaimRequest.from_form(tipo="", descricao="", texto_livre="l1\r\nl2\rl3",
                                 ordem="", item="", arquivo="")
    assert req.texto_livre == "l1\nl2\nl3"
    assert req.arquivo is None


def test_nao_completa_zeros(request_valido):
    req = ClaimRequest.from_form(tipo="PRODUTO_A", descricao="x", texto_livre="x",
                                 ordem="00123", item="010", arquivo="")
    assert (req.ordem, req.item) == ("00123", "010")


# ------------------------------------------------------------ validação

def test_dados_validos(request_valido, settings):
    assert validate(request_valido, settings) == []


def test_tudo_vazio_aponta_todos_os_campos(settings):
    req = ClaimRequest.from_form(tipo="", descricao="", texto_livre=" \n ", ordem="", item="", arquivo="")
    assert campos(validate(req, settings)) == {"tipo", "descricao", "texto_livre", "ordem", "item", "arquivo"}


def test_tipo_desconhecido(request_valido, settings):
    req = ClaimRequest.from_form(**{**_form(request_valido), "tipo": "MOTORES"})
    assert campos(validate(req, settings)) == {"tipo"}


def test_descricao_longa(request_valido, settings):
    req = ClaimRequest.from_form(**{**_form(request_valido), "descricao": "x" * 41})
    assert campos(validate(req, settings)) == {"descricao"}


def test_ordem_e_item_so_digitos(request_valido, settings):
    for ordem in ("2173.3814", "1234567A", "2173 3814", "２１７"):   # inclui dígitos de largura total
        req = ClaimRequest.from_form(**{**_form(request_valido), "ordem": ordem})
        assert campos(validate(req, settings)) == {"ordem"}, ordem


def test_ordem_e_item_tamanho(request_valido, settings):
    req = ClaimRequest.from_form(**{**_form(request_valido), "ordem": "1" * 11, "item": "1" * 7})
    assert campos(validate(req, settings)) == {"ordem", "item"}


def test_arquivo_inexistente(request_valido, settings, tmp_path):
    req = ClaimRequest.from_form(**{**_form(request_valido), "arquivo": str(tmp_path / "sumiu.pdf")})
    assert campos(validate(req, settings)) == {"arquivo"}


def test_arquivo_e_pasta(request_valido, settings, tmp_path):
    req = ClaimRequest.from_form(**{**_form(request_valido), "arquivo": str(tmp_path)})
    assert campos(validate(req, settings)) == {"arquivo"}


def test_arquivo_vazio(request_valido, settings, tmp_path):
    vazio = tmp_path / "vazio.pdf"
    vazio.write_bytes(b"")
    req = ClaimRequest.from_form(**{**_form(request_valido), "arquivo": str(vazio)})
    assert "vazio" in validate(req, settings)[0].mensagem


def test_nome_do_arquivo_longo(request_valido, settings, tmp_path):
    longo = tmp_path / ("n" * 37 + ".pdf")     # 41 caracteres
    longo.write_bytes(b"x")
    req = ClaimRequest.from_form(**{**_form(request_valido), "arquivo": str(longo)})
    problemas = validate(req, settings)
    assert campos(problemas) == {"arquivo"} and "Renomeie" in problemas[0].mensagem


def test_aceita_qualquer_extensao(request_valido, settings, tmp_path):
    for nome in ("anexos.zip", "planilha.xlsx", "texto.docx"):
        arq = tmp_path / nome
        arq.write_bytes(b"x")
        req = ClaimRequest.from_form(**{**_form(request_valido), "arquivo": str(arq)})
        assert validate(req, settings) == [], nome


def _form(req):
    return dict(tipo=req.tipo, descricao=req.descricao, texto_livre=req.texto_livre,
                ordem=req.ordem, item=req.item, arquivo=str(req.arquivo))


# ------------------------------------------------------------ claim sem anexo

def test_sem_anexo_explicito_e_valido(request_valido, settings):
    req = ClaimRequest.from_form(**{**_form(request_valido), "arquivo": ""}, sem_anexo=True)
    assert req.sem_anexo and req.arquivo is None
    assert validate(req, settings) == []


def test_sem_arquivo_e_sem_marcar_continua_obrigatorio(request_valido, settings):
    req = ClaimRequest.from_form(**{**_form(request_valido), "arquivo": ""})
    problemas = validate(req, settings)
    assert campos(problemas) == {"arquivo"} and "não tem anexo" in problemas[0].mensagem


def test_arquivo_e_sem_anexo_ao_mesmo_tempo_e_contraditorio(request_valido, settings):
    req = ClaimRequest.from_form(**_form(request_valido), sem_anexo=True)
    assert campos(validate(req, settings)) == {"arquivo"}
