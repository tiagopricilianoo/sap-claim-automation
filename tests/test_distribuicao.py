# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Publicação no servidor e atualização automática nos computadores."""

import importlib.util
import shutil
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent


def _modulo(nome, caminho):
    spec = importlib.util.spec_from_file_location(nome, caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


publicar = _modulo("publicar_mod", RAIZ / "publicar.py")
iniciar = _modulo("iniciar_mod", RAIZ / "distribuicao" / "iniciar.py")


@pytest.fixture
def servidor(tmp_path):
    pasta = tmp_path / "servidor"
    pasta.mkdir()
    return pasta


@pytest.fixture
def pc(tmp_path):
    pasta = tmp_path / "pc"
    pasta.mkdir()
    return pasta


def _sem_pip(_requirements):
    pass


# ------------------------------------------------------------------ publicação

def test_proxima_versao():
    assert publicar.proxima_versao("1.0.0") == "1.0.1"
    assert publicar.proxima_versao("1.2.9") == "1.2.10"
    assert publicar.proxima_versao("") == "1.0.0"


def test_settings_de_producao():
    from conftest import texto_settings_padrao
    texto = texto_settings_padrao().replace("pasta_dados =", r"pasta_dados = C:\dev\historico")
    prod = publicar.settings_de_producao(texto)
    assert "modo = AUTOMATICO" in prod and "automatico_habilitado = sim" in prod
    assert "\npasta_dados =\n" in prod                       # histórico na pasta padrão de cada usuário
    assert "USUARIO_SUP" in prod and "40SUPRIMENTOS" in prod     # rotas preservadas


def test_pacote_de_producao_sem_testes_nem_simulador(tmp_path):
    destino = tmp_path / "app"
    publicar.montar_pacote(RAIZ, destino, "1.0.0")
    nomes = {p.name for p in destino.rglob("*")}
    assert {"ui.py", "sap_client.py", "iniciar.py", "settings.ini", "versao.txt", "app.ico"} <= nomes
    assert not {"sap_fake.py", "ensaio.py", "publicar.py", "conftest.py"} & nomes
    assert "pytest" not in (destino / "requirements.txt").read_text()


def test_pacote_publicado_carrega_em_modo_de_uso(tmp_path):
    from config import load_settings
    destino = tmp_path / "app"
    publicar.montar_pacote(RAIZ, destino, "1.0.0")
    s = load_settings(destino / "settings.ini")
    assert (s.modo, s.automatico_habilitado) == ("AUTOMATICO", True)


def test_publicar_e_republicar(servidor):
    assert publicar.publicar(servidor, nota="primeira") == "1.0.0"
    assert publicar.publicar(servidor, nota="segunda") == "1.0.1"
    assert (servidor / "app" / "versao.txt").read_text().strip() == "1.0.1"
    assert (servidor / "app_anterior" / "versao.txt").read_text().strip() == "1.0.0"
    assert (servidor / "instalar.bat").exists() and (servidor / "instalar.py").exists()
    assert len((servidor / "historico_versoes.txt").read_text(encoding="utf-8").splitlines()) == 2
    assert not (servidor / "app_publicando").exists()


def test_nao_republica_a_mesma_versao(servidor):
    publicar.publicar(servidor, versao="2.0.0")
    with pytest.raises(ValueError):
        publicar.publicar(servidor, versao="2.0.0")


# ------------------------------------------------------------------ atualização no computador

def test_primeira_instalacao_e_atualizacao(servidor, pc):
    publicar.publicar(servidor)
    assert "atualizado" in iniciar.atualizar(servidor / "app", pc, instalar_libs=_sem_pip)
    assert iniciar.ler_versao(pc / "app") == "1.0.0"
    assert (pc / "iniciar.py").exists()

    assert "já é a do servidor" in iniciar.atualizar(servidor / "app", pc, instalar_libs=_sem_pip)

    publicar.publicar(servidor)
    assert "para 1.0.1" in iniciar.atualizar(servidor / "app", pc, instalar_libs=_sem_pip)
    assert iniciar.ler_versao(pc / "app") == "1.0.1"
    assert not (pc / "app_novo").exists()


def test_servidor_fora_do_ar_usa_versao_instalada(servidor, pc):
    publicar.publicar(servidor)
    iniciar.atualizar(servidor / "app", pc, instalar_libs=_sem_pip)
    shutil.rmtree(servidor)
    assert "inacessível" in iniciar.atualizar(servidor / "app", pc, instalar_libs=_sem_pip)
    assert iniciar.ler_versao(pc / "app") == "1.0.0"


def test_falha_no_pip_mantem_a_versao_anterior(servidor, pc):
    publicar.publicar(servidor)
    iniciar.atualizar(servidor / "app", pc, instalar_libs=_sem_pip)
    publicar.publicar(servidor)
    (servidor / "app" / "requirements.txt").write_text("biblioteca-nova\n")

    def pip_quebrado(_):
        raise RuntimeError("sem internet")
    with pytest.raises(RuntimeError):
        iniciar.atualizar(servidor / "app", pc, instalar_libs=pip_quebrado)
    assert iniciar.ler_versao(pc / "app") == "1.0.0"       # continua funcionando


def test_requirements_igual_nao_roda_pip(servidor, pc):
    chamadas = []
    publicar.publicar(servidor)
    iniciar.atualizar(servidor / "app", pc, instalar_libs=chamadas.append)
    publicar.publicar(servidor)
    iniciar.atualizar(servidor / "app", pc, instalar_libs=chamadas.append)
    assert len(chamadas) == 1                               # só na primeira instalação


def test_sem_origem_configurada(pc):
    assert iniciar.atualizar(None, pc) == "sem origem configurada"


def test_ler_origem(tmp_path):
    ini = tmp_path / "atualizacao.ini"
    ini.write_text("[atualizacao]\norigem = \\\\servidor\\comercial\\AutomacaoClaims\\app\n", encoding="utf-8")
    assert str(iniciar.ler_origem(ini)).endswith("AutomacaoClaims\\app") or \
        "AutomacaoClaims" in str(iniciar.ler_origem(ini))
    assert iniciar.ler_origem(tmp_path / "nao_existe.ini") is None
