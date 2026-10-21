# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Inicializador da Automação de Claims (fica no computador de cada orçamentista).

Ao abrir:
1. Lê em atualizacao.ini a pasta de origem no servidor.
2. Se a versão do servidor for diferente da instalada, copia a nova versão para
   uma pasta temporária e só então troca pela atual (a troca é feita de uma vez;
   se algo falhar no meio, a versão anterior continua valendo).
3. Abre o programa.

Sem acesso ao servidor (rede/VPN), abre a versão já instalada.
Usa só a biblioteca padrão do Python: funciona mesmo se uma atualização
trouxer bibliotecas novas (elas são instaladas aqui, antes de abrir).
"""

from __future__ import annotations

import configparser
import filecmp
import logging
import os
import runpy
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

LOCAL = Path(__file__).resolve().parent
APP = LOCAL / "app"
NOVO = LOCAL / "app_novo"
ANTERIOR = LOCAL / "app_anterior"
CONFIG = LOCAL / "atualizacao.ini"
VERSAO = "versao.txt"

log = logging.getLogger("claim.iniciar")


# ----------------------------------------------------------------------- utilitários

def ler_versao(pasta: Path) -> str:
    try:
        return (pasta / VERSAO).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def ler_origem(config: Path = CONFIG) -> Path | None:
    parser = configparser.ConfigParser(interpolation=None)
    if not parser.read(config, encoding="utf-8"):
        return None
    valor = parser.get("atualizacao", "origem", fallback="").strip()
    return Path(valor) if valor else None


def _remover(pasta: Path) -> None:
    if pasta.exists():
        shutil.rmtree(pasta, ignore_errors=True)


def _python_console() -> str:
    """python.exe ao lado do pythonw.exe (pip precisa de um console invisível)."""
    exe = Path(sys.executable)
    candidato = exe.with_name("python.exe")
    return str(candidato if candidato.exists() else exe)


BIBLIOTECAS_ESSENCIAIS = ("customtkinter", "win32com")


def bibliotecas_presentes() -> bool:
    import importlib.util
    return all(importlib.util.find_spec(nome) is not None for nome in BIBLIOTECAS_ESSENCIAIS)


def instalar_dependencias(requirements: Path) -> None:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    resultado = subprocess.run(
        [_python_console(), "-m", "pip", "install", "-r", str(requirements),
         "--disable-pip-version-check", "--quiet"],
        capture_output=True, text=True, creationflags=flags, timeout=600,
    )
    if resultado.returncode != 0:
        raise RuntimeError(f"pip falhou: {resultado.stderr.strip()[-500:]}")


# ----------------------------------------------------------------------- atualização

def atualizar(origem: Path | None, local: Path = LOCAL, instalar_libs=instalar_dependencias,
              libs_presentes=bibliotecas_presentes) -> str:
    """Atualiza local/app a partir de origem. Retorna o que aconteceu (para o log).

    Nunca deixa o computador sem uma versão funcional: a cópia vai para app_novo
    e só substitui app depois de completa.
    """
    app, novo, anterior = local / "app", local / "app_novo", local / "app_anterior"

    if origem is None:
        return "sem origem configurada"
    try:
        versao_servidor = ler_versao(origem)
    except OSError:
        versao_servidor = ""
    if not versao_servidor:
        return f"servidor inacessível ou sem {VERSAO}: usando a versão instalada"

    versao_local = ler_versao(app)
    if versao_servidor == versao_local:
        return f"versão {versao_local} já é a do servidor"

    _remover(novo)
    shutil.copytree(origem, novo, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if ler_versao(novo) != versao_servidor:
        _remover(novo)
        return "cópia incompleta (versão mudou durante a cópia): tenta na próxima abertura"

    req_novo, req_atual = novo / "requirements.txt", app / "requirements.txt"
    if req_novo.exists() and (not req_atual.exists() or not filecmp.cmp(req_novo, req_atual, shallow=False)):
        try:
            instalar_libs(req_novo)
        except Exception:  # noqa: BLE001
            # Python embutido já traz as bibliotecas: sem internet, o pip falha mas não faz falta.
            if not libs_presentes():
                _remover(novo)
                raise
            log.warning("pip falhou, mas as bibliotecas essenciais já estão presentes; seguindo")

    _remover(anterior)
    if app.exists():
        app.rename(anterior)
    try:
        novo.rename(app)
    except OSError:
        if anterior.exists() and not app.exists():
            anterior.rename(app)          # devolve a versão anterior
        raise

    # O próprio inicializador também é atualizado (vale a partir da próxima abertura).
    iniciador_novo = app / "iniciar.py"
    if iniciador_novo.exists():
        shutil.copy2(iniciador_novo, local / "iniciar.py")
    return f"atualizado de {versao_local or '(nenhuma)'} para {versao_servidor}"


# ----------------------------------------------------------------------- execução

def _avisar_erro(titulo: str, texto: str) -> None:
    try:
        import tkinter
        from tkinter import messagebox
        raiz = tkinter.Tk()
        raiz.withdraw()
        messagebox.showerror(titulo, texto)
        raiz.destroy()
    except Exception:  # noqa: BLE001
        pass


def _configurar_log() -> None:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ClaimAutomation" / "logs"
    base.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=base / "iniciar.log", level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s | %(levelname)-7s | %(message)s")


def main() -> None:
    _configurar_log()
    try:
        resultado = atualizar(ler_origem())
        log.info(resultado)
    except Exception as erro:  # noqa: BLE001 - atualização nunca impede o uso
        log.exception("Falha na atualização")
        _remover(NOVO)
        if not (APP / "ui.py").exists():
            _avisar_erro("Automação de Claims",
                         f"Não foi possível instalar o programa a partir do servidor:\n\n{erro}")
            return

    if not (APP / "ui.py").exists():
        _avisar_erro("Automação de Claims",
                     "O programa ainda não foi baixado e o servidor não está acessível.\n\n"
                     "Conecte-se à rede da empresa e abra de novo.")
        return

    sys.path.insert(0, str(APP))
    os.chdir(APP)
    log.info("Abrindo versão %s (%s)", ler_versao(APP), datetime.now().isoformat(timespec="seconds"))
    runpy.run_path(str(APP / "ui.py"), run_name="__main__")


if __name__ == "__main__":
    main()
