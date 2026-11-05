# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Configurações: o que o programa está usando (somente leitura) e a aparência.

Os parâmetros de execução vêm do settings.ini e passam pelas validações dele: não são editáveis
aqui, de propósito. A única preferência gravada é o tema, por usuário (QSettings)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout

from config import CAMINHO_PADRAO
from controlador import ROTULO_MODO, modos_da_interface

from ..componentes import Badge, Card, Segmentado, rotulo
from .base import Pagina


def versao_instalada() -> str:
    from pathlib import Path
    try:
        return "v" + (Path(CAMINHO_PADRAO).parent / "versao.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return "desenvolvimento"


class PaginaConfiguracoes(Pagina):
    titulo = "Configurações"
    subtitulo = "Parâmetros em uso (definidos pelo responsável no settings.ini) e aparência"

    def __init__(self, janela):
        super().__init__(janela)
        cfg = self.cfg
        linha = QHBoxLayout()
        linha.setSpacing(18)
        sap = self._card("SAP", "Trava de segurança: a automação só age nesta combinação",
                         [("Sistema", cfg.sistema), ("Mandante", cfg.mandante), ("Tipo de nota", cfg.tipo_nota)])
        modos = ", ".join(ROTULO_MODO[m] for m in modos_da_interface(cfg))
        execucao = self._card("Execução", "Modos que gravam só aparecem com a gravação habilitada",
                              [("Modo inicial", ROTULO_MODO.get(cfg.modo, cfg.modo)),
                               ("Gravação no SAP", "habilitada" if cfg.automatico_habilitado else "desligada"),
                               ("Modos disponíveis", modos),
                               ("Interface", "produção (só 'Criar')" if janela.producao else "desenvolvimento")])
        badge = Badge("grava no SAP" if cfg.automatico_habilitado else "não grava",
                      "atencao" if cfg.automatico_habilitado else "neutro")
        execucao.cabecalho.addWidget(badge, 0, Qt.AlignTop)
        linha.addWidget(sap, 1)
        linha.addWidget(execucao, 1)
        self.lay.addLayout(linha)

        linha2 = QHBoxLayout()
        linha2.setSpacing(18)
        pastas = [("Histórico e logs", str(cfg.pasta_dados)), ("settings.ini", str(CAMINHO_PADRAO))]
        if cfg.cotacao:
            pastas += [("Propostas (Produto A)", cfg.cotacao.raiz_produto_a), ("Propostas (Produto B)", cfg.cotacao.raiz_produto_b)]
        linha2.addWidget(self._card("Diretórios", "Onde o programa lê e grava", pastas), 1)

        aparencia = Card("Aparência", "Preferência deste usuário, neste computador")
        self.tema = Segmentado(["Claro", "Escuro"])
        self.tema.set("Escuro" if janela.tema_atual == "escuro" else "Claro")
        self.tema.mudou.connect(lambda t: janela.aplicar_tema("escuro" if t == "Escuro" else "claro"))
        aparencia.add(self.tema)
        aparencia.add(rotulo("O tema não muda nada na automação.", "Dica"))
        aparencia.corpo.addStretch(1)
        sobre = self._card("Sobre", "", [("Versão", versao_instalada()), ("Interface", "PySide6 (teste)")])
        lado = QHBoxLayout()
        coluna = QVBoxLayout()
        coluna.setSpacing(18)
        coluna.addWidget(aparencia)
        coluna.addWidget(sobre)
        lado.addLayout(coluna)
        linha2.addLayout(lado, 1)
        self.lay.addLayout(linha2)
        self.lay.addStretch(1)

    def _card(self, titulo: str, sub: str, linhas: list[tuple[str, str]]) -> Card:
        card = Card(titulo, sub)
        g = QGridLayout()
        g.setHorizontalSpacing(16)
        g.setVerticalSpacing(8)
        for i, (nome, valor) in enumerate(linhas):
            g.addWidget(rotulo(nome, "Dica"), i, 0, Qt.AlignTop)
            v = rotulo(valor or "—", quebra=True)
            v.setTextInteractionFlags(Qt.TextSelectableByMouse)
            g.addWidget(v, i, 1)
        g.setColumnStretch(1, 1)
        card.corpo.addLayout(g)
        card.corpo.addStretch(1)
        return card
