# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
import re
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from config import load_settings  # noqa: E402
from models import ClaimRequest  # noqa: E402


def texto_settings_padrao() -> str:
    """O settings.ini real, com as travas de execução sempre no padrão.

    Os testes não podem depender da configuração de uso (ex.: o usuário
    habilitou a gravação para operar): tudo o mais vem do arquivo real.
    """
    texto = (RAIZ / "settings.ini").read_text(encoding="utf-8")
    texto = re.sub(r"(?m)^modo\s*=.*$", "modo = SIMULACAO", texto)
    return re.sub(r"(?m)^automatico_habilitado\s*=.*$", "automatico_habilitado = nao", texto)


@pytest.fixture
def settings(tmp_path):
    caminho = tmp_path / "settings_teste.ini"
    caminho.write_text(texto_settings_padrao(), encoding="utf-8")
    return load_settings(caminho)


@pytest.fixture
def arquivo_pdf(tmp_path):
    caminho = tmp_path / "Proposta_teste.pdf"
    caminho.write_bytes(b"%PDF-1.4 conteudo ficticio")
    return caminho


@pytest.fixture
def request_valido(arquivo_pdf):
    return ClaimRequest.from_form(
        tipo="PRODUTO_A",
        descricao="Consulta tecnica de teste",
        texto_livre="Linha 1\nLinha 2",
        ordem="1234567",
        item="10",
        arquivo=str(arquivo_pdf),
    )
