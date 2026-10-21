# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Estruturas de dados do claim, independentes do SAP e da interface."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def _limpar_pontas(valor: object) -> str:
    """Remove espaços apenas no início e no fim. Nunca altera o conteúdo."""
    return "" if valor is None else str(valor).strip()


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
    ) -> "ClaimRequest":
        caminho = _limpar_pontas(arquivo).strip('"')
        return cls(
            tipo=_limpar_pontas(tipo),
            descricao=_limpar_pontas(descricao),
            texto_livre=_normalizar_texto_livre(texto_livre),
            ordem=_limpar_pontas(ordem),
            item=_limpar_pontas(item),
            arquivo=Path(caminho) if caminho else None,
            sem_anexo=bool(sem_anexo),
        )

    @property
    def nome_arquivo(self) -> str:
        return self.arquivo.name if self.arquivo else ""

    @property
    def chave_duplicidade(self) -> tuple[str, str]:
        """Ordem + item: usada para procurar claims já criados."""
        return (self.ordem, self.item)
