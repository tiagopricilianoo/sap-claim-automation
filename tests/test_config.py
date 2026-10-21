# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
import pytest

from config import USUARIO_LOGADO, ConfigError, load_settings, pendencias_configuracao


def test_carrega_valores_fixos(settings):
    assert settings.sistema == "PRD"
    assert settings.mandante == "100"
    assert settings.tipo_nota == "Z1"
    assert (settings.causa_grupo, settings.causa_codigo) == ("01", "0001")
    assert settings.prioridade == "1"
    assert (settings.doc_tipo, settings.doc_laboratorio, settings.doc_aplicacao) == ("ZDC", "L01", "PDF")
    assert settings.modo == "SIMULACAO"
    assert settings.automatico_habilitado is False


def test_tres_rotas_na_ordem_certa(settings):
    assert set(settings.rotas) == {"PRODUTO_A", "PRODUTO_B", "PRODUTO_B_CUSTO"}
    nos = lambda chave: [a.no for a in settings.rota(chave).atividades]
    assert nos("PRODUTO_A") == ["000000000660", "000000000647"]
    assert nos("PRODUTO_B") == ["000000000660", "000000000648"]
    assert nos("PRODUTO_B_CUSTO") == ["000000000660", "000000000683", "000000000687", "000000000689", "000000000648"]


def test_responsaveis_resolvidos(settings):
    rota = settings.rota("PRODUTO_B_CUSTO")
    finais = [a.responsavel_para("usuario1") for a in rota.atividades]
    assert finais == ["", "USUARIO_IND", "USUARIO_SUP", "USUARIO_CUS", "USUARIO1"]
    assert rota.atividades[-1].responsavel == USUARIO_LOGADO


def test_rota_desconhecida(settings):
    with pytest.raises(ConfigError):
        settings.rota("INEXISTENTE")


def test_aviso_bloqueio_cliente_configurado(settings):
    assert "O cliente * tem bloqueio de registro" in settings.avisos_aceitos


def test_configuracao_real_sem_pendencias(settings):
    # Sub grupos confirmados na grade real (20/10/2026): as duas "TR" se distinguem.
    assert pendencias_configuracao(settings) == []
    custo = {a.chave: a.subgrupo for a in settings.rota("PRODUTO_B_CUSTO").atividades}
    assert list(custo) == ["analise", "industrial", "suprimentos", "custos", "com_produto_b"]
    assert custo["industrial"] == "GRP-IND" and custo["custos"] == "GRP-CUS"


def test_detecta_atividades_indistinguiveis(tmp_path, texto_ini):
    caminho = _ini(tmp_path, texto_ini, "subgrupo = GRP-CUS", "subgrupo = GRP-IND")
    pendencias = pendencias_configuracao(load_settings(caminho))
    assert any("industrial" in p and "custos" in p for p in pendencias)


def _ini(tmp_path, texto_original, de, para):
    alterado = tmp_path / "settings.ini"
    alterado.write_text(texto_original.replace(de, para), encoding="utf-8")
    return alterado


@pytest.fixture
def texto_ini():
    from conftest import texto_settings_padrao
    return texto_settings_padrao()


def test_automatico_exige_habilitacao(tmp_path, texto_ini):
    caminho = _ini(tmp_path, texto_ini, "modo = SIMULACAO", "modo = AUTOMATICO")
    with pytest.raises(ConfigError, match="automatico_habilitado"):
        load_settings(caminho)


def test_automatico_habilitado_aceito(tmp_path, texto_ini):
    texto = texto_ini.replace("modo = SIMULACAO", "modo = AUTOMATICO")
    caminho = _ini(tmp_path, texto, "automatico_habilitado = nao", "automatico_habilitado = sim")
    assert load_settings(caminho).modo == "AUTOMATICO"


def test_modo_invalido(tmp_path, texto_ini):
    caminho = _ini(tmp_path, texto_ini, "modo = SIMULACAO", "modo = TURBO")
    with pytest.raises(ConfigError, match="Modo inválido"):
        load_settings(caminho)


def test_rota_com_atividade_inexistente(tmp_path, texto_ini):
    caminho = _ini(tmp_path, texto_ini, "atividades = analise, com_produto_a",
                   "atividades = analise, nao_existe")
    with pytest.raises(ConfigError, match="nao_existe"):
        load_settings(caminho)


def test_valor_obrigatorio_vazio(tmp_path, texto_ini):
    caminho = _ini(tmp_path, texto_ini, "tipo_nota = Z1", "tipo_nota =")
    with pytest.raises(ConfigError, match="tipo_nota"):
        load_settings(caminho)


def test_arquivo_inexistente(tmp_path):
    with pytest.raises(ConfigError, match="não encontrado"):
        load_settings(tmp_path / "nao_existe.ini")


def test_testes_independem_da_configuracao_de_uso(settings):
    # Mesmo com a gravação habilitada no settings.ini real, os testes partem do padrão seguro.
    assert settings.automatico_habilitado is False and settings.modo == "SIMULACAO"
