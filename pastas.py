# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Pastas da proposta na rede, planilhas padrão e atalhos (portado do programa "Criar Cotação").

Duas fases, como no programa anterior:
1. planejar_pastas: ANTES do SAP. Resolve o caminho do cliente/projeto, pergunta se um
   cliente com nome parecido é o mesmo e CANCELA se o projeto já tem pasta (evita
   cotação repetida). Nada é criado.
2. criar_pastas: DEPOIS de a cotação ser gravada. Cria R.0 e R.X, copia as planilhas
   e cria os atalhos. Arquivos que já existem são preservados.
"""

from __future__ import annotations

import logging
import re
import shutil
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

from config import CotacaoConfig
from cotacao import ESPECIAL_PAIS, ESPECIAL_REGIAO, CotacaoRequest

log = logging.getLogger("claim.pastas")
MAX_CAMINHO = 240

Perguntar = Callable[[str, str], bool]          # (título, texto) -> sim/não
CriarAtalho = Callable[[Path, str], None]       # (arquivo .lnk, pasta de destino)


class ProjetoJaExiste(Exception):
    """Já existe pasta para este cliente/projeto: o fluxo para antes do SAP."""


class CaminhoMuitoLongo(Exception):
    pass


@dataclass(frozen=True)
class PlanoPastas:
    modelo: str          # TU | TR | ESPECIAL
    base: Path           # pasta R.0 (a que vai no e-mail)
    revisao_x: Path | None
    raiz_produto_a: Path
    raiz_produto_b: Path
    ano: int


# ------------------------------------------------------------------------ nomes

def nome_comparavel(valor: str) -> str:
    sem_acento = "".join(c for c in unicodedata.normalize("NFKD", valor) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sem_acento).strip().casefold()


def _semelhanca(a: str, b: str) -> float:
    pa, pb = set(nome_comparavel(a).split()), set(nome_comparavel(b).split())
    if not pa or not pb:
        return 0.0
    return len(pa & pb) / max(len(pa), len(pb))


def _subpastas(pai: Path) -> list[Path]:
    try:
        return [f for f in pai.iterdir() if f.is_dir()] if pai.exists() else []
    except OSError:
        return []


def _existente_ou_nova(pai: Path, nome: str) -> Path:
    """A subpasta com o mesmo nome (ignorando acentos/maiúsculas) ou o caminho novo."""
    alvo = nome_comparavel(nome)
    for filho in _subpastas(pai):
        if nome_comparavel(filho.name) == alvo:
            return filho
    return pai / nome


def _parecidas(pai: Path, nome: str) -> list[Path]:
    """Todas as pastas de cliente com nome parecido (não só a primeira)."""
    alvo = nome_comparavel(nome)
    achadas = []
    for filho in sorted(_subpastas(pai), key=lambda f: f.name.casefold()):
        chave = nome_comparavel(filho.name)
        if chave != alvo and (alvo in chave or chave in alvo or _semelhanca(filho.name, nome) >= 0.65):
            achadas.append(filho)
    return achadas


def _caminho(raiz: Path, *partes: str) -> Path:
    atual = raiz
    for parte in partes:
        atual = _existente_ou_nova(atual, parte)
    return atual


# ------------------------------------------------------------------------ fase 1: planejar

def _projeto_existente(pai: Path, cliente: str, projeto: str) -> Path | None:
    """Pasta do projeto já existente no cliente exato OU em qualquer cliente parecido (sem perguntar)."""
    try:
        candidatos = [_existente_ou_nova(pai, cliente)] + _parecidas(pai, cliente)
    except OSError:
        return None
    for pasta_cliente in candidatos:
        try:
            ja = _existente_ou_nova(pasta_cliente, projeto)
            if ja.exists():
                return ja
        except OSError:          # pasta sem permissão: não derruba, segue para as outras
            continue
    return None


def _pasta_do_projeto(pai: Path, cliente: str, projeto: str, perguntar: Perguntar) -> Path:
    # O mesmo projeto no cliente exato OU em QUALQUER cliente parecido = cotação provavelmente já feita.
    ja_existe = _projeto_existente(pai, cliente, projeto)
    if ja_existe is not None:
        raise ProjetoJaExiste(
            f"Já existe uma pasta para este cliente e projeto:\n{ja_existe}\n\n"
            "Nada foi criado no SAP, para evitar uma cotação repetida. Confira se é o mesmo projeto; "
            "se for outro, mude o nome do projeto.")
    exato = _existente_ou_nova(pai, cliente)
    if exato.exists() and nome_comparavel(exato.name) == nome_comparavel(cliente):
        return _existente_ou_nova(exato, projeto)
    for parecida in _parecidas(pai, cliente):
        if perguntar(
            "Cliente parecido encontrado",
            f"Encontrei uma pasta de cliente parecida.\n\nDigitado: {cliente}\nExistente: {parecida.name}\n\n"
            "Salvar o projeto dentro da pasta existente?",
        ):
            return _existente_ou_nova(parecida, projeto)
    return _existente_ou_nova(exato, projeto)


def _raiz_do_ano(cfg: CotacaoConfig, equipamento: str, ano: int) -> Path:
    if equipamento == "TU":
        return Path(cfg.raiz_produto_a) / f"Propostas_{ano}"
    return Path(cfg.raiz_produto_b) / f"Propostas - {ano}"


def _conferir_outra_rede(req: CotacaoRequest, cfg: CotacaoConfig, principal: str, ano: int,
                         perguntar: Perguntar) -> None:
    """O mesmo projeto já cotado pela outra equipe (pasta na rede do outro equipamento): pergunta antes."""
    outro = "TR" if principal == "TU" else "TU"
    raiz = _raiz_do_ano(cfg, outro, ano)
    try:
        if not raiz.exists():
            return
    except OSError:
        return
    if req.tipo == "Cliente Especial":
        candidato = _caminho(raiz, "Exportação", ESPECIAL_REGIAO, ESPECIAL_PAIS, req.projeto)
        ja = candidato if candidato.exists() else None
    else:
        mercado = ("Brasil", req.regiao) if req.tipo == "Nacional" else ("Exportação", req.regiao, req.pais)
        ja = _projeto_existente(_caminho(raiz, *mercado), req.cliente, req.projeto)
    if ja is None:
        return
    equipe = "Produto B" if outro == "TR" else "Produto A"
    if not perguntar("Projeto já existe na outra rede",
                     f"Este projeto já tem pasta na rede de {equipe}:\n{ja}\n\n"
                     "Pode ser a mesma cotação feita pela outra equipe. Criar uma cotação NOVA mesmo assim?"):
        raise ProjetoJaExiste(f"Já existe uma pasta para este projeto na rede de {equipe}:\n{ja}\n\n"
                              "Nada foi criado no SAP, para evitar uma cotação repetida.")


def planejar_pastas(req: CotacaoRequest, cfg: CotacaoConfig, perguntar: Perguntar,
                    ano: int | None = None) -> PlanoPastas:
    ano = ano or date.today().year
    raiz_tu, raiz_tr = Path(cfg.raiz_produto_a), Path(cfg.raiz_produto_b)
    principal = "TU" if req.produto_a else "TR"
    rede = raiz_tu if principal == "TU" else raiz_tr
    if not rede.exists():
        raise OSError(f"A pasta de rede não está acessível: {rede}. Nada foi criado no SAP.")
    raiz = _raiz_do_ano(cfg, principal, ano)

    if req.tipo == "Cliente Especial":
        projeto = _caminho(raiz, "Exportação", ESPECIAL_REGIAO, ESPECIAL_PAIS, req.projeto)
        if projeto.exists():       # a pasta é a única proteção entre usuários contra cotação repetida
            raise ProjetoJaExiste(
                f"Já existe uma pasta para este projeto Cliente Especial:\n{projeto}\n\n"
                "Nada foi criado no SAP, para evitar uma cotação repetida. Confira se é o mesmo projeto.")
        _conferir_outra_rede(req, cfg, principal, ano, perguntar)
        plano = PlanoPastas("ESPECIAL", projeto / "R.0", None, raiz_tu, raiz_tr, ano)
    else:
        mercado = ("Brasil", req.regiao) if req.tipo == "Nacional" else ("Exportação", req.regiao, req.pais)
        projeto = _pasta_do_projeto(_caminho(raiz, *mercado), req.cliente, req.projeto, perguntar)
        _conferir_outra_rede(req, cfg, principal, ano, perguntar)
        plano = PlanoPastas(principal, projeto / "R.0", projeto / "R.X", raiz_tu, raiz_tr, ano)
    if len(str(plano.base)) > MAX_CAMINHO - 60:
        raise CaminhoMuitoLongo(f"Caminho muito longo para a rede ({len(str(plano.base))} caracteres):\n{plano.base}\n"
                                "Encurte o nome do cliente ou do projeto.")
    return plano


# ------------------------------------------------------------------------ fase 2: criar

def _pasta(caminho: Path) -> None:
    if len(str(caminho)) > MAX_CAMINHO:
        raise CaminhoMuitoLongo(f"Caminho muito longo para criar na rede ({len(str(caminho))} caracteres):\n{caminho}")
    caminho.mkdir(parents=True, exist_ok=True)


def _arquivo_vazio(caminho: Path) -> None:
    if caminho.exists():
        return
    _pasta(caminho.parent)
    caminho.touch()


def _copiar_primeiro(origem: Path, padrao: str, destino: Path) -> None:
    _pasta(destino)
    achados = sorted(origem.glob(padrao)) if origem.exists() else []
    if not achados:
        log.warning("Modelo não encontrado: %s", origem / padrao)
        return
    alvo = destino / achados[0].name
    if not alvo.exists():
        shutil.copy2(achados[0], alvo)


def atalho_windows(arquivo: Path, alvo: str) -> None:
    import win32com.client  # type: ignore
    atalho = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(arquivo))
    atalho.TargetPath = alvo
    atalho.WorkingDirectory = alvo
    atalho.Description = f"Atalho para {alvo}"
    atalho.Save()


def _atalho(pasta: Path, nome: str, alvo: Path, criar: CriarAtalho) -> None:
    _pasta(pasta)
    arquivo = pasta / f"{nome}.lnk"
    if not arquivo.exists():
        criar(arquivo, str(alvo))


def _arvore_padrao(base: Path, numero: str) -> None:
    for nome in ("Cálculo", "Claim", "Consultas - Especificações", "Correspondências", "Cotações", "Custos",
                 "Documentos - Envio ao cliente", "Propostas"):
        _pasta(base / nome)
    _arquivo_vazio(base / "Claim" / "Nº da Claim.txt")
    _arquivo_vazio(base / "Propostas" / f"Numero cotação {numero}.txt")
    for sub in (("Correspondências", "Cliente"), ("Correspondências", "interno", "PCP"),
                ("Correspondências", "interno", "Qualidade"), ("Correspondências", "interno", "Engenharia"),
                ("Cotações", "Gerador"), ("Cotações", "Painel de controle"), ("Cotações", "Serviços")):
        _pasta(base.joinpath(*sub))


def criar_pastas(plano: PlanoPastas, numero: str, criar_atalho: CriarAtalho = atalho_windows) -> Path:
    """Cria a estrutura da proposta para a cotação gravada. Devolve a pasta R.0."""
    tu, tr, base = plano.raiz_produto_a, plano.raiz_produto_b, plano.base
    if plano.modelo == "ESPECIAL":
        for nome in ("Cálculos", "Claim", "Consultas_Especificações", "Correspondências", "DOW", "FPV"):
            _pasta(base / nome)
        _arquivo_vazio(base / "Claim" / "Nº da Claim.txt")
        _arquivo_vazio(base / "Consultas_Especificações" / f"Numero cotação {numero}.txt")
        _pasta(base / "Correspondências" / "Cliente")
        _pasta(base / "Correspondências" / "interno")
        _copiar_primeiro(tu / "PLANILHA DE CUSTO", "*.xlsm", base / "FPV")
        return base

    if plano.revisao_x is not None:
        _arvore_padrao(plano.revisao_x, numero)
    _arvore_padrao(base, numero)
    if plano.modelo == "TU":
        _copiar_primeiro(tu / "PLANILHA DE CUSTO", "*.xlsm", base / "Custos")
        _copiar_primeiro(tu / "Padrão de Propostas", "*.xlsm", base / "Propostas")
        _atalho(base / "Cotações" / "Serviços", "Proposta AT", tu / "Aplicacao" / "Proposta AT", criar_atalho)
        _pasta(base / "Cálculo" / "Produto A")
        _pasta(base / "Cálculo" / "Produto B")
        _copiar_primeiro(tu / "DT" / "DT Reação", "*.xlsm", base / "Cálculo" / "Produto A")
        _copiar_primeiro(tu / "DT" / "DT Ação", "*.xlsm", base / "Cálculo" / "Produto A")
        _copiar_primeiro(tr / "Engenharia de Aplicação" / "Controles" / "Cálculos",
                         "calculo_preliminar.xls", base / "Cálculo" / "Produto B")
    else:
        _copiar_primeiro(tr / "PLANILHA DE CUSTO", "*.xlsm", base / "Custos")
        _atalho(base / "Cotações" / "Serviços", "Proposta AT",
                tr / "Engenharia de Aplicação" / "Controles" / "Proposta AT", criar_atalho)
        _atalho(base / "Propostas", "Modelos de Propostas",
                tr / f"Propostas - {plano.ano}" / "Modelos de Propostas", criar_atalho)
    log.info("Pastas criadas: %s", base)
    return base


# ------------------------------------------------------------------------ e-mail

def corpo_email(numero: str, pasta: Path, equipamentos: str) -> str:
    """HTML do e-mail. Nome de cliente/projeto com &, <, ' ou # não pode quebrar o texto nem o link."""
    import html
    from urllib.parse import quote
    caminho = str(pasta)
    url = "file://" + quote(caminho.replace("\\", "/"), safe="/:")
    estilo = "font-family:Arial; font-size:10pt;"
    return (
        f"<p style='{estilo}'>Olá,</p>"
        f"<p style='{estilo}'>Segue número de cotação e caminho para a pasta do projeto:</p>"
        f"<p style='{estilo}'>Cotação {html.escape(equipamentos)}: {html.escape(numero)}</p>"
        f"<p style='{estilo}'><strong>Caminho:</strong> "
        f"<a href=\"{html.escape(url, quote=True)}\">{html.escape(caminho)}</a></p><br>"
    )


def abrir_email(req: CotacaoRequest, numero: str, pasta: Path, equipamentos: str) -> None:
    """Abre (sem enviar) um e-mail no Outlook com o número e o caminho, como o programa anterior."""
    import win32com.client  # type: ignore
    email = win32com.client.Dispatch("Outlook.Application").CreateItem(0)
    email.Subject = f"Cotação: {req.cliente or req.pais} - {req.projeto}"
    email.Display()
    assinatura = email.HTMLBody
    email.HTMLBody = corpo_email(numero, pasta, equipamentos) + assinatura
    email.Display()
