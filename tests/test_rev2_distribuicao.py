# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""REVISOR 4 (TESTADOR), RODADA 2: manifesto, versões e downgrade (iniciar.py) e publicar.py."""

import importlib.util
import json
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent


def _modulo(nome, caminho):
    spec = importlib.util.spec_from_file_location(nome, caminho)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


publicar = _modulo("publicar_rev2", RAIZ / "publicar.py")
iniciar = _modulo("iniciar_rev2", RAIZ / "distribuicao" / "iniciar.py")


def _sem_pip(_r):
    pass


def _pastas(tmp_path):
    servidor, pc = tmp_path / "servidor", tmp_path / "pc"
    servidor.mkdir()
    pc.mkdir()
    return servidor, pc


def _instalar(servidor, pc, versao):
    publicar.publicar(servidor, versao=versao)
    return iniciar.atualizar(servidor / "app", pc, instalar_libs=_sem_pip)


# ------------------------------------------------------------------ versões / downgrade (correção 7)

@pytest.mark.parametrize("local,servidor,instala", [
    ("1.0.9", "1.0.10", True),
    ("1.0.10", "1.0.9", False),
    ("1.2.0", "1.2", False),          # (1,2) < (1,2,0): mais antiga
    ("2.0.0", "10.0.0", True),
    ("1.2.0", "1.0.0-hotfix", False),  # não numérica e mais antiga
    ("1.2.0", " 1.1.0 ", False),
])
def test_rev2_ordem_das_versoes(tmp_path, local, servidor, instala):
    # Contrato (correção da 2ª banca): publicar.py só publica número de versão MAIOR que o do ar;
    # versão escrita à mão no servidor que não seja maior / não seja número é ignorada nos computadores.
    srv, pc = _pastas(tmp_path)
    _instalar(srv, pc, local)
    try:
        publicar.publicar(srv, versao=servidor.strip())
    except ValueError:
        (srv / "app" / "versao.txt").write_text(servidor + "\n")       # "à mão", sem o publicar.py
    resultado = iniciar.atualizar(srv / "app", pc, instalar_libs=_sem_pip)
    instalada = iniciar.ler_versao(pc / "app")
    assert (instalada == servidor.strip()) == instala, (resultado, instalada)


def test_rev2_publicar_aceita_versao_menor_que_a_publicada(tmp_path):
    """publicar --versao 1.0.0 com 1.2.0 no ar: publica, e TODOS os computadores ignoram em silêncio."""
    srv, _ = _pastas(tmp_path)
    publicar.publicar(srv, versao="1.2.0")
    with pytest.raises(ValueError):
        publicar.publicar(srv, versao="1.0.0")


def test_rev2_proxima_versao_de_numero_com_duas_partes(tmp_path):
    """Versão '1.2' publicada à mão: a próxima automática vira '1.0.0', mais antiga, ignorada nos PCs."""
    assert publicar.proxima_versao("1.2") not in ("1.0.0",), publicar.proxima_versao("1.2")


# ------------------------------------------------------------------ manifesto

@pytest.mark.parametrize("estranho", ["assets/Thumbs.db", "desktop.ini", "assets/desktop.ini", ".DS_Store"])
def test_rev2_arquivo_do_windows_na_pasta_trava_todas_as_atualizacoes(tmp_path, estranho):
    """O Explorer cria Thumbs.db/desktop.ini sozinho ao abrir a pasta do servidor. A atualização passa a ser
    recusada em todos os computadores, só com uma linha no log (ninguém vê)."""
    srv, pc = _pastas(tmp_path)
    _instalar(srv, pc, "1.0.0")
    publicar.publicar(srv, versao="1.0.1")
    (srv / "app" / estranho).parent.mkdir(parents=True, exist_ok=True)
    (srv / "app" / estranho).write_bytes(b"\x00")
    iniciar.atualizar(srv / "app", pc, instalar_libs=_sem_pip)
    assert iniciar.ler_versao(pc / "app") == "1.0.1"


def test_rev2_manifesto_de_outra_versao_e_recusado(tmp_path):
    srv, pc = _pastas(tmp_path)
    _instalar(srv, pc, "1.0.0")
    publicar.publicar(srv, versao="1.0.1")
    m = json.loads((srv / "app" / "manifesto.json").read_text(encoding="utf-8"))
    m["versao"] = "9.9.9"
    (srv / "app" / "manifesto.json").write_text(json.dumps(m), encoding="utf-8")
    assert "recusada" in iniciar.atualizar(srv / "app", pc, instalar_libs=_sem_pip)
    assert iniciar.ler_versao(pc / "app") == "1.0.0"


@pytest.mark.parametrize("plantado", ["sub/versao.txt", "assets/manifesto.json", "__pycache__/ui.cpython-311.pyc",
                                      "assets/__pycache__/x.py"])
def test_rev2_arquivo_plantado_com_nome_ignorado_nao_passa(tmp_path, plantado):
    """Nomes ignorados pelo manifesto (versao.txt, manifesto.json, __pycache__) em QUALQUER subpasta."""
    srv, pc = _pastas(tmp_path)
    _instalar(srv, pc, "1.0.0")
    publicar.publicar(srv, versao="1.0.1")
    alvo = srv / "app" / plantado
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_text("import os  # plantado\n")
    iniciar.atualizar(srv / "app", pc, instalar_libs=_sem_pip)
    copiado = pc / "app" / plantado
    assert not copiado.exists() or iniciar.ler_versao(pc / "app") == "1.0.0", \
        f"{plantado} entrou no computador sem estar no manifesto"


def test_rev2_manifesto_com_json_invalido_e_tipos_errados(tmp_path):
    srv, pc = _pastas(tmp_path)
    _instalar(srv, pc, "1.0.0")
    publicar.publicar(srv, versao="1.0.1")
    for conteudo in ("{", "[]", '{"versao": "1.0.1", "arquivos": []}', '{"versao": "1.0.1", "arquivos": null}'):
        (srv / "app" / "manifesto.json").write_text(conteudo, encoding="utf-8")
        r = iniciar.atualizar(srv / "app", pc, instalar_libs=_sem_pip)
        assert "recusada" in r, (conteudo, r)
    assert iniciar.ler_versao(pc / "app") == "1.0.0"


def test_rev2_primeira_instalacao_sem_manifesto_e_aceita(tmp_path):
    """Comportamento documentado: sem manifesto local nem no servidor, nada é conferido (versão antiga)."""
    srv, pc = _pastas(tmp_path)
    publicar.publicar(srv, versao="1.0.0")
    (srv / "app" / "manifesto.json").unlink()
    (srv / "app" / "extra.py").write_text("x = 1\n")
    iniciar.atualizar(srv / "app", pc, instalar_libs=_sem_pip)
    assert (pc / "app" / "extra.py").exists()     # informativo: a 1ª instalação não tem proteção


# ------------------------------------------------------------------ publicar.py: pasta errada (correção 21)

def test_rev2_publicar_em_pasta_de_grupo_que_tem_um_instalar_bat_qualquer(tmp_path):
    """'instalar.bat' é um nome comum: a pasta de outro programa com esse arquivo é aceita como nossa."""
    grupo = tmp_path / "grupo"
    (grupo / "app").mkdir(parents=True)
    (grupo / "app" / "planilha.xlsx").write_text("dados")
    (grupo / "instalar.bat").write_text("@echo instalador de OUTRO programa")
    with pytest.raises(ValueError):
        publicar.publicar(grupo)
    assert (grupo / "app" / "planilha.xlsx").exists()


def test_rev2_publicar_em_arquivo_e_nao_pasta(tmp_path):
    arquivo = tmp_path / "x.txt"
    arquivo.write_text("x")
    with pytest.raises(ValueError):
        publicar.publicar(arquivo)


def test_rev2_publicar_nao_apaga_atalho_de_pasta(tmp_path):
    import os
    srv, _ = _pastas(tmp_path)
    publicar.publicar(srv, versao="1.0.0")
    alvo = tmp_path / "importante"
    alvo.mkdir()
    (alvo / "dado.txt").write_text("x")
    try:
        os.symlink(alvo, srv / "app_publicando", target_is_directory=True)
    except OSError:          # Windows sem modo desenvolvedor/administrador não cria link simbólico
        pytest.skip("sem permissão para criar link simbólico neste computador")
    with pytest.raises(ValueError):
        publicar.publicar(srv, versao="1.0.1")
    assert (alvo / "dado.txt").exists()


# ------------------------------------------------------------------ requirements (correção 15)

def test_rev2_requirements_fixos_ou_com_teto():
    for linha in publicar.REQUIREMENTS_PRODUCAO.split():
        assert "==" in linha or "<" in linha, linha
