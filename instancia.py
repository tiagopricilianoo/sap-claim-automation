# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Trava de instância única (uma janela do programa por computador)."""

from __future__ import annotations

import os


class InstanciaUnica:
    """Trava de arquivo na pasta de dados: dois programas abertos no mesmo computador poderiam resolver,
    numa janela, a execução que a outra está gravando no SAP (e liberar um claim em duplicidade).
    A trava some sozinha quando o processo termina, mesmo se ele for morto."""

    def __init__(self, pasta) -> None:
        from pathlib import Path
        self.caminho = Path(pasta) / "programa_aberto.lock"
        self._arquivo = None

    def adquirir(self) -> bool:
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        arquivo = open(self.caminho, "a+b")  # noqa: SIM115 - fica aberto enquanto o programa roda
        try:
            if os.name == "nt":
                import msvcrt
                arquivo.seek(0)
                msvcrt.locking(arquivo.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(arquivo.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            arquivo.close()
            return False
        self._arquivo = arquivo
        return True

    def liberar(self) -> None:
        if self._arquivo is not None:
            self._arquivo.close()
            self._arquivo = None
