# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Pendências: execuções que pedem decisão humana depois de conferir no SAP.

As regras são as do controlador (resolver_pendencia / resolver_cotacao): nada aqui marca uma
execução como concluída sem o número conferido, e uma recusa não muda nada no histórico.
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout

from controlador import resolver_cotacao, resolver_pendencia
from cotacao import validar_cotacao
from pastas import ProjetoJaExiste, criar_pastas, planejar_pastas
from storage import Storage
from storage_cotacao import CotacaoStorage

from .. import dialogos
from ..componentes import Banner, Botao, Card, rotulo
from ..dados import Historico, linha_claim, linha_cot
from ..ponte import TarefaRede
from ..tabela import Tabela
from .base import Pagina
from .historico import COLUNAS_CLAIM, COLUNAS_COT


class PaginaPendencias(Pagina):
    titulo = "Pendências"
    subtitulo = "Execuções interrompidas, sem confirmação ou em revisão"

    def __init__(self, janela):
        super().__init__(janela)
        self.hist = Historico(janela.caminho_db)
        self.lay.addWidget(Banner("info", "A automação nunca repete uma gravação sozinha",
                                  "Confira no SAP (CLM3 para claims, VA23 para cotações) e informe o que encontrou. "
                                  "Só então crie de novo, se for o caso."))

        self.card_claim = Card("Claims", "Selecione uma linha e, depois de conferir no SAP:")
        acoes = QHBoxLayout()
        acoes.addStretch(1)
        acoes.addWidget(Botao("Claim criado…", "sucesso", "check", lambda: self._resolver(True)))
        acoes.addWidget(Botao("Não foi criado", "perigo", "x", lambda: self._resolver(False)))
        self.card_claim.cabecalho.addLayout(acoes)
        self.t_claim = Tabela(COLUNAS_CLAIM, 6, ("check", "Nenhum claim pendente", "Tudo resolvido."))
        self.t_claim.setMinimumHeight(260)
        self.card_claim.add(self.t_claim)
        self.lay.addWidget(self.card_claim)

        self.card_cot = Card("Cotações", "Sem confirmação? Confira na VA23 e informe:")
        acoes2 = QHBoxLayout()
        acoes2.addStretch(1)
        acoes2.addWidget(Botao("Cotação existe…", "sucesso", "check", lambda: self._resolver_cotacao(True)))
        acoes2.addWidget(Botao("Não foi criada", "perigo", "x", lambda: self._resolver_cotacao(False)))
        self.card_cot.cabecalho.addLayout(acoes2)
        self.t_cot = Tabela(COLUNAS_COT, 6, ("check", "Nenhuma cotação pendente", "Tudo resolvido."))
        self.t_cot.setMinimumHeight(220)
        self.card_cot.add(self.t_cot)
        self.lay.addWidget(self.card_cot)
        self.card_cot.setVisible(bool(self.cfg.cotacao))
        self.lay.addStretch(1)

    def ao_mostrar(self) -> None:
        try:
            self.t_claim.definir([linha_claim(e) for e in self.hist.pendencias_claim()])
            if self.cfg.cotacao:
                self.t_cot.definir([linha_cot(c) for c in self.hist.pendencias_cotacao()])
        except Exception as erro:  # noqa: BLE001
            dialogos.erro(self, "Pendências", f"Não foi possível ler o histórico:\n{erro}")

    # ------------------------------------------------------------------ claims

    def _resolver(self, criado: bool) -> None:
        if self.janela.executor.ocupado:
            # A própria execução em andamento aparece na lista: resolver agora mentiria no histórico.
            dialogos.informar(self, "Pendências", "Há uma execução em andamento. Aguarde terminar para resolver.")
            return
        execucao = self.t_claim.selecionado()
        if execucao is None:
            dialogos.informar(self, "Pendências", "Selecione uma execução na lista.")
            return
        ordem = f"{execucao.ordem}/{execucao.item or 'nova'}"
        linha = execucao.linha_criada or ""
        linha_existe = None
        if linha.startswith("?"):
            resposta = dialogos.sim_nao_cancelar(
                self, "Linha da cotação",
                f"Esta execução enviou a linha {linha[1:]} para a cotação {execucao.ordem}, sem confirmação.\n\n"
                f"Confira na VA23: a linha {linha[1:]} EXISTE na cotação?")
            if resposta is None:
                return
            linha_existe = resposta
        numero = ""
        if criado:
            numero = (dialogos.pedir_texto(self, "Claim criado", f"Ordem {ordem}\nNúmero da nota conferida no SAP:")
                      or "").strip()
            if not numero:
                return
            pergunta = f"Registrar a execução {execucao.id} como CONCLUÍDA, nota {numero}?"
        else:
            pergunta = (f"Confirma que o claim da execução {execucao.id} (ordem {ordem}) NÃO existe no SAP?\n\n"
                        "Isso libera uma nova execução para esta ordem/item.")
            if linha.lstrip("?") and linha_existe is not False:
                pergunta += (f"\n\nA linha {linha.lstrip('?')} continua registrada: crie o claim dela pelo programa, "
                             "SEM marcar 'Criar linha nova'.")
        if not dialogos.confirmar(self, "Resolver pendência", pergunta):
            return
        try:
            db = Storage(self.janela.caminho_db)
            try:
                resolver_pendencia(db, execucao.id, criado=criado, numero_nota=numero, linha_existe=linha_existe)
            finally:
                db.close()
        except Exception as erro:  # noqa: BLE001 - qualquer recusa vira mensagem (nada foi mudado)
            dialogos.erro(self, "Resolver pendência", str(erro))
            return
        self.janela.atualizar_dados()

    # ------------------------------------------------------------------ cotações

    def _resolver_cotacao(self, criada: bool) -> None:
        if self.janela.executor.ocupado:
            dialogos.informar(self, "Cotações", "Há uma execução em andamento. Aguarde terminar para resolver.")
            return
        registro = self.t_cot.selecionado()
        if registro is None:
            dialogos.informar(self, "Cotações", "Selecione uma cotação na lista.")
            return
        numero = ""
        if criada:
            numero = (dialogos.pedir_texto(self, "Cotação existe", "Número da cotação conferido na VA23:") or "").strip()
            if not numero:
                return
        elif not dialogos.confirmar(self, "Cotação não criada", "Confirma que esta cotação NÃO existe no SAP?"):
            return
        db = CotacaoStorage(self.janela.caminho_db)
        atualizado = None
        try:
            resolver_cotacao(db, registro.id, criada=criada, numero=numero)
            atualizado = db.obter(registro.id)
        except Exception as erro:  # noqa: BLE001 - qualquer recusa vira mensagem (nada foi mudado)
            dialogos.erro(self, "Cotações", str(erro))
        finally:
            db.close()
        self.janela.atualizar_dados()
        if criada and atualizado is not None:
            self._pastas_depois(atualizado, numero)

    def _pastas_depois(self, registro, numero: str) -> None:
        """Pastas de uma cotação resolvida como 'existe' (a execução não chegou a criá-las)."""
        if registro.modo != "AUTOMATICO":
            return
        problemas = validar_cotacao(registro.request, self.cfg)     # o histórico pode ser antigo/editado
        if problemas:
            dialogos.avisar(self, "Pastas", "A cotação foi registrada, mas as pastas não foram criadas: os dados "
                            "guardados não passam mais na validação:\n" + "\n".join(p.mensagem for p in problemas))
            return

        def trabalho(perguntar):
            plano = planejar_pastas(registro.request, self.cfg.cotacao, perguntar=perguntar)
            return criar_pastas(plano, numero)

        def terminou(pasta) -> None:
            db = CotacaoStorage(self.janela.caminho_db)
            try:
                db.registrar_pasta(registro.id, str(pasta))
            finally:
                db.close()
            self.janela.atualizar_dados()
            dialogos.informar(self, "Pastas criadas", f"Pastas da proposta criadas:\n{pasta}")

        def falhou(erro: Exception) -> None:
            if isinstance(erro, ProjetoJaExiste):
                dialogos.avisar(self, "Pastas", "A cotação foi registrada. A pasta deste projeto JÁ EXISTE na rede, "
                                "então nenhuma pasta nova foi criada. Confira se ela é desta cotação:\n\n"
                                + str(erro).split("\n\n")[0])
            else:
                dialogos.avisar(self, "Pastas", f"A cotação foi registrada, mas as pastas não foram criadas:\n{erro}")

        TarefaRede(self.janela, trabalho, terminou, falhou)
