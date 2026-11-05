# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Nova cotação (VA21 + pastas da proposta). Só aparecem os campos que o tipo escolhido pede."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLineEdit,
                               QPlainTextEdit, QVBoxLayout, QWidget)

from controlador import ROTULO_ESTADO, TOM_ESTADO, modos_cotacao_da_interface
from cotacao import PAISES_POR_REGIAO, CotacaoRequest, regioes_do_tipo, tipos_disponiveis, validar_cotacao
from cotacao_service import ETAPAS_COTACAO, ResultadoCotacao, etapas_cotacao_do_modo
from pastas import CaminhoMuitoLongo, ProjetoJaExiste, abrir_email, planejar_pastas
from state import Estado

from .. import dialogos
from ..componentes import Badge, Banner, Botao, Campo, Card, LinhaDoTempo, Segmentado, esvaziar, rotulo
from ..ponte import TarefaRede
from .base import Pagina

log = logging.getLogger("claim.ui_qt.cotacao")
ROTULO_MODO_COTACAO = {"SIMULACAO": "Simulação", "ENSAIO": "Ensaio", "AUTOMATICO": "Criar (grava)"}
CAMPOS = ("tipo", "regiao", "pais", "cliente", "projeto", "equipamentos")


class Lista(QComboBox):
    """Lista suspensa somente leitura com o primeiro item vazio ('Selecione…')."""

    def __init__(self, ao_mudar):
        super().__init__()
        self.setMaxVisibleItems(14)
        self.currentIndexChanged.connect(lambda _: ao_mudar(self.get()))

    def opcoes(self, valores) -> None:
        self.blockSignals(True)
        self.clear()
        self.addItem("Selecione…", "")
        for v in valores:
            self.addItem(v, v)
        self.blockSignals(False)

    def get(self) -> str:
        return self.currentData() or ""


class PaginaCotacao(Pagina):
    titulo = "Nova cotação"
    subtitulo = "Cotação na VA21, pastas da proposta e e-mail para o time"

    def __init__(self, janela):
        super().__init__(janela)
        self.rotulo_modo = {m: ROTULO_MODO_COTACAO[m] for m in modos_cotacao_da_interface(self.cfg)}
        self.tocados: set[str] = set()
        self.ultimo: ResultadoCotacao | None = None
        self.ultimo_req: CotacaoRequest | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._atualizar)

        self.faixa = Banner("atencao")
        self.faixa.setVisible(False)
        self.lay.addWidget(self.faixa)
        esquerda, direita = self.colunas(3, 2)
        esquerda.addWidget(self._grupo_dados())
        esquerda.addWidget(self._grupo_equipamentos())
        esquerda.addWidget(self._grupo_resultado())      # logo abaixo: número e "Criar claim" à vista
        esquerda.addStretch(1)
        direita.addWidget(self._grupo_execucao())
        direita.addWidget(self._grupo_andamento())
        direita.addStretch(1)
        tipos = list(tipos_disponiveis(self.cfg))
        self.tipo.set(tipos[0] if tipos else "")
        self._mudou_tipo(self.tipo.get(), inicial=True)
        self.resetar_etapas()

    # ------------------------------------------------------------------ grupos

    def _grupo_dados(self) -> Card:
        card = Card("Dados da cotação", "Os campos mudam conforme o tipo")
        self.tipo = Segmentado(list(tipos_disponiveis(self.cfg)))
        self.tipo.mudou.connect(self._mudou_tipo)
        self.c_tipo = Campo("Tipo de cotação", self.tipo)
        card.add(self.c_tipo)

        self.grade_local = QGridLayout()
        self.grade_local.setHorizontalSpacing(14)
        self.regiao = Lista(self._mudou_regiao)
        self.pais = Lista(lambda _: self._mudou("pais"))
        self.c_regiao = Campo("Região", self.regiao)
        self.c_pais = Campo("País", self.pais)
        self.grade_local.addWidget(self.c_regiao, 0, 0)
        self.grade_local.addWidget(self.c_pais, 0, 1)
        card.corpo.addLayout(self.grade_local)

        grade = QGridLayout()
        grade.setHorizontalSpacing(14)
        self.cliente = QLineEdit()
        self.cliente.setPlaceholderText("Nome do cliente")
        self.cliente.textEdited.connect(lambda _: self._mudou("cliente"))
        self.projeto = QLineEdit()
        self.projeto.setPlaceholderText("Nome do projeto")
        self.projeto.textEdited.connect(lambda _: self._mudou("projeto"))
        self.c_cliente = Campo("Cliente", self.cliente)
        self.c_projeto = Campo("Projeto", self.projeto)
        grade.addWidget(self.c_cliente, 0, 0)
        grade.addWidget(self.c_projeto, 0, 1)
        card.corpo.addLayout(grade)
        self.info_tipo = rotulo("", "Dica", quebra=True)
        card.add(self.info_tipo)
        return card

    def _grupo_equipamentos(self) -> Card:
        card = Card("Equipamentos", "Produto A e Produto B juntos = uma cotação com duas linhas (10 e 20)")
        linha = QHBoxLayout()
        linha.setSpacing(24)
        self.produto_a = QCheckBox("Produto A")
        self.produto_b = QCheckBox("Produto B")
        gerador = QCheckBox("Gerador · em breve")
        gerador.setEnabled(False)
        for c in (self.produto_a, self.produto_b):
            c.setCursor(Qt.PointingHandCursor)
            c.toggled.connect(lambda _: self._mudou("equipamentos"))
            linha.addWidget(c)
        linha.addWidget(gerador)
        linha.addStretch(1)
        card.corpo.addLayout(linha)
        self.erro_equip = rotulo("", "Erro", quebra=True)
        self.erro_equip.setVisible(False)
        card.add(self.erro_equip)
        return card

    def _grupo_execucao(self) -> Card:
        card = Card("Execução", "O número da cotação é copiado ao final")
        if not self.janela.producao:
            self.modo = Segmentado(list(self.rotulo_modo.values()))
            self.modo.set(self.rotulo_modo.get("ENSAIO", "Simulação"))
            self.modo.mudou.connect(lambda _: (self.resetar_etapas(), self._atualizar_resumo()))
            card.add(Campo("Modo", self.modo, obrigatorio=False))
        self.resumo = QGridLayout()
        self.resumo.setHorizontalSpacing(12)
        self.resumo.setVerticalSpacing(6)
        self._valores: dict[str, object] = {}
        for i, nome in enumerate(("Tipo", "Cliente", "Projeto", "Linhas", "Modo")):
            self.resumo.addWidget(rotulo(nome, "Dica"), i, 0, Qt.AlignTop)
            v = rotulo("—", quebra=True)
            self.resumo.addWidget(v, i, 1)
            self._valores[nome] = v
        self.resumo.setColumnStretch(1, 1)
        card.corpo.addLayout(self.resumo)
        botoes = QHBoxLayout()
        self.btn_limpar = Botao("Limpar", "secundario", "limpar", self.limpar)
        self.btn_parar = Botao("Interromper", "perigo", "parar", self._interromper)
        self.btn_parar.setEnabled(False)
        botoes.addWidget(self.btn_limpar)
        botoes.addStretch(1)
        botoes.addWidget(self.btn_parar)
        card.corpo.addLayout(botoes)
        self.btn_criar = Botao("Criar cotação", "primario", "play", self._criar)
        self.btn_criar.setMinimumHeight(42)
        card.add(self.btn_criar)
        return card

    def _grupo_andamento(self) -> Card:
        card = Card("Andamento")
        self.tempo = LinhaDoTempo(ETAPAS_COTACAO)
        card.add(self.tempo)
        return card

    def _grupo_resultado(self) -> Card:
        card = Card("Resultado")
        self.selo = Badge()
        card.cabecalho.addWidget(self.selo, 0, Qt.AlignTop)
        self.msg = rotulo("Nenhuma cotação nesta sessão.", "Dica", quebra=True)
        self.msg.setTextInteractionFlags(Qt.TextSelectableByMouse)
        card.add(self.msg)
        self.proximos = QVBoxLayout()
        self.proximos.setSpacing(8)
        card.corpo.addLayout(self.proximos)
        self.detalhes = QPlainTextEdit()
        self.detalhes.setObjectName("Mono")
        self.detalhes.setReadOnly(True)
        self.detalhes.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.detalhes.setMinimumHeight(110)
        self.detalhes.setVisible(False)
        card.add(self.detalhes)
        return card

    # ------------------------------------------------------------------ reações

    def _tipo_cfg(self, tipo: str):
        return self.cfg.cotacao.tipos.get(tipo) if self.cfg.cotacao else None

    def _mudou_tipo(self, tipo: str, inicial: bool = False) -> None:
        cfg = self._tipo_cfg(tipo)
        regioes = list(regioes_do_tipo(tipo))
        self.regiao.opcoes(regioes)
        self.pais.opcoes([])
        self.pais.setEnabled(False)
        pede_regiao = bool(regioes) and (cfg is None or cfg.pede_regiao)
        pede_pais = tipo == "Exportação"
        pede_cliente = cfg is None or cfg.pede_cliente
        self.c_regiao.setVisible(pede_regiao)
        self.c_pais.setVisible(pede_pais)
        self.c_cliente.setVisible(pede_cliente)
        if not pede_cliente:
            self.cliente.clear()
        self.info_tipo.setText("" if pede_cliente else f"{tipo}: região, país e cliente são fixos.")
        self.info_tipo.setVisible(not pede_cliente)
        if not inicial:
            self._mudou("tipo")
        self._atualizar_resumo()

    def _mudou_regiao(self, regiao: str) -> None:
        paises = list(PAISES_POR_REGIAO.get(regiao, ())) if self.tipo.get() == "Exportação" else []
        self.pais.opcoes(paises)
        self.pais.setEnabled(bool(paises))
        self._mudou("regiao")

    def _mudou(self, campo: str) -> None:
        self.tocados.add(campo)
        self._atualizar_resumo()
        self._timer.start()

    def _request(self) -> CotacaoRequest:
        return CotacaoRequest.from_form(
            tipo=self.tipo.get(), regiao=self.regiao.get(), pais=self.pais.get(), cliente=self.cliente.text(),
            projeto=self.projeto.text(), produto_a=self.produto_a.isChecked(), produto_b=self.produto_b.isChecked())

    def _atualizar(self) -> list:
        req = self._request()
        problemas = validar_cotacao(req, self.cfg)
        por_campo: dict[str, str] = {}
        for p in problemas:
            por_campo.setdefault(p.campo, p.mensagem)
        for nome, campo in (("tipo", self.c_tipo), ("regiao", self.c_regiao), ("pais", self.c_pais),
                            ("cliente", self.c_cliente), ("projeto", self.c_projeto)):
            campo.set_erro(por_campo.get(nome, "") if nome in self.tocados else "")
        texto = por_campo.get("equipamentos", "") if "equipamentos" in self.tocados else ""
        self.erro_equip.setText(texto)
        self.erro_equip.setVisible(bool(texto))
        return problemas

    def _atualizar_resumo(self) -> None:
        req = self._request()
        v = self._valores
        v["Tipo"].setText(req.tipo or "—")
        local = " · ".join(x for x in (req.regiao, req.pais) if x and req.tipo != "Cliente Especial")
        v["Cliente"].setText((req.cliente or ("fixo" if req.tipo == "Cliente Especial" else "—"))
                             + (f"  ({local})" if local else ""))
        v["Projeto"].setText(req.projeto or "—")
        linhas = [n for n, ok in (("10 Produto A", req.produto_a), ("20 Produto B" if req.produto_a else "10 Produto B",
                                                                req.produto_b)) if ok]
        v["Linhas"].setText(", ".join(linhas) or "—")
        modo = self._modo()
        v["Modo"].setText("Criar cotação (produção)" if self.janela.producao
                          else ROTULO_MODO_COTACAO[modo] + (" · grava no SAP e cria pastas" if modo == "AUTOMATICO"
                                                            else ""))

    # ------------------------------------------------------------------ execução

    def _modo(self) -> str:
        if self.janela.producao:
            return "AUTOMATICO"
        inverso = {v: k for k, v in self.rotulo_modo.items()}
        return inverso.get(self.modo.get(), "SIMULACAO")

    def _criar(self) -> None:
        if self.janela.executor.ocupado:
            dialogos.informar(self, "Aguarde", "Há uma execução em andamento.")
            return
        self.tocados.update(CAMPOS)
        if self._atualizar():
            self._texto_resultado("atencao", "Dados incompletos", "Corrija os campos marcados.")
            return
        req, modo = self._request(), self._modo()
        if modo == "AUTOMATICO":
            # A pasta de propostas fica na rede: conferir em segundo plano para a tela não congelar.
            # Sem confirmação extra (decisão do dono): o clique com os dados validados é a autorização.
            self.btn_criar.setEnabled(False)
            self.btn_criar.setText("Conferindo pastas…")
            self._texto_resultado("info", "Conferindo", "Conferindo a pasta de propostas na rede…")

            def falhou(erro: Exception) -> None:
                self.btn_criar.setEnabled(True)
                self.btn_criar.setText("Criar cotação")
                if isinstance(erro, (ProjetoJaExiste, CaminhoMuitoLongo)):
                    dialogos.avisar(self, "Cotação não criada", str(erro))
                    self._texto_resultado("atencao", "Não criada", str(erro).split("\n")[0])
                elif isinstance(erro, OSError):
                    dialogos.erro(self, "Rede", f"Não consegui acessar a pasta de propostas na rede:\n{erro}")
                    self._texto_resultado("erro", "Rede", "Pasta de propostas inacessível. Nada foi criado.")
                else:
                    dialogos.erro(self, "Cotação não criada", str(erro))
                    self._texto_resultado("erro", "Não criada", "Erro ao conferir as pastas. Nada foi criado.")

            TarefaRede(self.janela, lambda perguntar: planejar_pastas(req, self.cfg.cotacao, perguntar=perguntar),
                       lambda plano: self._comecar(req, modo, plano), falhou)
            return
        if modo == "ENSAIO":
            if not dialogos.ok_cancelar(self, "Ensaio no SAP", "A automação vai abrir uma janela própria no SAP e "
                                        "preencher a VA21.\n\nNada será gravado e nenhuma pasta será criada."):
                return
        self._comecar(req, modo, None)

    def _comecar(self, req, modo: str, plano_pastas) -> None:
        if self.janela.executor.ocupado:       # outra página começou enquanto as pastas eram conferidas
            self.btn_criar.setEnabled(True)
            self.btn_criar.setText("Criar cotação")
            dialogos.informar(self, "Aguarde", "Há uma execução em andamento. Nada foi criado.")
            return
        self.ultimo_req = req
        self.resetar_etapas()
        self.janela.pagina_execucao.iniciar("cotacao", modo, False, f"Cotação · {req.cliente or req.tipo} / "
                                                                   f"{req.projeto}")
        self._limpar_proximos()
        self._texto_resultado("info", "Em andamento", "Criando a cotação…")
        self.btn_criar.setEnabled(False)
        self.btn_criar.setText("Criando…")
        self.btn_parar.setEnabled(True)
        self.btn_limpar.setEnabled(False)
        self._travar(True)
        try:
            self.janela.executor.iniciar_cotacao(req, modo, plano_pastas)
        except Exception as erro:  # noqa: BLE001
            self._destravar()
            self._texto_resultado("atencao", "Não iniciada", f"{erro} Nada foi criado.")

    def _travar(self, travar: bool) -> None:
        for w in (self.tipo, self.regiao, self.cliente, self.projeto, self.produto_a, self.produto_b):
            w.setEnabled(not travar)
        self.pais.setEnabled(not travar and self.pais.count() > 1)
        if hasattr(self, "modo"):
            self.modo.setEnabled(not travar)

    def _destravar(self) -> None:
        self._travar(False)
        self.btn_criar.setEnabled(True)
        self.btn_criar.setText("Criar cotação")
        self.btn_parar.setEnabled(False)
        self.btn_parar.setText("Interromper")
        self.btn_limpar.setEnabled(True)

    def _interromper(self) -> None:
        self.janela.executor.interromper()
        self.btn_parar.setEnabled(False)
        self.btn_parar.setText("Parando…")

    def resetar_etapas(self) -> None:
        ativas = [c for c, _ in etapas_cotacao_do_modo(self._modo())]
        self.tempo.preparar(ativas, "não faz parte do ensaio")

    def marcar_etapa(self, chave: str, situacao: str, detalhe: str) -> None:
        self.tempo.marcar(chave, situacao, detalhe)

    def terminou(self, evento) -> None:
        self._destravar()
        if isinstance(evento.resultado, ResultadoCotacao):
            self._mostrar(evento.resultado)
        else:
            self._texto_resultado("erro", "Erro inesperado", evento.detalhe)

    def _texto_resultado(self, tom: str, selo: str, mensagem: str) -> None:
        self.selo.definir(selo, tom)
        self.msg.setText(mensagem)

    def _limpar_proximos(self) -> None:
        esvaziar(self.proximos)

    def _mostrar(self, r: ResultadoCotacao) -> None:
        self.ultimo = r
        self._texto_resultado(TOM_ESTADO.get(r.estado, "atencao"), ROTULO_ESTADO.get(r.estado, r.estado.value),
                              r.mensagem)
        self.detalhes.setPlainText("\n".join(detalhes_cotacao(r)))
        self.detalhes.setVisible(True)
        self._limpar_proximos()
        if r.estado == Estado.CONCLUIDO and r.numero:
            QGuiApplication.clipboard().setText(r.numero)
            QApplication.beep()
            texto = f"{r.mensagem} O número foi copiado."
            if r.aviso_pastas:
                self._texto_resultado("atencao", "Criada, sem pastas", texto + f"\n\n{r.aviso_pastas}")
            else:
                self.msg.setText(texto)
            self.proximos.addWidget(self._destaque(r))
        elif r.estado == Estado.ENSAIO_CONCLUIDO:
            QApplication.beep()

    def _destaque(self, r: ResultadoCotacao) -> QWidget:
        from PySide6.QtWidgets import QFrame
        caixa = QFrame()
        caixa.setObjectName("Destaque")
        lay = QVBoxLayout(caixa)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)
        lay.addWidget(rotulo(f"Cotação {r.numero}", "DestaqueNumero"))
        lay.addWidget(rotulo("Próximo passo: criar o claim de cada linha", "Dica"))
        for linha in r.linhas:
            b = Botao(f"Criar claim · item {linha['item']} · {linha['equipamento']}", "grande", "mais",
                      lambda _=False, l=linha: self.janela.pagina_claim.preparar_claim(r.numero, l["item"], l["rota"]))
            lay.addWidget(b)
        extras = QHBoxLayout()
        if r.pasta:
            extras.addWidget(Botao("Abrir pasta", "secundario", "pasta", lambda: abrir_pasta(self, r.pasta)))
            extras.addWidget(Botao("E-mail no Outlook", "secundario", "email", self._email))
        extras.addStretch(1)
        lay.addLayout(extras)
        return caixa

    def _email(self) -> None:
        r, req = self.ultimo, self.ultimo_req
        if r is None or req is None:
            return
        try:
            abrir_email(req, r.numero, Path(r.pasta), req.equipamentos)
        except Exception as erro:  # noqa: BLE001
            dialogos.erro(self, "E-mail", f"Não foi possível abrir o Outlook:\n{erro}")

    def limpar(self) -> None:
        if self.janela.executor.ocupado:
            dialogos.informar(self, "Limpar", "Aguarde a execução em andamento terminar.")
            return
        for c in (self.cliente, self.projeto):
            c.clear()
        for c in (self.produto_a, self.produto_b):
            c.blockSignals(True)
            c.setChecked(False)
            c.blockSignals(False)
        self.tocados.clear()
        self._mudou_tipo(self.tipo.get(), inicial=True)
        self._atualizar()
        self._limpar_proximos()
        self.selo.definir("")
        self.msg.setText("Pronto para uma nova cotação.")
        self.detalhes.clear()
        self.detalhes.setVisible(False)
        self.resetar_etapas()

    def mostrar_pendentes(self, n: int) -> None:
        self.faixa.definir("atencao", f"{n} cotação(ões) sem confirmação",
                           "Confira na VA23 e resolva na página Pendências antes de criar de novo.")
        self.faixa.setVisible(n > 0)


def detalhes_cotacao(r: ResultadoCotacao) -> list[str]:
    linhas = [f"Execução {r.cotacao_id}"]
    if r.numero:
        linhas.append(f"COTAÇÃO CRIADA: {r.numero}")
    for l in r.linhas:
        linhas.append(f"  Item {l['item']}: {l['equipamento']} · {l['material']} · centro {l['centro']}")
    if r.pasta:
        linhas.append(f"Pasta: {r.pasta}")
    if r.aviso_pastas:
        linhas.append(f"ATENÇÃO: {r.aviso_pastas}")
    for p in r.problemas:
        linhas.append(f"  [{p.campo}] {p.mensagem}")
    for a in r.avisos:
        linhas.append(f"Aviso aceito: {a}")
    return linhas


def abrir_pasta(pai, pasta: str) -> None:
    try:
        os.startfile(pasta)  # type: ignore[attr-defined]
    except (OSError, AttributeError) as erro:
        dialogos.avisar(pai, "Abrir pasta", f"Não foi possível abrir:\n{pasta}\n\n{erro}")
