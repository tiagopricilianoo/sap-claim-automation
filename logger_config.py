# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Configuração de logs operacionais.

Regra de uso: logar etapas, estados, números de documento/nota e mensagens
técnicas do SAP. NUNCA logar o texto livre, o conteúdo do anexo ou senhas.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

FORMATO = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def configurar_logs(pasta_dados: Path, nivel: int = logging.INFO) -> logging.Logger:
    pasta_logs = Path(pasta_dados) / "logs"
    pasta_logs.mkdir(parents=True, exist_ok=True)

    raiz = logging.getLogger("claim")
    raiz.setLevel(nivel)
    if raiz.handlers:  # evita duplicar handlers ao reconfigurar
        return raiz

    arquivo = RotatingFileHandler(
        pasta_logs / "claim_automation.log",
        maxBytes=2_000_000,
        backupCount=10,
        encoding="utf-8",
    )
    arquivo.setFormatter(logging.Formatter(FORMATO))
    raiz.addHandler(arquivo)

    if sys.stderr is not None:   # sem console (pythonw / atalho), só o arquivo
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(FORMATO))
        raiz.addHandler(console)
    return raiz
