# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Estruturas de dados do claim, independentes do SAP e da interface."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from pathlib import Path


def _limpar_pontas(valor: object) -> str:
    """Remove espaços apenas no início e no fim. Nunca altera o conteúdo."""
    # NFC só junta letra + acento decompostos (texto colado de PDF/Mac); o que o usuário vê não muda.
    return "" if valor is None else unicodedata.normalize("NFC", str(valor).strip())


def normalizar_numero(valor: str) -> str:
    """'01234567' -> '1234567', '010' -> '10'. O SAP guarda ordem (ALPHA) e item (NUMC) com zeros à
    esquerda, então '010' e '10' são o MESMO item: a duplicidade tem que comparar sem eles.
    Valores que não são só dígitos ficam como estão (a validação recusa)."""
    if valor and valor.isdigit() and valor.isascii():
        return valor.lstrip("0") or "0"
    return valor


def _normalizar_texto_livre(valor: object) -> str:
    """Padroniza quebras de linha e remove linhas vazias só nas pontas."""
    texto = "" if valor is None else str(valor)
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    return texto.strip()


@dataclass(frozen=True)
class ClaimRequest:
    """Dados digitados pelo orçamentista para um claim."""

    tipo: str            # chave da rota: PRODUTO_A | PRODUTO_B | PRODUTO_B_CUSTO
    descricao: str
    texto_livre: str
    ordem: str
    item: str
    arquivo: Path | None
    sem_anexo: bool = False   # escolha explícita: claim sem anexo (pula o documento)
    linha_nova: bool = False  # cria antes uma linha nova na cotação (VA22); o item vem do SAP
    confirmar_linha_extra: bool = False   # o usuário confirmou mais uma linha logo depois de outra

    @classmethod
    def from_form(
        cls,
        *,
        tipo: object,
        descricao: object,
        texto_livre: object,
        ordem: object,
        item: object,
        arquivo: object,
        sem_anexo: object = False,
        linha_nova: object = False,
    ) -> "ClaimRequest":
        linha_nova = bool(linha_nova)
        # O caminho NÃO passa por NFC: o disco guarda o nome como veio (NFD de zip do Mac, por ex.).
        caminho = ("" if arquivo is None else str(arquivo).strip()).strip('"')
        return cls(
            tipo=_limpar_pontas(tipo),
            descricao=_limpar_pontas(descricao),
            texto_livre=_normalizar_texto_livre(texto_livre),
            ordem=normalizar_numero(_limpar_pontas(ordem)),
            item="" if linha_nova else normalizar_numero(_limpar_pontas(item)),
            arquivo=Path(caminho) if caminho else None,
            sem_anexo=bool(sem_anexo),
            linha_nova=linha_nova,
        )

    @property
    def nome_arquivo(self) -> str:
        return self.arquivo.name if self.arquivo else ""

    def normalizado(self) -> "ClaimRequest":
        """Mesma requisição com ordem e item sem zeros à esquerda."""
        from dataclasses import replace
        return replace(self, ordem=normalizar_numero(self.ordem), item=normalizar_numero(self.item))
