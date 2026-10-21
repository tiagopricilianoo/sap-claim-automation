# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Leitura e validação do settings.ini.

Nenhum valor de negócio fica no código: tudo que é fixo no processo
(tipo de nota, causa, prioridade, documento, rotas de atividades)
vem deste arquivo.
"""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field
from pathlib import Path

USUARIO_LOGADO = "@usuario_logado"
MODOS = ("SIMULACAO", "ENSAIO", "ASSISTIDO", "AUTOMATICO")
CAMINHO_PADRAO = Path(__file__).with_name("settings.ini")


class ConfigError(Exception):
    """Configuração ausente, incompleta ou inconsistente."""


@dataclass(frozen=True)
class ActivityConfig:
    chave: str
    descricao: str
    subgrupo: str
    pasta: str
    no: str
    responsavel: str  # "" = SAP preenche | USUARIO_LOGADO | usuário fixo

    def responsavel_para(self, usuario_logado: str) -> str:
        """Responsável final da atividade, resolvendo @usuario_logado."""
        if self.responsavel == USUARIO_LOGADO:
            return usuario_logado.strip().upper()
        return self.responsavel.upper()


@dataclass(frozen=True)
class RouteConfig:
    chave: str
    rotulo: str
    atividades: tuple[ActivityConfig, ...]


@dataclass(frozen=True)
class Limits:
    descricao_max: int
    descricao_documento_max: int
    ordem_max: int
    item_max: int


@dataclass(frozen=True)
class Settings:
    sistema: str
    mandante: str
    tipo_nota: str
    causa_grupo: str
    causa_codigo: str
    prioridade: str
    doc_tipo: str
    doc_laboratorio: str
    doc_aplicacao: str
    raiz_arvore: str
    modo: str
    automatico_habilitado: bool
    limites: Limits
    avisos_aceitos: tuple[str, ...]
    rotas: dict[str, RouteConfig] = field(default_factory=dict)
    pasta_dados: Path = Path(".")

    def rota(self, chave: str) -> RouteConfig:
        try:
            return self.rotas[chave]
        except KeyError:
            raise ConfigError(f"Rota desconhecida: {chave!r}") from None


def _pasta_dados_padrao() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "ClaimAutomation"
    return Path.home() / ".claim_automation"


def _obrigatorio(parser: configparser.ConfigParser, secao: str, chave: str) -> str:
    if not parser.has_section(secao):
        raise ConfigError(f"Seção [{secao}] ausente no settings.ini")
    valor = parser.get(secao, chave, fallback="").strip()
    if not valor:
        raise ConfigError(f"Valor obrigatório vazio: [{secao}] {chave}")
    return valor


def _opcional(parser: configparser.ConfigParser, secao: str, chave: str) -> str:
    return parser.get(secao, chave, fallback="").strip()


def _inteiro(parser: configparser.ConfigParser, secao: str, chave: str) -> int:
    texto = _obrigatorio(parser, secao, chave)
    try:
        valor = int(texto)
    except ValueError:
        raise ConfigError(f"[{secao}] {chave} deve ser um número inteiro: {texto!r}") from None
    if valor <= 0:
        raise ConfigError(f"[{secao}] {chave} deve ser maior que zero")
    return valor


def _sim_nao(parser: configparser.ConfigParser, secao: str, chave: str) -> bool:
    texto = _opcional(parser, secao, chave).lower()
    if texto in ("sim", "s", "true", "1"):
        return True
    if texto in ("", "nao", "não", "n", "false", "0"):
        return False
    raise ConfigError(f"[{secao}] {chave} deve ser 'sim' ou 'nao': {texto!r}")


def _carregar_atividades(parser: configparser.ConfigParser) -> dict[str, ActivityConfig]:
    atividades: dict[str, ActivityConfig] = {}
    for secao in parser.sections():
        if not secao.startswith("atividade."):
            continue
        chave = secao.split(".", 1)[1].strip().lower()
        atividades[chave] = ActivityConfig(
            chave=chave,
            descricao=_obrigatorio(parser, secao, "descricao"),
            subgrupo=_opcional(parser, secao, "subgrupo"),
            pasta=_obrigatorio(parser, secao, "pasta"),
            no=_opcional(parser, secao, "no"),   # só referência: o item é achado pelo texto
            responsavel=_opcional(parser, secao, "responsavel"),
        )
    return atividades


def _carregar_rotas(
    parser: configparser.ConfigParser, atividades: dict[str, ActivityConfig]
) -> dict[str, RouteConfig]:
    rotas: dict[str, RouteConfig] = {}
    for secao in parser.sections():
        if not secao.startswith("rota."):
            continue
        chave = secao.split(".", 1)[1].strip()
        nomes = [n.strip().lower() for n in _obrigatorio(parser, secao, "atividades").split(",")]
        nomes = [n for n in nomes if n]
        if not nomes:
            raise ConfigError(f"[{secao}] não tem atividades")
        faltando = [n for n in nomes if n not in atividades]
        if faltando:
            raise ConfigError(f"[{secao}] referencia atividades inexistentes: {', '.join(faltando)}")
        if len(set(nomes)) != len(nomes):
            raise ConfigError(f"[{secao}] repete a mesma atividade")
        rotas[chave] = RouteConfig(
            chave=chave,
            rotulo=_obrigatorio(parser, secao, "rotulo"),
            atividades=tuple(atividades[n] for n in nomes),
        )
    if not rotas:
        raise ConfigError("Nenhuma rota [rota.*] definida no settings.ini")
    return rotas


def load_settings(caminho: Path | str = CAMINHO_PADRAO) -> Settings:
    caminho = Path(caminho)
    parser = configparser.ConfigParser(interpolation=None)
    if not parser.read(caminho, encoding="utf-8"):
        raise ConfigError(f"Arquivo de configuração não encontrado: {caminho}")

    modo = _obrigatorio(parser, "execucao", "modo").upper()
    if modo not in MODOS:
        raise ConfigError(f"Modo inválido: {modo!r}. Use um de: {', '.join(MODOS)}")
    automatico = _sim_nao(parser, "execucao", "automatico_habilitado")
    if modo == "AUTOMATICO" and not automatico:
        raise ConfigError("Modo AUTOMATICO exige [execucao] automatico_habilitado = sim")

    pasta = _opcional(parser, "armazenamento", "pasta_dados")
    avisos = tuple(
        v.strip() for _, v in parser.items("avisos_aceitos") if v.strip()
    ) if parser.has_section("avisos_aceitos") else ()

    atividades = _carregar_atividades(parser)

    return Settings(
        sistema=_obrigatorio(parser, "sap", "sistema").upper(),
        mandante=_obrigatorio(parser, "sap", "mandante"),
        tipo_nota=_obrigatorio(parser, "nota", "tipo_nota"),
        causa_grupo=_obrigatorio(parser, "nota", "causa_grupo"),
        causa_codigo=_obrigatorio(parser, "nota", "causa_codigo"),
        prioridade=_obrigatorio(parser, "nota", "prioridade"),
        doc_tipo=_obrigatorio(parser, "documento", "tipo"),
        doc_laboratorio=_obrigatorio(parser, "documento", "laboratorio"),
        doc_aplicacao=_obrigatorio(parser, "documento", "aplicacao"),
        raiz_arvore=_obrigatorio(parser, "arvore_atividades", "raiz"),
        modo=modo,
        automatico_habilitado=automatico,
        limites=Limits(
            descricao_max=_inteiro(parser, "limites", "descricao_max"),
            descricao_documento_max=_inteiro(parser, "limites", "descricao_documento_max"),
            ordem_max=_inteiro(parser, "limites", "ordem_max"),
            item_max=_inteiro(parser, "limites", "item_max"),
        ),
        avisos_aceitos=avisos,
        rotas=_carregar_rotas(parser, atividades),
        pasta_dados=Path(pasta) if pasta else _pasta_dados_padrao(),
    )


def pendencias_configuracao(settings: Settings) -> list[str]:
    """Problemas que não impedem carregar o arquivo, mas impedem executar a rota no SAP.

    Ex.: duas atividades da mesma rota com a mesma descrição e sem sub grupo
    para diferenciá-las na grade (a automação não saberia qual linha é qual).
    """
    problemas: list[str] = []
    for rota in settings.rotas.values():
        vistos: dict[tuple[str, str], str] = {}
        for atv in rota.atividades:
            chave = (atv.descricao.upper(), atv.subgrupo.upper())
            if chave in vistos:
                problemas.append(
                    f"Rota {rota.chave}: atividades '{vistos[chave]}' e '{atv.chave}' "
                    f"não se distinguem na grade (mesma descrição e sub grupo)"
                )
            vistos[chave] = atv.chave
    return problemas
