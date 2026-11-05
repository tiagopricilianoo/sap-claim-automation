# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Novo claim (CLM1): mesmos campos, regras e decisões da interface anterior, em grupos visuais."""

from __future__ import annotations

import logging
from dataclasses import replace

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QApplication, QCheckBox, QGridLayout, QHBoxLayout, QLineEdit, QPlainTextEdit,
                               QVBoxLayout, QWidget)

from claim_service import ETAPAS, etapas_do_modo
from controlador import (ROTULO_ESTADO, ROTULO_MODO, TOM_ESTADO, modos_da_interface, montar_request,
                         resumo_arquivo, validar_formulario)
from state import Estado
from validators import tamanho_sap

from .. import dialogos
from ..componentes import Badge, Banner, Botao, Campo, Card, LinhaDoTempo, Segmentado, SeletorArquivo, rotulo
from .base import Pagina

log = logging.getLogger("claim.ui_qt")
CAMPOS = ("tipo", "descricao", "texto_livre", "ordem", "item", "arquivo")


class PaginaClaim(Pagina):
    titulo = "Novo claim"
    subtitulo = "Nota CLM1 com documento, atividades e responsáveis da rota"

    def __init__(self, janela):
        super().__init__(janela)
        self.rotas = {r.rotulo: r.chave for r in self.cfg.rotas.values()}
        self.rotulo_modo = {m: ROTULO_MODO[m] for m in modos_da_interface(self.cfg)}
        self.tocados: set[str] = set()
        self._ultimo_pedido = None
        self._timer_validacao = QTimer(self)
        self._timer_validacao.setSingleShot(True)
        self._timer_validacao.setInterval(250)
        self._timer_validacao.timeout.connect(self._mostrar_erros)

        self.faixa = Banner("atencao")
        self.faixa.setVisible(False)
        self.lay.addWidget(self.faixa)
        esquerda, direita = self.colunas(3, 2)
        esquerda.addWidget(self._grupo_principal())
        esquerda.addWidget(self._grupo_complementar())
        esquerda.addStretch(1)
        direita.addWidget(self._grupo_execucao())
        direita.addWidget(self._grupo_andamento())
        direita.addWidget(self._grupo_resultado())
        direita.addStretch(1)
        self._resetar_etapas()
        self._atualizar_resumo()

    # ------------------------------------------------------------------ grupos

    def _grupo_principal(self) -> Card:
        card = Card("Informações principais", "Tipo, cotação e item que recebem o claim")
        self.tipo = Segmentado(list(self.rotas))
        self.tipo.mudou.connect(lambda _: self._mudou("tipo"))
        self.c_tipo = Campo("Tipo de claim", self.tipo)
        self.c_tipo.set_dica("Escolha o tipo para ver a rota de atividades.")
        card.add(self.c_tipo)

        grade = QGridLayout()
        grade.setHorizontalSpacing(14)
        grade.setVerticalSpacing(4)
        self.ordem = self._entrada("Ex.: 1234567", "ordem")
        self.item = self._entrada("Ex.: 10", "item")
        self.c_ordem = Campo("Ordem do cliente (cotação)", self.ordem)
        self.c_item = Campo("Item", self.item)
        grade.addWidget(self.c_ordem, 0, 0)
        grade.addWidget(self.c_item, 0, 1)
        grade.setColumnStretch(0, 3)
        grade.setColumnStretch(1, 1)
        card.corpo.addLayout(grade)

        self.linha_nova = QCheckBox("Criar linha nova na cotação (o item é criado na VA22 e recebe o claim)")
        self.linha_nova.setCursor(Qt.PointingHandCursor)
        self.linha_nova.toggled.connect(self._mudou_linha_nova)
        card.add(self.linha_nova)
        self.linha_info = rotulo("", "DicaAzul", quebra=True)
        self.linha_info.setVisible(False)
        card.add(self.linha_info)

        self.contador = rotulo(f"0/{self.cfg.limites.descricao_max}", "Dica")
        self.descricao = self._entrada("Resumo do claim", "descricao")
        self.c_descricao = Campo("Descrição", self.descricao, direita=self.contador)
        card.add(self.c_descricao)
        return card

    def _grupo_complementar(self) -> Card:
        card = Card("Informações complementares", "Texto da nota e anexo do documento ZDC")
        self.texto = QPlainTextEdit()
        self.texto.setPlaceholderText("Detalhes do claim")
        self.texto.setMinimumHeight(110)
        self.texto.textChanged.connect(lambda: self._mudou("texto_livre"))
        self.c_texto = Campo("Texto livre", self.texto)
        card.add(self.c_texto)

        self.arquivo = SeletorArquivo(resumo_arquivo)
        self.arquivo.escolhido.connect(lambda _: self._mudou("arquivo"))
        self.c_arquivo = Campo("Arquivo anexo", self.arquivo,
                               dica="Vários arquivos? Junte em um único ZIP. O nome do arquivo vira a descrição "
                                    "do documento.")
        card.add(self.c_arquivo)
        self.sem_anexo = QCheckBox("Este claim não tem anexo")
        self.sem_anexo.setCursor(Qt.PointingHandCursor)
        self.sem_anexo.toggled.connect(self._mudou_sem_anexo)
        card.add(self.sem_anexo)
        return card

    def _grupo_execucao(self) -> Card:
        card = Card("Execução", "Confira o resumo antes de criar")
        if not self.janela.producao:
            self.modo = Segmentado(list(self.rotulo_modo.values()))
            self.modo.set(self.rotulo_modo.get(self.cfg.modo, self.rotulo_modo["SIMULACAO"]))
            self.modo.mudou.connect(lambda _: (self._resetar_etapas(), self._atualizar_resumo()))
            card.add(Campo("Modo", self.modo, obrigatorio=False))
        self.resumo = QGridLayout()
        self.resumo.setHorizontalSpacing(12)
        self.resumo.setVerticalSpacing(6)
        self._resumo_valores: dict[str, object] = {}
        for i, nome in enumerate(("Tipo", "Ordem / item", "Anexo", "Modo")):
            self.resumo.addWidget(rotulo(nome, "Dica"), i, 0, Qt.AlignTop)
            valor = rotulo("—", quebra=True)
            self.resumo.addWidget(valor, i, 1)
            self._resumo_valores[nome] = valor
        self.resumo.setColumnStretch(1, 1)
        card.corpo.addLayout(self.resumo)

        botoes = QHBoxLayout()
        botoes.setSpacing(8)
        self.btn_limpar = Botao("Limpar", "secundario", "limpar", self._limpar_tudo)
        self.btn_validar = Botao("Validar", "secundario", "check", self._validar_tudo)
        self.btn_interromper = Botao("Interromper", "perigo", "parar", self._interromper)
        self.btn_interromper.setEnabled(False)
        botoes.addWidget(self.btn_limpar)
        botoes.addWidget(self.btn_validar)
        botoes.addStretch(1)
        botoes.addWidget(self.btn_interromper)
        card.corpo.addLayout(botoes)
        self.btn_executar = Botao(self._texto_executar(), "primario", "play", self._executar)
        self.btn_executar.setMinimumHeight(42)
        card.add(self.btn_executar)
        return card

    def _grupo_andamento(self) -> Card:
        card = Card("Andamento")
        self.tempo = LinhaDoTempo(ETAPAS)
        card.add(self.tempo)
        return card

    def _grupo_resultado(self) -> Card:
        card = Card("Resultado")
        self.selo = Badge()
        card.cabecalho.addWidget(self.selo, 0, Qt.AlignTop)
        self.msg_resultado = rotulo("Nenhuma execução nesta sessão.", "Dica", quebra=True)
        self.msg_resultado.setTextInteractionFlags(Qt.TextSelectableByMouse)
        card.add(self.msg_resultado)
        self.detalhes = QPlainTextEdit()
        self.detalhes.setObjectName("Mono")
        self.detalhes.setReadOnly(True)
        self.detalhes.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.detalhes.setMinimumHeight(140)
        self.detalhes.setVisible(False)
        card.add(self.detalhes)
        return card

    def _entrada(self, dica: str, campo: str) -> QLineEdit:
        e = QLineEdit()
        e.setPlaceholderText(dica)
        e.textEdited.connect(lambda _: self._mudou(campo))
        return e

    # ------------------------------------------------------------------ estado do formulário

    def _campos(self) -> dict:
        return {
            "tipo": self.rotas.get(self.tipo.get(), ""),
            "descricao": self.descricao.text(),
            "texto_livre": self.texto.toPlainText(),
            "ordem": self.ordem.text(),
            "item": self.item.text(),
            "arquivo": self.arquivo.caminho,
            "sem_anexo": self.sem_anexo.isChecked(),
            "linha_nova": self.linha_nova.isChecked(),
        }

    def _mudou(self, campo: str) -> None:
        self.tocados.add(campo)
        if campo == "descricao":
            n, maximo = tamanho_sap(self.descricao.text().strip()), self.cfg.limites.descricao_max
            self.contador.setText(f"{n}/{maximo}")
            self.contador.setObjectName("Erro" if n > maximo else "Dica")
            self.contador.style().polish(self.contador)
        if campo == "tipo":
            self._mostrar_rota()
            self._mostrar_linha()
        self._atualizar_resumo()
        self._timer_validacao.start()

    def _mostrar_rota(self) -> None:
        chave = self.rotas.get(self.tipo.get())
        if not chave:
            self.c_tipo.set_dica("Escolha o tipo para ver a rota de atividades.")
            return
        atividades = self.cfg.rota(chave).atividades
        contagem: dict[str, int] = {}
        for a in atividades:
            contagem[a.descricao] = contagem.get(a.descricao, 0) + 1
        nomes = [f"{a.descricao} · {a.subgrupo}" if contagem[a.descricao] > 1 else a.descricao for a in atividades]
        self.c_tipo.set_dica(f"Rota ({len(atividades)} atividades): " + "  →  ".join(nomes), azul=True)

    def _mudou_linha_nova(self, marcado: bool) -> None:
        if marcado:
            self.item.clear()
            self.item.setEnabled(False)
            self.item.setPlaceholderText("automático")
        else:
            self.item.setEnabled(True)
            self.item.setPlaceholderText("Ex.: 10")
        self._mostrar_linha()
        if not self.janela.executor.ocupado:
            self._resetar_etapas()
        self._mudou("item")

    def _mostrar_linha(self) -> None:
        if not self.linha_nova.isChecked():
            self.linha_info.setVisible(False)
            return
        chave = self.rotas.get(self.tipo.get())
        if not chave:
            texto = "Escolha o tipo: o material da linha vem dele."
        else:
            rota = self.cfg.rota(chave)
            texto = (f"Linha nova: material {rota.material or '—'} · centro {rota.centro or '—'} · quantidade "
                     f"{self.cfg.linha_quantidade}. O número do item é o próximo livre (de 10 em 10).")
        self.linha_info.setText(texto)
        self.linha_info.setVisible(True)

    def _mudou_sem_anexo(self, marcado: bool) -> None:
        self.arquivo.sem_anexo(marcado)
        if marcado:
            self.arquivo.caminho = ""
        self._mudou("arquivo")

    def _mostrar_erros(self) -> dict:
        erros = validar_formulario(self._campos(), self.cfg)
        campos = {"tipo": self.c_tipo, "descricao": self.c_descricao, "texto_livre": self.c_texto,
                  "ordem": self.c_ordem, "item": self.c_item, "arquivo": self.c_arquivo}
        for nome, campo in campos.items():
            campo.set_erro(erros.get(nome, "") if nome in self.tocados else "")
        self.arquivo.set_erro("arquivo" in self.tocados and "arquivo" in erros)
        return erros

    def _atualizar_resumo(self) -> None:
        c = self._campos()
        v = self._resumo_valores
        v["Tipo"].setText(self.tipo.get() or "—")
        item = "linha nova (VA22)" if c["linha_nova"] else (c["item"].strip() or "—")
        v["Ordem / item"].setText(f"{c['ordem'].strip() or '—'} / {item}")
        if c["sem_anexo"]:
            v["Anexo"].setText("sem anexo")
        else:
            v["Anexo"].setText((resumo_arquivo(c["arquivo"]) if c["arquivo"] else "") or "—")
        modo = self._modo_escolhido()
        grava = " · grava no SAP" if modo in ("ASSISTIDO", "AUTOMATICO") else ""
        v["Modo"].setText(("Criar claim (produção)" if self.janela.producao else ROTULO_MODO[modo]) + grava)

    def _validar_tudo(self) -> bool:
        self.tocados.update(CAMPOS)
        erros = self._mostrar_erros()
        if erros:
            self._resultado_texto("atencao", "Dados incompletos",
                                  f"{len(erros)} campo(s) precisam de ajuste antes de executar.")
        else:
            self._resultado_texto("ok", "Dados válidos", "Tudo certo. Pode executar.")
        return not erros

    def _tem_dados(self) -> bool:
        c = self._campos()
        return c["sem_anexo"] or any(str(v).strip() for k, v in c.items() if k not in ("sem_anexo", "linha_nova"))

    # ------------------------------------------------------------------ limpar

    def _limpar_conteudo_claim(self) -> None:
        """Apaga o que é de UM claim (descrição, texto, anexo, item, linha nova). Tipo e ordem ficam."""
        self.descricao.clear()
        self.texto.blockSignals(True)
        self.texto.clear()
        self.texto.blockSignals(False)
        self.arquivo.caminho = ""
        self.sem_anexo.blockSignals(True)
        self.sem_anexo.setChecked(False)
        self.sem_anexo.blockSignals(False)
        self.arquivo.sem_anexo(False)
        self.linha_nova.blockSignals(True)
        self.linha_nova.setChecked(False)
        self.linha_nova.blockSignals(False)
        self.item.setEnabled(True)
        self.item.setPlaceholderText("Ex.: 10")
        self.item.clear()
        self.linha_info.setVisible(False)
        self.contador.setText(f"0/{self.cfg.limites.descricao_max}")
        self.tocados.difference_update({"descricao", "texto_livre", "item", "arquivo"})
        self._atualizar_resumo()

    def _limpar_tudo(self) -> None:
        if self.janela.executor.ocupado:
            dialogos.informar(self, "Limpar", "Aguarde a execução em andamento terminar.")
            return
        if self._tem_dados() and not dialogos.confirmar(self, "Limpar", "Apagar os dados preenchidos e começar "
                                                        "um novo claim?", alerta=False):
            return
        self._limpar_conteudo_claim()
        self.tipo.set("")
        self.ordem.clear()
        self._mostrar_rota()
        self.tocados.clear()
        self._mostrar_erros()
        self._resetar_etapas()
        self._atualizar_resumo()
        self.selo.definir("")
        self.msg_resultado.setText("Pronto para um novo claim.")
        self.detalhes.clear()
        self.detalhes.setVisible(False)
        self.descricao.setFocus()

    # ------------------------------------------------------------------ vindo da cotação

    def preparar_claim(self, ordem: str, item: str, rota: str) -> None:
        if self.janela.executor.ocupado:
            dialogos.informar(self, "Aguarde", "Há uma execução em andamento. Aguarde terminar.")
            return
        conteudo = (self.descricao.text().strip() or self.texto.toPlainText().strip() or self.arquivo.caminho
                    or self.sem_anexo.isChecked())
        if conteudo and not dialogos.confirmar(
                self, "Novo claim", "O formulário de claim tem dados de outro claim (descrição, texto ou anexo)."
                                    "\n\nApagar esses dados e preencher para este item?", alerta=False):
            return
        self._limpar_conteudo_claim()
        self.janela.ir("claim")
        rotulos = {chave: r for r, chave in self.rotas.items()}
        self.tipo.set(rotulos.get(rota, ""))
        self.ordem.setText(ordem)
        self.item.setText(item)
        for campo in ("tipo", "ordem", "item"):
            self._mudou(campo)
        self._resetar_etapas()
        self._resultado_texto("info", "Da cotação",
                              f"Cotação {ordem}, item {item} preenchidos. Complete descrição, texto e anexo.")
        self.descricao.setFocus()

    # ------------------------------------------------------------------ execução

    def _modo_escolhido(self) -> str:
        if self.janela.producao:
            return "AUTOMATICO"
        inverso = {v: k for k, v in self.rotulo_modo.items()}
        return inverso.get(self.modo.get(), "SIMULACAO")

    def _texto_executar(self) -> str:
        return "Criar claim" if self.janela.producao else "Executar"

    def _executar(self) -> None:
        ex = self.janela.executor
        if ex.ocupado:
            texto = ("Verificando a conexão com o SAP (alguns segundos). Tente de novo em seguida."
                     if ex.verificando else "Há uma execução em andamento.")
            dialogos.informar(self, "Aguarde", texto)
            return
        if not self._validar_tudo():
            self.msg_resultado.setText("Corrija os campos marcados em vermelho.")
            return
        modo = self._modo_escolhido()
        avisos = {
            "ENSAIO": ("Ensaio no SAP", "A automação vai abrir uma janela própria no SAP e preencher a nota "
                       "e as atividades.\n\nNada será gravado."),
            "ASSISTIDO": ("Assistido — GRAVA o documento", "A automação vai preencher tudo e GRAVAR o documento "
                          "ZDC com o anexo no SAP de PRODUÇÃO.\n\nO claim NÃO será gravado: confira a janela e "
                          "grave você mesmo."),
            "AUTOMATICO": ("Completo — GRAVA o claim", "A automação vai GRAVAR o documento ZDC e o CLAIM no SAP "
                           "de PRODUÇÃO, com as atividades para os responsáveis da rota.\n\nConfirma?"),
        }
        # Produção: sem confirmação a cada claim (o clique com os dados validados é a autorização).
        if modo in avisos and not self.janela.producao:
            titulo, texto = avisos[modo]
            texto += "\n\nNão use a janela que a automação abrir até terminar."
            ok = (dialogos.confirmar(self, titulo, texto) if modo in ("ASSISTIDO", "AUTOMATICO")
                  else dialogos.ok_cancelar(self, titulo, texto))
            if not ok:
                return
        self._comecar(montar_request(self._campos()), modo)

    def _travar(self, travar: bool) -> None:
        for w in (self.descricao, self.ordem, self.texto, self.tipo, self.linha_nova, self.sem_anexo,
                  self.btn_validar):
            w.setEnabled(not travar)
        self.item.setEnabled(not travar and not self.linha_nova.isChecked())
        self.arquivo.setEnabled(not travar and not self.sem_anexo.isChecked())
        if hasattr(self, "modo"):
            self.modo.setEnabled(not travar)

    def _comecar(self, req, modo: str) -> None:
        self._ultimo_pedido = (req, modo)
        self._travar(True)
        self._resetar_etapas()
        self.janela.pagina_execucao.iniciar("claim", modo, req.linha_nova,
                                            f"Claim · ordem {req.ordem}/{req.item or 'linha nova'}")
        self._resultado_texto("info", "Em andamento", "Executando…")
        self.btn_executar.setEnabled(False)
        self.btn_executar.setText("Executando…")
        self.btn_interromper.setEnabled(True)
        self.btn_limpar.setEnabled(False)
        try:
            self.janela.executor.iniciar(req, modo)
        except Exception as erro:  # noqa: BLE001 - recusado antes de começar: a tela volta ao normal
            self._destravar_botoes()
            self._resultado_texto("atencao", "Não iniciado", f"{erro} Nada foi gravado.")

    def _destravar_botoes(self) -> None:
        self._travar(False)
        self.btn_executar.setEnabled(True)
        self.btn_executar.setText(self._texto_executar())
        self.btn_interromper.setEnabled(False)
        self.btn_interromper.setText("Interromper")
        self.btn_limpar.setEnabled(True)

    def _interromper(self) -> None:
        self.janela.executor.interromper()
        self.btn_interromper.setEnabled(False)
        self.btn_interromper.setText("Parando…")

    def _resetar_etapas(self) -> None:
        modo = self._modo_escolhido()
        ativas = [c for c, _ in etapas_do_modo(modo, self.linha_nova.isChecked())]
        self.tempo.preparar(ativas, f"não faz parte do modo {ROTULO_MODO[modo]}")

    def marcar_etapa(self, chave: str, situacao: str, detalhe: str) -> None:
        self.tempo.marcar(chave, situacao, detalhe)

    def _resultado_texto(self, tom: str, selo: str, mensagem: str) -> None:
        self.selo.definir(selo, tom)
        self.msg_resultado.setText(mensagem)

    def terminou(self, evento) -> None:
        self._destravar_botoes()
        if evento.resultado is not None:
            self._mostrar_resultado(evento.resultado)
        else:
            self._resultado_texto("erro", "Erro inesperado", evento.detalhe)

    def _mostrar_resultado(self, r) -> None:
        self._resultado_texto(TOM_ESTADO.get(r.estado, "atencao"), ROTULO_ESTADO.get(r.estado, r.estado.value),
                              r.mensagem)
        linhas = detalhes_claim(r)
        self.detalhes.setPlainText("\n".join(linhas))
        self.detalhes.setVisible(True)
        if r.estado in (Estado.ENSAIO_CONCLUIDO, Estado.CONCLUIDO) and self._modo_escolhido() != "SIMULACAO":
            QApplication.beep()
        if r.estado == Estado.CONCLUIDO and r.numero_nota:
            # Formulário pronto para o PRÓXIMO claim: um segundo clique não repete este (nem a linha nova).
            self._limpar_conteudo_claim()
            try:
                QGuiApplication.clipboard().setText(r.numero_nota)
            except Exception:  # noqa: BLE001 - só conveniência
                log.exception("área de transferência")
            # O tipo também sai: o próximo item pode ser de outro equipamento; só a ordem continua.
            self.tipo.set("")
            self.tocados.discard("tipo")          # tipo vazio de propósito: sem erro vermelho
            self._mostrar_rota()
            self._mostrar_erros()
            self._atualizar_resumo()
            self.msg_resultado.setText(f"{r.mensagem} O número foi copiado para a área de transferência. "
                                       "A ordem continua preenchida; escolha o tipo e o item do próximo claim.")
        if r.confirmar == "linha_extra" and self._ultimo_pedido is not None and not self.janela.fechando:
            req, modo = self._ultimo_pedido
            if dialogos.confirmar(self, "Outra linha nova?",
                                  f"{r.mensagem}\n\nCriar MAIS UMA linha nova ({req.tipo}) na cotação {req.ordem}, "
                                  "com documento ZDC e claim, GRAVANDO no SAP?", padrao_nao=True):
                self._comecar(replace(req, confirmar_linha_extra=True), modo)

    def mostrar_pendencias(self, n: int) -> None:
        self.faixa.definir("atencao", f"{n} execução(ões) pendente(s)", "Confira no SAP e resolva na página "
                                                                       "Pendências antes de repetir o claim.")
        self.faixa.setVisible(n > 0)


def detalhes_claim(r) -> list[str]:
    linhas = [f"Execução {r.execucao_id}"]
    if r.numero_nota:
        linhas.append(f"CLAIM CRIADO: nota {r.numero_nota}")
    if r.linha_criada:
        item = r.linha_criada.lstrip("?")
        linhas.append(f"LINHA NA COTAÇÃO: item {item}" + (" (sem confirmação)" if r.linha_criada.startswith("?") else ""))
    if r.documento_dms:
        linhas.append(f"Documento ZDC: {r.documento_dms}")
    for p in r.problemas:
        linhas.append(f"  [{p.campo}] {p.mensagem}")
    for a in r.avisos:
        linhas.append(f"Aviso aceito: {a}")
    if r.grade:
        linhas.append("")
        linhas.append("Atividades (antes de Transferir):")
        for i, linha in enumerate(r.grade, 1):
            sub, resp = linha.get("SUB_GRUPO", ""), linha.get("RESP", "")
            desc = linha.get("DS_ATIVIDADE") or linha.get("DESCRICAO") or linha.get("DESC_ATIV") or ""
            linhas.append(f"  {i}. {desc:<22} {sub:<11} {resp}")
    for c in r.conferencias:
        linhas.append(f"Conferir: {c}")
    return linhas
