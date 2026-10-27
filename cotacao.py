# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Cotação nova (VA21): dados do formulário, validação e o plano do que será criado.

Regras vindas do programa "Criar Cotação" (usado até out/2026), com uma mudança
decidida em 26/10/2026: Produto A e Produto B marcados juntos geram UMA cotação (dados
de Produto A) com DUAS linhas, em vez de só a de Produto A. Gerador: ainda não disponível.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

from config import CotacaoConfig, Settings, TipoCotacao
from validators import ValidationIssue

REGIOES_BRASIL = ("Centro Oeste", "Nordeste", "Norte", "Sudeste", "Sul")
REGIOES_EXPORTACAO = ("América do Sul", "América Central", "América do Norte", "África", "Ásia", "Europa", "Oceania")
PAISES_POR_REGIAO: dict[str, tuple[str, ...]] = {
    "América do Sul": (
        "Argentina", "Bolivia", "Chile", "Colombia", "Equador", "Guiana", "Paraguai", "Peru", "Suriname",
        "Uruguai", "Venezuela",
    ),
    "América Central": (
        "Belize", "Costa Rica", "El Salvador", "Guatemala", "Honduras", "Nicaragua", "Panama",
        "Antigua e Barbuda", "Bahamas", "Barbados", "Cuba", "Dominica", "Republica Dominicana", "Granada",
        "Haiti", "Jamaica", "Sao Cristovao e Nevis", "Santa Lucia", "Sao Vicente e Granadinas",
        "Trindade e Tobago",
    ),
    "América do Norte": (
        "Canada", "Mexico", "Estados Unidos",
    ),
    "Oceania": (
        "Australia", "Fiji", "Kiribati", "Ilhas Marshall", "Micronesia", "Nauru", "Nova Zelandia", "Palau",
        "Papua Nova Guine", "Samoa", "Ilhas Salomao", "Tonga", "Tuvalu", "Vanuatu",
    ),
    "Ásia": (
        "Afeganistao", "Armenia", "Azerbaijao", "Bahrein", "Bangladesh", "Butao", "Brunei", "Camboja",
        "China", "Chipre", "Georgia", "India", "Indonesia", "Ira", "Iraque", "Israel", "Japao", "Jordania",
        "Cazaquistao", "Kuwait", "Quirguistao", "Laos", "Libano", "Malasia", "Maldivas", "Mongolia",
        "Mianmar", "Nepal", "Coreia do Norte", "Oma", "Paquistao", "Palestina", "Filipinas", "Catar",
        "Arabia Saudita", "Singapura", "Coreia do Sul", "Sri Lanka", "Siria", "Taiwan", "Tajiquistao",
        "Tailandia", "Timor-Leste", "Turquia", "Turcomenistao", "Emirados Arabes Unidos", "Uzbequistao",
        "Vietna", "Iemen",
    ),
    "África": (
        "Argelia", "Angola", "Benin", "Botswana", "Burkina Faso", "Burundi", "Camaroes", "Cabo Verde",
        "Republica Centro-Africana", "Chade", "Comores", "Congo", "Djibuti", "Egito", "Guine Equatorial",
        "Eritreia", "Essuatini", "Etiopia", "Gabao", "Gambia", "Gana", "Guine", "Guine-Bissau",
        "Costa do Marfim", "Quenia", "Lesoto", "Liberia", "Libia", "Madagascar", "Malawi", "Mali",
        "Mauritania", "Mauricio", "Marrocos", "Mocambique", "Namibia", "Niger", "Nigeria", "Ruanda",
        "Sao Tome e Principe", "Senegal", "Seicheles", "Serra Leoa", "Somalia", "Africa do Sul",
        "Sudao do Sul", "Sudao", "Tanzania", "Togo", "Tunisia", "Uganda", "Zambia", "Zimbabue",
    ),
    "Europa": (
        "Albania", "Andorra", "Austria", "Bielorrussia", "Belgica", "Bosnia e Herzegovina", "Bulgaria",
        "Croacia", "Republica Tcheca", "Dinamarca", "Estonia", "Finlandia", "Franca", "Alemanha", "Grecia",
        "Hungria", "Islandia", "Irlanda", "Italia", "Kosovo", "Letonia", "Liechtenstein", "Lituania",
        "Luxemburgo", "Malta", "Moldavia", "Monaco", "Montenegro", "Paises Baixos", "Macedonia do Norte",
        "Noruega", "Polonia", "Portugal", "Romenia", "Russia", "San Marino", "Servia", "Eslovaquia",
        "Eslovenia", "Espanha", "Suecia", "Suica", "Ucrania", "Reino Unido", "Vaticano",
    ),
}

MAX_NOME_PASTA = 50
MAX_ENDERECO = 15          # o programa anterior cortava cliente/projeto em 15 no SAP
CARACTERES_PROIBIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
NOMES_RESERVADOS = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
                    *(f"COM{i}" for i in "0123456789¹²³"), *(f"LPT{i}" for i in "0123456789¹²³")}
ESPECIAL_REGIAO, ESPECIAL_PAIS = "Europa", "Cliente Especial"


def _limpar(valor: object) -> str:
    # NFC: texto colado de PDF/Mac vem decomposto (c + cedilha) e contaria o dobro de letras.
    return "" if valor is None else unicodedata.normalize("NFC", " ".join(str(valor).split()))


@dataclass(frozen=True)
class CotacaoRequest:
    tipo: str            # Nacional | Exportação | Cliente Especial
    regiao: str
    pais: str
    cliente: str
    projeto: str
    produto_a: bool
    produto_b: bool

    @classmethod
    def from_form(cls, *, tipo: object, regiao: object = "", pais: object = "", cliente: object = "",
                  projeto: object = "", produto_a: object = False, produto_b: object = False) -> "CotacaoRequest":
        tipo = _limpar(tipo)
        regiao, pais, cliente = _limpar(regiao), _limpar(pais), _limpar(cliente)
        if tipo == "Cliente Especial":
            regiao, pais, cliente = ESPECIAL_REGIAO, ESPECIAL_PAIS, ""
        return cls(tipo=tipo, regiao=regiao, pais=pais, cliente=cliente.rstrip(". "),
                   projeto=_limpar(projeto).rstrip(". "), produto_a=bool(produto_a), produto_b=bool(produto_b))

    @property
    def equipamentos(self) -> str:
        return " + ".join(n for n, ok in (("Produto A", self.produto_a), ("Produto B", self.produto_b)) if ok)


@dataclass(frozen=True)
class LinhaCotacao:
    equipamento: str     # Produto A | Produto B
    rota: str            # rota do claim correspondente (PRODUTO_A | PRODUTO_B)
    material: str
    centro: str
    quantidade: str


@dataclass(frozen=True)
class PlanoCotacao:
    """Tudo o que será digitado na VA21, calculado ANTES de tocar no SAP (mostrado na tela)."""
    tipo: TipoCotacao
    principal: str                 # TU | TR: define equipe e pasta
    equipe: str
    nome_endereco: str
    cidade: str
    referencia: str
    validade: date
    recebimento: date
    linhas: tuple[LinhaCotacao, ...] = field(default_factory=tuple)


def tipos_disponiveis(settings: Settings) -> tuple[str, ...]:
    return tuple(settings.cotacao.tipos) if settings.cotacao else ()


def regioes_do_tipo(tipo: str) -> tuple[str, ...]:
    if tipo == "Nacional":
        return REGIOES_BRASIL
    if tipo == "Exportação":
        return REGIOES_EXPORTACAO
    return ()


def _validar_nome(campo: str, rotulo: str, valor: str) -> list[ValidationIssue]:
    if not valor:
        return [ValidationIssue(campo, f"Informe {rotulo.lower()}.")]
    if CARACTERES_PROIBIDOS.search(valor):
        return [ValidationIssue(campo, 'Sem os caracteres < > : " / \\ | ? * (o nome vira pasta na rede).')]
    if len(valor) > MAX_NOME_PASTA:
        return [ValidationIssue(campo, f"Máximo de {MAX_NOME_PASTA} caracteres (informado: {len(valor)}).")]
    if valor.split(".")[0].strip().upper() in NOMES_RESERVADOS:
        return [ValidationIssue(campo, "Nome reservado pelo Windows; escolha outro.")]
    return []


def validar_cotacao(req: CotacaoRequest, settings: Settings) -> list[ValidationIssue]:
    cfg = settings.cotacao
    if cfg is None:
        return [ValidationIssue("tipo", "Criação de cotação não configurada no settings.ini ([cotacao]).")]
    problemas: list[ValidationIssue] = []
    tipo = cfg.tipos.get(req.tipo)
    if tipo is None:
        problemas.append(ValidationIssue("tipo", "Escolha o tipo de cotação."))
    else:
        if tipo.pede_regiao and req.regiao not in regioes_do_tipo(req.tipo):
            problemas.append(ValidationIssue("regiao", "Escolha a região."))
        if tipo.pede_pais and req.pais not in PAISES_POR_REGIAO.get(req.regiao, ()):
            problemas.append(ValidationIssue("pais", "Escolha o país."))
        if tipo.pede_cliente:
            problemas += _validar_nome("cliente", "o cliente", req.cliente)
    problemas += _validar_nome("projeto", "o projeto", req.projeto)
    if not (req.produto_a or req.produto_b):
        problemas.append(ValidationIssue("equipamentos", "Marque Produto A, Produto B ou os dois."))
    return problemas


def _mais_meses(dia: date, meses: int) -> date:
    ano, mes = divmod(dia.month - 1 + meses, 12)
    ano, mes = dia.year + ano, mes + 1
    for d in (dia.day, 28):
        try:
            return date(ano, mes, d)
        except ValueError:
            continue
    return date(ano, mes, 28)


def planejar(req: CotacaoRequest, settings: Settings, hoje: date | None = None) -> PlanoCotacao:
    """O plano da VA21 para um formulário já validado."""
    cfg: CotacaoConfig = settings.cotacao
    tipo = cfg.tipos[req.tipo]
    hoje = hoje or date.today()
    linhas = []
    for marcado, nome, rota in ((req.produto_a, "Produto A", cfg.rota_produto_a), (req.produto_b, "Produto B", cfg.rota_produto_b)):
        if marcado:
            r = settings.rota(rota)
            linhas.append(LinhaCotacao(nome, rota, r.material, r.centro, settings.linha_quantidade))
    principal = "TU" if req.produto_a else "TR"
    return PlanoCotacao(
        tipo=tipo,
        principal=principal,
        equipe=tipo.equipe_produto_a if principal == "TU" else tipo.equipe_produto_b,
        nome_endereco=tipo.nome_cliente_fixo or req.cliente,
        cidade=req.projeto[:MAX_ENDERECO].strip(),
        # Sem cliente (Cliente Especial), só o projeto: nada de " - K-77" com o traço solto.
        referencia=" - ".join(p for p in (req.cliente[:MAX_ENDERECO].strip(), req.projeto[:MAX_ENDERECO].strip())
                              if p),
        validade=_mais_meses(hoje, cfg.validade_meses),
        recebimento=hoje,
        linhas=tuple(linhas),
    )


def resumo_plano(plano: PlanoCotacao, settings: Settings) -> list[str]:
    """Linhas legíveis do que será criado (prévia na tela e registro no histórico)."""
    cfg = settings.cotacao
    resumo = [
        f"Cotação {cfg.tipo_documento} · org. {cfg.organizacao}/{cfg.canal}/{plano.tipo.setor} · "
        f"escritório {cfg.escritorio} · equipe {plano.equipe}",
        f"Emissor {plano.tipo.emissor} · endereço \"{plano.nome_endereco}\" / \"{plano.cidade}\"",
        f"Válida até {plano.validade:%d/%m/%Y} · referência \"{plano.referencia}\"",
    ]
    for i, linha in enumerate(plano.linhas, 1):
        resumo.append(f"Linha {i * 10}: {linha.equipamento} · material {linha.material} · centro {linha.centro} "
                      f"· qtd {linha.quantidade}")
    return resumo
