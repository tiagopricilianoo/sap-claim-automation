# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Verificação SOMENTE LEITURA da conexão com o SAP.

Mostra todas as sessões abertas e de qual delas a automação abriria a sua
janela própria. Não abre janela, não clica, não digita e não altera nada.

Uso:  python verificar_sap.py
"""

from __future__ import annotations

import sys

from config import ConfigError, load_settings
from logger_config import configurar_logs
from sap_client import SapClient
from sap_gateway import SapError


def main() -> int:
    try:
        settings = load_settings()
    except ConfigError as erro:
        print(f"[ERRO] Configuração: {erro}")
        return 2
    configurar_logs(settings.pasta_dados)

    print(f"Alvo configurado: sistema {settings.sistema}, mandante {settings.mandante}\n")
    cliente = SapClient(settings)
    try:
        base = cliente.diagnostico()
        falha = None
    except SapError as erro:
        base, falha = None, f"[BLOQUEADO] {erro}"

    if cliente.todas:
        print("Sessões encontradas:")
        for s in cliente.todas:
            marca = "  <== base para abrir a janela da automação" if base == s else ""
            estado = "ocupada" if s.info.ocupada else "livre"
            print(f"  {s.rotulo}: {s.info.sistema}/{s.info.mandante} | usuário {s.info.usuario or '-'} | "
                  f"transação {s.info.transacao or '-'} | {estado}{marca}")
        print()

    if base:
        print(f"[OK] A automação abrirá uma janela própria para o usuário {base.info.usuario}.")
        print("     Suas janelas não serão usadas nem alteradas.")
        return 0
    print(falha)
    return 1


if __name__ == "__main__":
    sys.exit(main())
