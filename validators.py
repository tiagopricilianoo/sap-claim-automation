# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Validações locais executadas ANTES de qualquer interação com o SAP.

Nenhuma função aqui corrige valores: só aponta o problema.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from config import Settings
from models import ClaimRequest


@dataclass(frozen=True)
class ValidationIssue:
    campo: str
    mensagem: str


def _validar_numero(nome: str, valor: str, maximo: int) -> list[ValidationIssue]:
    if not valor:
        return [ValidationIssue(nome, "Campo obrigatório.")]
    if not valor.isdigit() or not valor.isascii():
        return [ValidationIssue(nome, "Use somente dígitos (0-9), sem espaços, pontos ou letras.")]
    if len(valor) > maximo:
        return [ValidationIssue(nome, f"Máximo de {maximo} dígitos (informado: {len(valor)}).")]
    return []


def _validar_arquivo(req: ClaimRequest, settings: Settings) -> list[ValidationIssue]:
    campo = "arquivo"
    caminho = req.arquivo
    if req.sem_anexo:
        if caminho is not None:
            return [ValidationIssue(campo, "Há um arquivo selecionado, mas a opção 'Este claim não tem anexo' "
                                           "está marcada. Remova o arquivo ou desmarque a opção.")]
        return []
    if caminho is None:
        return [ValidationIssue(campo, "Selecione o arquivo a anexar (vários arquivos: junte em um ZIP) ou "
                                       "marque 'Este claim não tem anexo'.")]
    if not caminho.exists():
        return [ValidationIssue(campo, "Arquivo não encontrado no caminho informado.")]
    if not caminho.is_file():
        return [ValidationIssue(campo, "O caminho aponta para uma pasta, não para um arquivo.")]
    try:
        tamanho = caminho.stat().st_size
        with caminho.open("rb") as f:
            f.read(1)
    except OSError:
        return [ValidationIssue(campo, "Não foi possível ler o arquivo (aberto em outro programa ou sem permissão?).")]
    if tamanho == 0:
        return [ValidationIssue(campo, "O arquivo está vazio.")]

    maximo = settings.limites.descricao_documento_max
    import unicodedata
    tamanho_nome = tamanho_sap(unicodedata.normalize("NFC", caminho.name))     # como o SAP conta (UTF-16)
    if tamanho_nome > maximo:
        return [ValidationIssue(
            campo,
            f"O nome do arquivo vira a descrição do documento e pode ter até {maximo} "
            f"caracteres (atual: {tamanho_nome}; emoji conta 2). Renomeie o arquivo.",
        )]
    return []


def tamanho_sap(texto: str) -> int:
    """Tamanho como o SAP conta (UTF-16): emoji e outros símbolos fora do BMP ocupam 2 posições."""
    return len(texto.encode("utf-16-le")) // 2


def validate(req: ClaimRequest, settings: Settings) -> list[ValidationIssue]:
    """Retorna a lista de problemas encontrados. Lista vazia = dados válidos."""
    problemas: list[ValidationIssue] = []

    if not req.tipo:
        problemas.append(ValidationIssue("tipo", "Escolha o tipo de claim."))
    elif req.tipo not in settings.rotas:
        problemas.append(ValidationIssue("tipo", f"Tipo de claim desconhecido: {req.tipo!r}."))

    if not req.descricao:
        problemas.append(ValidationIssue("descricao", "Campo obrigatório."))
    elif any(unicodedata.category(c) == "Cc" for c in req.descricao):
        problemas.append(ValidationIssue("descricao", "A descrição é uma linha só: sem quebra de linha, tabulação "
                                         "ou caractere invisível (comum ao colar de PDF)."))
    elif tamanho_sap(req.descricao) > settings.limites.descricao_max:
        problemas.append(ValidationIssue(
            "descricao",
            f"Máximo de {settings.limites.descricao_max} caracteres (informado: {tamanho_sap(req.descricao)}; "
            "emoji conta 2).",
        ))

    if not req.texto_livre:
        problemas.append(ValidationIssue("texto_livre", "Campo obrigatório."))

    problemas += _validar_numero("ordem", req.ordem, settings.limites.ordem_max)
    if req.linha_nova:
        rota = settings.rotas.get(req.tipo)
        if rota is not None and not rota.material:
            problemas.append(ValidationIssue(
                "item", f"O tipo '{rota.rotulo}' não tem material de linha nova no settings.ini."))
    else:
        problemas += _validar_numero("item", req.item, settings.limites.item_max)
        if not problemas or problemas[-1].campo != "item":
            if req.item.strip("0") == "" and req.item:
                problemas.append(ValidationIssue("item", "O item 0 é o cabeçalho da cotação: informe o item da linha "
                                                 "(10, 20…)."))
    problemas += _validar_arquivo(req, settings)
    return problemas
