# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Atualização do Python do programa (onde ficam as bibliotecas, como o PySide6), com aviso na tela.

O programa em si já se atualiza sozinho ao abrir (iniciar.py). O Python não: o programa roda dentro
dele e o Windows não deixa trocar a pasta em uso. Por isso:

1. A tela pergunta "Há uma nova atualização disponível, deseja baixar?" (ou "Atualizar depois").
2. A cópia vai para <local>/python_novo, com barra de progresso. Interrompida, nada muda.
3. Ao reiniciar, um script pequeno espera o programa fechar, troca python_novo -> python e abre de novo.
   Se a troca falhar, devolve o Python anterior.

Só vale para quem instalou pelo instalar.bat com o Python do servidor (pasta <local>/python).
"""

from __future__ import annotations

import configparser
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

log = logging.getLogger("claim.atualizacao_python")

RUNTIME = "runtime.txt"
COMPLETO = "copia_completa.txt"


@dataclass(frozen=True)
class Locais:
    local: Path            # %LOCALAPPDATA%\AutomacaoClaims
    python: Path           # Python em uso (local/python)
    novo: Path             # local/python_novo
    servidor: Path | None  # <servidor>/python


def locais(executavel: str | None = None, pasta_app: Path | None = None) -> Locais | None:
    """None quando o programa não roda do Python instalado pelo instalar.bat (ex.: desenvolvimento)."""
    exe = Path(executavel or sys.executable).resolve()
    app = Path(pasta_app or Path(__file__).resolve().parent)
    local = app.parent
    python = local / "python"
    try:
        exe.relative_to(python.resolve())
    except ValueError:
        return None
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(local / "atualizacao.ini", encoding="utf-8")
    origem = parser.get("atualizacao", "origem", fallback="").strip()
    servidor = Path(origem).parent / "python" if origem else None
    return Locais(local, python, local / "python_novo", servidor)


def _ler(arquivo: Path) -> str:
    try:
        return arquivo.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def disponivel(l: Locais | None) -> bool:
    """Há um Python diferente no servidor (e ele está completo)?"""
    if l is None or l.servidor is None:
        return False
    no_servidor = _ler(l.servidor / RUNTIME)
    if not no_servidor or not (l.servidor / "pythonw.exe").exists():
        return False
    return no_servidor != _ler(l.python / RUNTIME) and no_servidor != _ler(l.novo / COMPLETO)


def pronto_para_trocar(l: Locais | None) -> bool:
    """Já baixado e conferido (falta só reiniciar)."""
    return l is not None and (l.novo / COMPLETO).exists() and (l.novo / "pythonw.exe").exists()


def baixar(l: Locais, progresso: Callable[[int, int], None] = lambda feito, total: None,
           cancelar: Callable[[], bool] = lambda: False) -> bool:
    """Copia o Python do servidor para python_novo. True = completo e conferido; False = cancelado."""
    origem = l.servidor
    arquivos = [p for p in origem.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    total = sum(p.stat().st_size for p in arquivos)
    if l.novo.exists():
        shutil.rmtree(l.novo, ignore_errors=True)
    feito = 0
    for p in arquivos:
        if cancelar():
            shutil.rmtree(l.novo, ignore_errors=True)
            return False
        alvo = l.novo / p.relative_to(origem)
        alvo.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, alvo)
        feito += p.stat().st_size
        progresso(feito, total)
    copiados = [p for p in l.novo.rglob("*") if p.is_file()]
    if len(copiados) != len(arquivos) or sum(p.stat().st_size for p in copiados) != total:
        shutil.rmtree(l.novo, ignore_errors=True)
        raise OSError("A cópia do Python ficou incompleta. Tente de novo.")
    (l.novo / COMPLETO).write_text(_ler(origem / RUNTIME) + "\n", encoding="utf-8")
    log.info("Python novo baixado (%s arquivos, %s bytes)", len(arquivos), total)
    return True


SCRIPT_TROCA = r"""@echo off
rem Troca do Python da Automação Comercial (gerado pelo programa). Espera o programa fechar.
set "LOCAL={local}"
:espera
tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto espera
)
if exist "%LOCAL%\python_antigo" rmdir /s /q "%LOCAL%\python_antigo"
move "%LOCAL%\python" "%LOCAL%\python_antigo" >nul 2>&1
if errorlevel 1 goto abrir
move "%LOCAL%\python_novo" "%LOCAL%\python" >nul 2>&1
if errorlevel 1 (
    move "%LOCAL%\python_antigo" "%LOCAL%\python" >nul 2>&1
    goto abrir
)
del "%LOCAL%\python\{completo}" >nul 2>&1
rmdir /s /q "%LOCAL%\python_antigo"
:abrir
start "" "%LOCAL%\python\pythonw.exe" "%LOCAL%\iniciar.py"
del "%~f0"
"""


def preparar_troca(l: Locais, pid: int | None = None) -> Path:
    """Escreve o script que troca o Python depois que este programa fechar."""
    script = l.local / "trocar_python.cmd"
    script.write_text(SCRIPT_TROCA.format(local=l.local, pid=pid or os.getpid(), completo=COMPLETO),
                      encoding="cp1252", errors="replace")
    return script


def reiniciar_com_python_novo(l: Locais) -> None:
    """Dispara a troca (o programa deve fechar logo em seguida)."""
    script = preparar_troca(l)
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) \
        | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(["cmd", "/c", str(script)], creationflags=flags, close_fds=True)
    log.info("Troca do Python agendada: %s", script)
