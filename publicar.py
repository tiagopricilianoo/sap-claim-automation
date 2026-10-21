# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Publica uma nova versão no servidor (rodar na cópia de DESENVOLVIMENTO).

Uso:
    python publicar.py "\\\\servidor\\pasta\\AutomacaoClaims"
    python publicar.py "\\\\servidor\\pasta\\AutomacaoClaims" --nota "nova rota X"
    python publicar.py "\\\\servidor\\pasta\\AutomacaoClaims" --versao 2.0.0

O que faz:
1. Roda todos os testes. Se algum falhar, NADA é publicado.
2. Monta a versão de produção: só os arquivos do programa (sem testes nem
   simulador), com o settings.ini em modo de uso (AUTOMATICO, gravação ligada,
   histórico na pasta padrão de cada usuário).
3. Copia para uma pasta temporária no servidor e só então troca pela atual.
   A versão anterior fica guardada em app_anterior (para voltar, se precisar).
4. Aumenta o número da versão. Os orçamentistas recebem ao abrir o programa.
"""

from __future__ import annotations

import argparse
import getpass
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent

ARQUIVOS_DO_PROGRAMA = (
    "ui.py", "controlador.py", "claim_service.py", "config.py", "models.py", "validators.py",
    "state.py", "storage.py", "sap_gateway.py", "sap_client.py", "logger_config.py",
    "verificar_sap.py", "sobre.py", "tema.ini",
)
ASSETS = ("logo.png", "logo_40.png", "logo_80.png", "app.ico")
REQUIREMENTS_PRODUCAO = "pywin32>=312\ncustomtkinter>=5.2\n"


def proxima_versao(atual: str) -> str:
    partes = [int(p) for p in re.findall(r"\d+", atual)][:3]
    if len(partes) != 3:
        return "1.0.0"
    partes[2] += 1
    return ".".join(map(str, partes))


def settings_de_producao(texto: str) -> str:
    texto = re.sub(r"(?m)^modo\s*=.*$", "modo = AUTOMATICO", texto)
    texto = re.sub(r"(?m)^automatico_habilitado\s*=.*$", "automatico_habilitado = sim", texto)
    texto = re.sub(r"(?m)^pasta_dados\s*=.*$", "pasta_dados =", texto)
    for chave in ("modo = AUTOMATICO", "automatico_habilitado = sim"):
        if chave not in texto:
            raise ValueError(f"settings.ini sem a chave esperada: {chave.split(' ')[0]}")
    return texto


def montar_pacote(origem: Path, destino: Path, versao: str) -> None:
    """Monta em `destino` a pasta app/ completa da versão de produção."""
    destino.mkdir(parents=True)
    for nome in ARQUIVOS_DO_PROGRAMA:
        shutil.copy2(origem / nome, destino / nome)
    (destino / "assets").mkdir()
    for nome in ASSETS:
        shutil.copy2(origem / "assets" / nome, destino / "assets" / nome)
    shutil.copy2(origem / "distribuicao" / "iniciar.py", destino / "iniciar.py")
    (destino / "requirements.txt").write_text(REQUIREMENTS_PRODUCAO, encoding="utf-8")
    texto = (origem / "settings.ini").read_text(encoding="utf-8")
    (destino / "settings.ini").write_text(settings_de_producao(texto), encoding="utf-8")
    (destino / "versao.txt").write_text(versao + "\n", encoding="utf-8")   # por último


def rodar_testes() -> bool:
    print("\n  Rodando os testes...")
    return subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=RAIZ).returncode == 0


def publicar(servidor: Path, versao: str | None = None, nota: str = "", origem: Path = RAIZ) -> str:
    app, temporaria, anterior = servidor / "app", servidor / "app_publicando", servidor / "app_anterior"
    atual = ""
    if (app / "versao.txt").exists():
        atual = (app / "versao.txt").read_text(encoding="utf-8").strip()
    nova = versao or (proxima_versao(atual) if atual else "1.0.0")
    if nova == atual:
        raise ValueError(f"A versão {nova} já está publicada.")

    if temporaria.exists():
        shutil.rmtree(temporaria)
    montar_pacote(origem, temporaria, nova)

    if anterior.exists():
        shutil.rmtree(anterior)
    if app.exists():
        app.rename(anterior)
    try:
        temporaria.rename(app)
    except OSError:
        if anterior.exists() and not app.exists():
            anterior.rename(app)
        raise

    for nome in ("instalar.bat", "instalar.py", "LEIA-ME.txt"):
        shutil.copy2(origem / "distribuicao" / nome, servidor / nome)

    try:
        usuario = getpass.getuser()
    except Exception:  # noqa: BLE001
        usuario = "?"
    with open(servidor / "historico_versoes.txt", "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%d/%m/%Y %H:%M} | {nova} | {usuario} | {nota or '-'}\n")
    return nova


def main() -> int:
    argumentos = argparse.ArgumentParser(description="Publica a Automação de Claims no servidor.")
    argumentos.add_argument("servidor", help="Pasta do servidor (a que contém instalar.bat)")
    argumentos.add_argument("--versao", help="Número da versão (padrão: aumenta o último número)")
    argumentos.add_argument("--nota", default="", help="O que mudou (vai para historico_versoes.txt)")
    args = argumentos.parse_args()

    servidor = Path(args.servidor)
    if not servidor.exists():
        print(f"\n  [ERRO] Pasta não encontrada: {servidor}")
        return 1
    if not rodar_testes():
        print("\n  [BLOQUEADO] Há testes falhando. Nada foi publicado.")
        return 1
    try:
        nova = publicar(servidor, args.versao, args.nota)
    except (OSError, ValueError) as erro:
        print(f"\n  [ERRO] Publicação não concluída: {erro}")
        print("  A versão anterior continua valendo. Se alguém estiver baixando, tente de novo em instantes.")
        return 1
    print(f"\n  Versão {nova} publicada em {servidor / 'app'}.")
    print("  Os orçamentistas recebem ao abrir o programa.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
