# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Instalação da Automação de Claims, executada A PARTIR DA PASTA DO SERVIDOR.

- Instala as bibliotecas.
- Cria %LOCALAPPDATA%\\AutomacaoClaims com o inicializador e o endereço do servidor.
- Baixa a versão atual.
- Cria o atalho na área de trabalho.

Rodar de novo é seguro: serve também para reparar uma instalação.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

PASTA_SERVIDOR = Path(__file__).resolve().parent
ORIGEM = PASTA_SERVIDOR / "app"
LOCAL = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AutomacaoClaims"
NOME_ATALHO = "Automacao de Claims.lnk"


def caminho_universal(caminho: Path) -> Path:
    """Z:\\pasta -> \\\\servidor\\compartilhamento\\pasta (letras de unidade variam entre PCs)."""
    try:
        import win32wnet  # pywin32
        return Path(win32wnet.WNetGetUniversalName(str(caminho), 1))
    except Exception:  # noqa: BLE001 - já é UNC, ou não é unidade de rede
        return caminho


def passo(texto: str) -> None:
    print(f"\n  {texto}")


def main() -> int:
    print("\n  ===============================================")
    print("   Automação de Claims (CLM1) - instalação")
    print("  ===============================================")

    if not (ORIGEM / "ui.py").exists():
        print(f"\n  [ERRO] Programa não encontrado em {ORIGEM}")
        return 1

    if "--python-embutido" in sys.argv:
        passo("1/4  Python do programa copiado (bibliotecas já incluídas).")
    else:
        passo("1/4  Instalando bibliotecas...")
        if subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(ORIGEM / "requirements.txt"),
                           "--disable-pip-version-check"]).returncode != 0:
            print("\n  [ERRO] Não foi possível instalar as bibliotecas. Verifique a internet/proxy.")
            return 1

    passo("2/4  Preparando a pasta local...")
    LOCAL.mkdir(parents=True, exist_ok=True)
    origem = caminho_universal(ORIGEM)
    (LOCAL / "atualizacao.ini").write_text(
        "; Pasta do servidor de onde o programa se atualiza ao abrir.\n"
        f"[atualizacao]\norigem = {origem}\n",
        encoding="utf-8",
    )
    shutil.copy2(ORIGEM / "iniciar.py", LOCAL / "iniciar.py")
    print(f"       Atualizações virão de: {origem}")

    passo("3/4  Baixando a versão atual...")
    sys.path.insert(0, str(LOCAL))
    import iniciar  # noqa: E402 - o inicializador recém-copiado
    print("       " + iniciar.atualizar(origem, LOCAL))

    passo("4/4  Criando o atalho na área de trabalho...")
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.exists():
        pythonw = Path(sys.executable)
    try:
        import win32com.client  # pywin32
        shell = win32com.client.Dispatch("WScript.Shell")
        atalho = shell.CreateShortCut(str(Path(shell.SpecialFolders("Desktop")) / NOME_ATALHO))
        atalho.TargetPath = str(pythonw)
        atalho.Arguments = f'"{LOCAL / "iniciar.py"}"'
        atalho.WorkingDirectory = str(LOCAL)
        atalho.IconLocation = f"{LOCAL / 'app' / 'assets' / 'app.ico'},0"
        atalho.Description = "Automação de Claims - CLM1"
        atalho.save()
        print("       Atalho criado.")
    except Exception as erro:  # noqa: BLE001
        print(f"       [AVISO] Atalho não criado ({erro}).")
        print(f"       Abra pelo arquivo: {LOCAL / 'iniciar.py'}")

    print("\n  Instalação concluída. Use o atalho 'Automacao de Claims' na área de trabalho.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
