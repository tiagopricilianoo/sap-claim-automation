# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Interface desktop da automação de claims (CustomTkinter).

Identidade visual: logo e cor principal (tema.ini). A tela só desenha e
reage; toda a lógica fica em controlador.py e claim_service.py.

Uso:  python ui.py
"""

from __future__ import annotations

import configparser
import logging
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

from claim_service import ETAPAS, Resultado, etapas_do_modo
from config import ConfigError, Settings, load_settings
from controlador import (
    ROTULO_MODO,
    ROTULO_ESTADO,
    TOM_ESTADO,
    Evento,
    Executor,
    linha_historico,
    modos_da_interface,
    montar_request,
    pendencias,
    resolver_pendencia,
    resumo_arquivo,
    validar_formulario,
)
from logger_config import configurar_logs
from sobre import COPYRIGHT
from state import Estado
from storage import Storage

RAIZ = Path(__file__).resolve().parent
AZUL_PADRAO = "#0E7490"


# ============================================================================ tema

def _misturar(cor: str, com: str, fracao: float) -> str:
    """Mistura duas cores hex (fração da segunda)."""
    a = [int(cor[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(com[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * fracao):02X}" for x, y in zip(a, b))


def _versao_instalada() -> str:
    try:
        return "v" + (RAIZ / "versao.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return "desenvolvimento"


def carregar_tema() -> dict[str, str]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(RAIZ / "tema.ini", encoding="utf-8")
    azul = parser.get("marca", "cor_principal", fallback=AZUL_PADRAO).strip() or AZUL_PADRAO
    return {
        "azul": azul,
        "azul_hover": _misturar(azul, "#000000", 0.18),
        "azul_claro": _misturar(azul, "#FFFFFF", 0.90),
        "fundo": "#F3F5F8",
        "cartao": "#FFFFFF",
        "borda": "#DCE2E9",
        "texto": "#1E2A38",
        "suave": "#5B6B7C",
        "ok": "#1E8E5A",
        "ok_claro": "#E4F4EC",
        "erro": "#C62828",
        "erro_claro": "#FBE9E9",
        "atencao": "#B26A00",
        "atencao_claro": "#FFF3E0",
        "inativo": "#AAB4BF",
    }


T = carregar_tema()
FONTE = "Segoe UI"


def fonte(tamanho: int = 13, peso: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=FONTE, size=tamanho, weight=peso)


def cartao(master, **kw) -> ctk.CTkFrame:
    return ctk.CTkFrame(master, fg_color=T["cartao"], corner_radius=12,
                        border_width=1, border_color=T["borda"], **kw)


def rotulo(master, texto: str, tamanho: int = 13, peso: str = "normal", cor: str | None = None, **kw):
    return ctk.CTkLabel(master, text=texto, font=fonte(tamanho, peso), text_color=cor or T["texto"],
                        anchor="w", justify="left", **kw)


# ============================================================================ janela

class App(ctk.CTk):
    def __init__(self, settings: Settings):
        super().__init__()
        self.cfg = settings
        # Produção: modo AUTOMATICO no settings.ini. Sem seletor de modo e sem confirmação
        # a cada claim; o clique em "Criar claim" (com os dados validados) é a autorização.
        self.producao = settings.modo == "AUTOMATICO"
        self.caminho_db = settings.pasta_dados / "historico.db"
        self.executor = Executor(settings, self.caminho_db)
        self.rotas = {r.rotulo: r.chave for r in settings.rotas.values()}
        self.arquivo = ""
        self.tocados: set[str] = set()
        self._validacao_agendada: str | None = None

        self.report_callback_exception = self._erro_inesperado
        self.title("Automação de Claims · CLM1")
        self.geometry("1220x800")
        self.minsize(1080, 720)
        self.configure(fg_color=T["fundo"])
        self.protocol("WM_DELETE_WINDOW", self._fechar)
        # O CustomTkinter aplica o ícone padrão dele ~200 ms após abrir: aplicamos o nosso depois.
        self.after(300, self._aplicar_icone)

        self._estilo_tabelas()
        self._cabecalho()
        rotulo(self, f"{COPYRIGHT} · Todos os direitos reservados", 10, cor=T["suave"]).pack(
            side="bottom", anchor="e", padx=24, pady=(0, 6))
        self.abas = ctk.CTkTabview(self, fg_color=T["fundo"], segmented_button_fg_color=T["borda"],
                                   segmented_button_selected_color=T["azul"],
                                   segmented_button_selected_hover_color=T["azul_hover"],
                                   segmented_button_unselected_color=T["cartao"],
                                   segmented_button_unselected_hover_color=T["azul_claro"],
                                   text_color=T["texto"], anchor="w",
                                   command=lambda: self._realcar(self.abas._segmented_button))
        self.abas.pack(fill="both", expand=True, padx=20, pady=(4, 16))
        self._aba_novo(self.abas.add("Novo claim"))
        self._aba_historico(self.abas.add("Histórico"))
        self._aba_pendencias(self.abas.add("Pendências"))

        self._realcar(self.abas._segmented_button)
        self._resetar_etapas()
        self._atualizar_listas()
        self._verificar_sap()
        self.after(100, self._processar_fila)

    # ------------------------------------------------------------------ cabeçalho

    def _aplicar_icone(self) -> None:
        try:
            self._icone = tk.PhotoImage(file=str(RAIZ / "assets" / "logo_80.png"))
            self.iconphoto(True, self._icone)
        except tk.TclError:
            pass

    def _cabecalho(self) -> None:
        topo = ctk.CTkFrame(self, fg_color=T["cartao"], corner_radius=0, height=72)
        topo.pack(fill="x")
        topo.pack_propagate(False)
        ctk.CTkFrame(self, fg_color=T["azul"], corner_radius=0, height=4).pack(fill="x")

        try:
            self._logo = tk.PhotoImage(file=str(RAIZ / "assets" / "logo_40.png"))
            tk.Label(topo, image=self._logo, bg=T["cartao"], bd=0).pack(side="left", padx=(24, 14))
        except tk.TclError:
            pass

        titulos = ctk.CTkFrame(topo, fg_color="transparent")
        titulos.pack(side="left", pady=12)
        rotulo(titulos, "Automação de Claims", 18, "bold", T["azul"]).pack(anchor="w")
        versao = _versao_instalada()
        rotulo(titulos, f"Transação CLM1 · Nota {self.cfg.tipo_nota} · Comercial · {versao}", 12,
               cor=T["suave"]).pack(anchor="w")

        lado = ctk.CTkFrame(topo, fg_color="transparent")
        lado.pack(side="right", padx=24)
        ctk.CTkButton(lado, text="Verificar", width=84, height=30, font=fonte(12),
                      fg_color="transparent", text_color=T["azul"], border_width=1,
                      border_color=T["azul"], hover_color=T["azul_claro"],
                      command=self._verificar_sap).pack(side="right")
        self.chip_sap = ctk.CTkLabel(lado, text="  SAP: verificando…  ", font=fonte(12, "bold"),
                                     fg_color=T["borda"], text_color=T["suave"], corner_radius=14, height=30)
        self.chip_sap.pack(side="right", padx=(0, 10))

    # ------------------------------------------------------------------ aba: novo claim

    def _aba_novo(self, aba) -> None:
        aba.grid_columnconfigure(0, weight=3, uniform="c")
        aba.grid_columnconfigure(1, weight=2, uniform="c")
        aba.grid_rowconfigure(1, weight=1)

        self.faixa = ctk.CTkLabel(aba, text="", font=fonte(12, "bold"), fg_color=T["atencao_claro"],
                                  text_color=T["atencao"], corner_radius=8, anchor="w")
        self._formulario(aba)
        self._painel_execucao(aba)

    def _formulario(self, aba) -> None:
        caixa = cartao(aba)
        caixa.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        corpo = ctk.CTkScrollableFrame(caixa, fg_color="transparent")
        corpo.pack(fill="both", expand=True, padx=8, pady=8)

        rotulo(corpo, "Novo claim", 20, "bold").pack(anchor="w", padx=12, pady=(4, 0))
        rotulo(corpo, "Preencha os dados recebidos. Os valores fixos do processo são aplicados automaticamente.",
               12, cor=T["suave"], wraplength=560, height=18).pack(anchor="w", padx=12, pady=(0, 6))

        self.erros: dict[str, ctk.CTkLabel] = {}

        # Tipo de claim
        self._titulo_campo(corpo, "Tipo de claim")
        self.tipo = ctk.CTkSegmentedButton(
            corpo, values=list(self.rotas), font=fonte(13, "bold"), height=36,
            selected_color=T["azul"], selected_hover_color=T["azul_hover"],
            unselected_color=T["fundo"], unselected_hover_color=T["azul_claro"],
            text_color=T["texto"], command=lambda _: (self._realcar(self.tipo), self._mudou("tipo")),
        )
        self.tipo.pack(fill="x", padx=12)
        self.tipo.set("")
        self._realcar(self.tipo)
        self.rota_info = rotulo(corpo, "Escolha o tipo para ver a rota de atividades.", 11, cor=T["suave"],
                                wraplength=560, height=18)
        self.rota_info.pack(anchor="w", padx=12, pady=(4, 0))
        self._erro(corpo, "tipo")

        # Descrição
        linha = self._titulo_campo(corpo, "Descrição")
        self.contador = rotulo(linha, f"0/{self.cfg.limites.descricao_max}", 11, cor=T["suave"])
        self.contador.pack(side="right")
        self.descricao = self._entrada(corpo, "Resumo do claim")
        self.descricao.bind("<KeyRelease>", lambda _: self._mudou("descricao"))
        self._erro(corpo, "descricao")

        # Texto livre
        self._titulo_campo(corpo, "Texto livre")
        self.texto = ctk.CTkTextbox(corpo, height=96, font=fonte(13), wrap="word", fg_color=T["cartao"],
                                    border_width=1, border_color=T["borda"], corner_radius=8,
                                    text_color=T["texto"])
        self.texto.pack(fill="x", padx=12)
        self.texto.bind("<KeyRelease>", lambda _: self._mudou("texto_livre"))
        self._erro(corpo, "texto_livre")

        # Ordem e item
        dupla = ctk.CTkFrame(corpo, fg_color="transparent")
        dupla.pack(fill="x")
        dupla.grid_columnconfigure(0, weight=3)
        dupla.grid_columnconfigure(1, weight=1)
        col_ordem = ctk.CTkFrame(dupla, fg_color="transparent")
        col_ordem.grid(row=0, column=0, sticky="ew")
        col_item = ctk.CTkFrame(dupla, fg_color="transparent")
        col_item.grid(row=0, column=1, sticky="ew")
        self._titulo_campo(col_ordem, "Ordem do cliente")
        self.ordem = self._entrada(col_ordem, "Ex.: 1234567")
        self.ordem.bind("<KeyRelease>", lambda _: self._mudou("ordem"))
        self._erro(col_ordem, "ordem")
        self._titulo_campo(col_item, "Item")
        self.item = self._entrada(col_item, "Ex.: 10")
        self.item.bind("<KeyRelease>", lambda _: self._mudou("item"))
        self._erro(col_item, "item")

        # Arquivo
        self._titulo_campo(corpo, "Arquivo anexo")
        arq = ctk.CTkFrame(corpo, fg_color=T["fundo"], corner_radius=8, border_width=1, border_color=T["borda"])
        arq.pack(fill="x", padx=12)
        self.arq_frame = arq
        self.arq_nome = rotulo(arq, "Nenhum arquivo selecionado", 12, cor=T["suave"])
        self.arq_nome.pack(side="left", padx=12, pady=10, fill="x", expand=True)
        ctk.CTkButton(arq, text="Selecionar…", width=110, height=32, font=fonte(12, "bold"),
                      fg_color=T["azul"], hover_color=T["azul_hover"],
                      command=self._escolher_arquivo).pack(side="right", padx=8, pady=6)
        rotulo(corpo, "Vários arquivos? Junte em um único ZIP. O nome do arquivo vira a descrição do documento.",
               11, cor=T["suave"], wraplength=560, height=18).pack(anchor="w", padx=12, pady=(3, 0))
        self._erro(corpo, "arquivo")

        # Valores fixos
        prioridade = "Normal" if self.cfg.prioridade == "1" else self.cfg.prioridade
        fixos = ctk.CTkFrame(corpo, fg_color=T["azul_claro"], corner_radius=8)
        fixos.pack(fill="x", padx=12, pady=(14, 6))
        rotulo(fixos, "Aplicado automaticamente", 11, "bold", T["azul"]).pack(anchor="w", padx=12, pady=(8, 0))
        rotulo(fixos, f"Nota {self.cfg.tipo_nota} · Causa {self.cfg.causa_grupo}/{self.cfg.causa_codigo} · "
                      f"Prioridade {prioridade} · Documento {self.cfg.doc_tipo}/{self.cfg.doc_laboratorio} · "
                      f"Comercial = seu usuário SAP", 12, wraplength=540).pack(anchor="w", padx=12, pady=(0, 8))

        # Rodapé: modo + ações
        rodape = ctk.CTkFrame(caixa, fg_color="transparent")
        rodape.pack(fill="x", padx=20, pady=(4, 16))
        self.rotulo_modo = {m: ROTULO_MODO[m] for m in modos_da_interface(self.cfg)}
        if not self.producao:
            rotulo(rodape, "Modo", 12, "bold", T["suave"]).pack(side="left")
            self.modo = ctk.CTkSegmentedButton(
                rodape, values=list(self.rotulo_modo.values()), font=fonte(12), height=32,
                selected_color=T["azul"], selected_hover_color=T["azul_hover"],
                unselected_color=T["fundo"], unselected_hover_color=T["azul_claro"], text_color=T["texto"],
                command=lambda _: (self._realcar(self.modo), self._resetar_etapas()),
            )
            self.modo.pack(side="left", padx=(10, 0))
            self.modo.set(self.rotulo_modo.get(self.cfg.modo, self.rotulo_modo["SIMULACAO"]))
            self._realcar(self.modo)

        self.btn_executar = ctk.CTkButton(rodape, text=self._texto_executar(), width=150, height=38,
                                          font=fonte(13, "bold"), fg_color=T["azul"],
                                          hover_color=T["azul_hover"], command=self._executar)
        self.btn_executar.pack(side="right")
        self.btn_interromper = ctk.CTkButton(rodape, text="Interromper", width=110, height=38,
                                             font=fonte(12, "bold"), fg_color="transparent",
                                             text_color=T["erro"], border_width=1, border_color=T["erro"],
                                             hover_color=T["erro_claro"], state="disabled",
                                             command=self._interromper)
        self.btn_interromper.pack(side="right", padx=8)
        ctk.CTkButton(rodape, text="Validar", width=90, height=38, font=fonte(12, "bold"),
                      fg_color="transparent", text_color=T["azul"], border_width=1, border_color=T["azul"],
                      hover_color=T["azul_claro"], command=self._validar_tudo).pack(side="right")
        self.btn_limpar = ctk.CTkButton(rodape, text="⟲  Limpar tudo", width=120, height=38,
                                        font=fonte(12, "bold"), fg_color="transparent",
                                        text_color=T["suave"], border_width=1, border_color=T["borda"],
                                        hover_color=T["fundo"], command=self._limpar_tudo)
        self.btn_limpar.pack(side="right", padx=8)

    @staticmethod
    def _realcar(segmentado) -> None:
        """Texto branco no botão selecionado e escuro nos demais (contraste sobre o azul)."""
        atual = segmentado.get()
        for valor, botao in getattr(segmentado, "_buttons_dict", {}).items():
            botao.configure(text_color="#FFFFFF" if valor == atual else T["texto"])

    def _titulo_campo(self, master, texto: str) -> ctk.CTkFrame:
        linha = ctk.CTkFrame(master, fg_color="transparent")
        linha.pack(fill="x", padx=12, pady=(8, 3))
        rotulo(linha, texto, 13, "bold").pack(side="left")
        rotulo(linha, " *", 13, "bold", T["erro"]).pack(side="left")
        return linha

    def _entrada(self, master, dica: str) -> ctk.CTkEntry:
        campo = ctk.CTkEntry(master, placeholder_text=dica, height=36, font=fonte(13), corner_radius=8,
                             fg_color=T["cartao"], border_color=T["borda"], text_color=T["texto"])
        campo.pack(fill="x", padx=12)
        return campo

    def _erro(self, master, campo: str) -> None:
        msg = rotulo(master, "", 11, cor=T["erro"], wraplength=540, height=16)
        msg.pack(anchor="w", padx=12)
        self.erros[campo] = msg

    # ------------------------------------------------------------------ painel de execução

    def _painel_execucao(self, aba) -> None:
        lado = ctk.CTkFrame(aba, fg_color="transparent")
        lado.grid(row=1, column=1, sticky="nsew", padx=(10, 0))
        lado.grid_rowconfigure(1, weight=1)
        lado.grid_columnconfigure(0, weight=1)

        andamento = cartao(lado)
        andamento.grid(row=0, column=0, sticky="ew")
        rotulo(andamento, "Andamento", 16, "bold").pack(anchor="w", padx=18, pady=(14, 2))
        self.barra = ctk.CTkProgressBar(andamento, height=8, progress_color=T["azul"], fg_color=T["borda"])
        self.barra.pack(fill="x", padx=18, pady=(6, 10))
        self.barra.set(0)

        self.etapas: dict[str, tuple[ctk.CTkLabel, ctk.CTkLabel, ctk.CTkLabel]] = {}
        for chave, titulo in ETAPAS:
            self.etapas[chave] = self._linha_etapa(andamento, titulo)
        ctk.CTkFrame(andamento, fg_color="transparent", height=8).pack()

        resultado = cartao(lado)
        resultado.grid(row=1, column=0, sticky="nsew", pady=(16, 0))
        topo = ctk.CTkFrame(resultado, fg_color="transparent")
        topo.pack(fill="x", padx=18, pady=(14, 6))
        rotulo(topo, "Resultado", 16, "bold").pack(side="left")
        self.selo = ctk.CTkLabel(topo, text="", font=fonte(11, "bold"), corner_radius=12, height=24)
        self.selo.pack(side="right")
        self.msg_resultado = rotulo(resultado, "Nenhuma execução nesta sessão.", 12, cor=T["suave"],
                                    wraplength=540)
        self.msg_resultado.pack(anchor="w", padx=18)
        self.detalhes = ctk.CTkTextbox(resultado, font=ctk.CTkFont(family="Consolas", size=11),
                                       fg_color=T["fundo"], text_color=T["texto"], corner_radius=8,
                                       wrap="none", height=160)
        self.detalhes.pack(fill="both", expand=True, padx=18, pady=(10, 16))
        self.detalhes.configure(state="disabled")

    def _linha_etapa(self, master, titulo: str):
        linha = ctk.CTkFrame(master, fg_color="transparent")
        linha.pack(fill="x", padx=18, pady=3)
        icone = ctk.CTkLabel(linha, text="○", width=22, font=fonte(15, "bold"), text_color=T["inativo"])
        icone.pack(side="left")
        nome = rotulo(linha, titulo, 13)
        nome.pack(side="left", padx=(6, 0))
        detalhe = rotulo(linha, "", 11, cor=T["suave"])
        detalhe.pack(side="right")
        return icone, nome, detalhe

    # ------------------------------------------------------------------ abas de listas

    def _estilo_tabelas(self) -> None:
        estilo = ttk.Style(self)
        try:
            estilo.theme_use("clam")
        except tk.TclError:
            pass
        estilo.configure("Claim.Treeview", font=(FONTE, 10), rowheight=30, background=T["cartao"],
                         fieldbackground=T["cartao"], foreground=T["texto"], borderwidth=0)
        estilo.configure("Claim.Treeview.Heading", font=(FONTE, 10, "bold"), background=T["fundo"],
                         foreground=T["suave"], relief="flat", padding=(8, 6))
        estilo.map("Claim.Treeview", background=[("selected", T["azul_claro"])],
                   foreground=[("selected", T["texto"])])

    def _tabela(self, master) -> ttk.Treeview:
        colunas = (("quando", "Quando", 110), ("estado", "Estado", 190), ("tipo", "Tipo", 150),
                   ("ordem", "Ordem/Item", 130), ("nota", "Nota", 120), ("duracao", "Duração", 80),
                   ("id", "Execução", 130))
        caixa = cartao(master)
        caixa.pack(fill="both", expand=True)
        arvore = ttk.Treeview(caixa, columns=[c for c, _, _ in colunas], show="headings", style="Claim.Treeview")
        for chave, titulo, largura in colunas:
            arvore.heading(chave, text=titulo, anchor="w")
            arvore.column(chave, width=largura, anchor="w")
        arvore.tag_configure("ok", foreground=T["ok"])
        arvore.tag_configure("erro", foreground=T["erro"])
        arvore.tag_configure("atencao", foreground=T["atencao"])
        rolagem = ttk.Scrollbar(caixa, orient="vertical", command=arvore.yview)
        arvore.configure(yscrollcommand=rolagem.set)
        rolagem.pack(side="right", fill="y", padx=(0, 6), pady=10)
        arvore.pack(fill="both", expand=True, padx=(10, 0), pady=10)
        return arvore

    def _aba_historico(self, aba) -> None:
        topo = ctk.CTkFrame(aba, fg_color="transparent")
        topo.pack(fill="x", pady=(0, 10))
        rotulo(topo, "Últimas execuções", 16, "bold").pack(side="left")
        ctk.CTkButton(topo, text="Atualizar", width=90, height=30, font=fonte(12), fg_color="transparent",
                      text_color=T["azul"], border_width=1, border_color=T["azul"], hover_color=T["azul_claro"],
                      command=self._atualizar_listas).pack(side="right")
        self.tabela_hist = self._tabela(aba)

    def _aba_pendencias(self, aba) -> None:
        rotulo(aba, "Execuções que pedem atenção", 16, "bold").pack(anchor="w")
        rotulo(aba, "Execuções interrompidas no meio ou sem confirmação de gravação. Confira no SAP antes de "
                    "criar o claim de novo: a automação nunca repete uma gravação sozinha.",
               12, cor=T["suave"], wraplength=900).pack(anchor="w", pady=(2, 10))
        acoes = ctk.CTkFrame(aba, fg_color="transparent")
        acoes.pack(fill="x", pady=(0, 10))
        rotulo(acoes, "Selecione uma linha e, depois de conferir no SAP:", 12, cor=T["suave"]).pack(side="left")
        ctk.CTkButton(acoes, text="✕  Não foi criado", width=150, height=32, font=fonte(12, "bold"),
                      fg_color="transparent", text_color=T["erro"], border_width=1, border_color=T["erro"],
                      hover_color=T["erro_claro"], command=lambda: self._resolver(False)).pack(side="right")
        ctk.CTkButton(acoes, text="✓  Claim criado…", width=150, height=32, font=fonte(12, "bold"),
                      fg_color=T["ok"], hover_color=_misturar(T["ok"], "#000000", 0.18),
                      command=lambda: self._resolver(True)).pack(side="right", padx=8)
        self.tabela_pend = self._tabela(aba)

    def _resolver(self, criado: bool) -> None:
        selecao = self.tabela_pend.selection()
        if not selecao:
            messagebox.showinfo("Pendências", "Selecione uma execução na lista.")
            return
        valores = self.tabela_pend.item(selecao[0], "values")
        execucao_id, ordem = valores[-1], valores[3]
        numero = ""
        if criado:
            dialogo = ctk.CTkInputDialog(title="Claim criado",
                                         text=f"Ordem {ordem}\nNúmero da nota conferida no SAP:")
            numero = (dialogo.get_input() or "").strip()
            if not numero:
                return
            pergunta = f"Registrar a execução {execucao_id} como CONCLUÍDA, nota {numero}?"
        else:
            pergunta = (f"Confirma que o claim da execução {execucao_id} (ordem {ordem}) NÃO existe no SAP?\n\n"
                        "Isso libera uma nova execução para esta ordem/item.")
        if not messagebox.askyesno("Resolver pendência", pergunta, icon="warning"):
            return
        try:
            db = Storage(self.caminho_db)
            try:
                resolver_pendencia(db, execucao_id, criado=criado, numero_nota=numero)
            finally:
                db.close()
        except (ValueError, KeyError) as erro:
            messagebox.showerror("Resolver pendência", str(erro))
            return
        self._atualizar_listas()

    def _preencher(self, tabela: ttk.Treeview, execucoes) -> None:
        tabela.delete(*tabela.get_children())
        for e in execucoes:
            tabela.insert("", "end", values=linha_historico(e), tags=(TOM_ESTADO.get(e.estado, "neutro"),))

    def _atualizar_listas(self) -> None:
        try:
            db = Storage(self.caminho_db)
            try:
                self._preencher(self.tabela_hist, db.recentes(100))
                pend = pendencias(db)
                self._preencher(self.tabela_pend, pend)
            finally:
                db.close()
        except Exception as erro:  # noqa: BLE001
            messagebox.showerror("Histórico", f"Não foi possível ler o histórico:\n{erro}")
            return
        if pend:
            self.faixa.configure(text=f"   ⚠  {len(pend)} execução(ões) pendente(s). Veja a aba Pendências.")
            self.faixa.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10), ipady=6)
        else:
            self.faixa.grid_forget()

    # ------------------------------------------------------------------ formulário: estado

    def _campos(self) -> dict[str, str]:
        return {
            "tipo": self.rotas.get(self.tipo.get(), ""),
            "descricao": self.descricao.get(),
            "texto_livre": self.texto.get("1.0", "end-1c"),
            "ordem": self.ordem.get(),
            "item": self.item.get(),
            "arquivo": self.arquivo,
        }

    def _mudou(self, campo: str) -> None:
        self.tocados.add(campo)
        if campo == "descricao":
            n, maximo = len(self.descricao.get().strip()), self.cfg.limites.descricao_max
            self.contador.configure(text=f"{n}/{maximo}", text_color=T["erro"] if n > maximo else T["suave"])
        if campo == "tipo":
            self._mostrar_rota()
        if self._validacao_agendada:
            self.after_cancel(self._validacao_agendada)
        self._validacao_agendada = self.after(250, self._mostrar_erros)

    def _mostrar_rota(self) -> None:
        chave = self.rotas.get(self.tipo.get())
        if not chave:
            return
        atividades = self.cfg.rota(chave).atividades
        contagem: dict[str, int] = {}
        for a in atividades:
            contagem[a.descricao] = contagem.get(a.descricao, 0) + 1
        nomes = [f"{a.descricao} · {a.subgrupo}" if contagem[a.descricao] > 1 else a.descricao for a in atividades]
        self.rota_info.configure(text=f"Rota ({len(atividades)} atividades): " + "  →  ".join(nomes),
                                 text_color=T["azul"])

    def _mostrar_erros(self) -> dict[str, str]:
        self._validacao_agendada = None
        erros = validar_formulario(self._campos(), self.cfg)
        bordas = {"descricao": self.descricao, "texto_livre": self.texto, "ordem": self.ordem,
                  "item": self.item, "arquivo": self.arq_frame}
        for campo, msg in self.erros.items():
            texto = erros.get(campo, "") if campo in self.tocados else ""
            msg.configure(text=texto)
            if campo in bordas:
                bordas[campo].configure(border_color=T["erro"] if texto else T["borda"])
        return erros

    def _validar_tudo(self) -> bool:
        self.tocados.update(self.erros)
        erros = self._mostrar_erros()
        if erros:
            self._mostrar_resultado_texto("atencao", "Dados incompletos",
                                          f"{len(erros)} campo(s) precisam de ajuste antes de executar.")
        else:
            self._mostrar_resultado_texto("ok", "Dados válidos", "Tudo certo. Pode executar.")
        return not erros

    def _escolher_arquivo(self) -> None:
        caminho = filedialog.askopenfilename(title="Selecione o arquivo do claim")
        if not caminho:
            return
        self.arquivo = caminho
        self.arq_nome.configure(text=resumo_arquivo(caminho) or Path(caminho).name, text_color=T["texto"])
        self._mudou("arquivo")

    def _tem_dados(self) -> bool:
        c = self._campos()
        return any(str(v).strip() for v in c.values())

    def _limpar_tudo(self) -> None:
        """Prepara a tela para um novo claim: formulário, andamento e resultado."""
        if self.executor.ocupado:
            return
        if self._tem_dados() and not messagebox.askyesno(
            "Limpar tudo", "Apagar os dados preenchidos e começar um novo claim?"
        ):
            return
        self._limpar()
        self.selo.configure(text="", fg_color="transparent")
        self.msg_resultado.configure(text="Pronto para um novo claim.", text_color=T["suave"])
        self.detalhes.configure(state="normal")
        self.detalhes.delete("1.0", "end")
        self.detalhes.configure(state="disabled")
        self.descricao.focus_set()

    def _limpar(self) -> None:
        if self.executor.ocupado:
            return
        self.tipo.set("")
        self._realcar(self.tipo)
        for campo in (self.descricao, self.ordem, self.item):
            campo.delete(0, "end")
        self.texto.delete("1.0", "end")
        self.arquivo = ""
        self.arq_nome.configure(text="Nenhum arquivo selecionado", text_color=T["suave"])
        self.rota_info.configure(text="Escolha o tipo para ver a rota de atividades.", text_color=T["suave"])
        self.contador.configure(text=f"0/{self.cfg.limites.descricao_max}", text_color=T["suave"])
        self.tocados.clear()
        self._mostrar_erros()
        self._resetar_etapas()

    # ------------------------------------------------------------------ execução

    def _modo_escolhido(self) -> str:
        if self.producao:
            return "AUTOMATICO"
        inverso = {v: k for k, v in self.rotulo_modo.items()}
        return inverso.get(self.modo.get(), "SIMULACAO")

    def _texto_executar(self) -> str:
        return "Criar claim" if self.producao else "Executar"

    def _executar(self) -> None:
        if self.executor.ocupado or not self._validar_tudo():
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
        if modo in avisos and not self.producao:
            titulo, texto = avisos[modo]
            pergunta = messagebox.askyesno if modo in ("ASSISTIDO", "AUTOMATICO") else messagebox.askokcancel
            if not pergunta(titulo, texto + "\n\nNão use a janela que a automação abrir até terminar.",
                            icon="warning" if modo != "ENSAIO" else "info"):
                return
        self._resetar_etapas()
        self._mostrar_resultado_texto("neutro", "Em andamento", "Executando…")
        self.btn_executar.configure(state="disabled", text="Executando…")
        self.btn_interromper.configure(state="normal")
        self.btn_limpar.configure(state="disabled")
        self.executor.iniciar(montar_request(self._campos()), modo)

    def _interromper(self) -> None:
        self.executor.interromper()
        self.btn_interromper.configure(state="disabled", text="Parando…")

    def _verificar_sap(self) -> None:
        self.chip_sap.configure(text="  SAP: verificando…  ", fg_color=T["borda"], text_color=T["suave"])
        self.executor.verificar_sap()

    def _processar_fila(self) -> None:
        for evento in self.executor.drenar():
            self._tratar(evento)
        self.after(100, self._processar_fila)

    def _tratar(self, evento: Evento) -> None:
        if evento.tipo == "etapa":
            self._marcar_etapa(evento.etapa, evento.situacao, evento.detalhe)
        elif evento.tipo == "sap":
            if evento.situacao == "ok":
                self.chip_sap.configure(text=f"  ●  SAP conectado · {evento.detalhe}  ",
                                        fg_color=T["ok_claro"], text_color=T["ok"])
            else:
                self.chip_sap.configure(text="  ●  SAP indisponível  ", fg_color=T["erro_claro"],
                                        text_color=T["erro"])
                self._mostrar_resultado_texto("atencao", "SAP", evento.detalhe)
        elif evento.tipo in ("fim", "erro"):
            self.btn_executar.configure(state="normal", text=self._texto_executar())
            self.btn_interromper.configure(state="disabled", text="Interromper")
            self.btn_limpar.configure(state="normal")
            if evento.resultado is not None:
                self._mostrar_resultado(evento.resultado)
            else:
                self._mostrar_resultado_texto("erro", "Erro inesperado", evento.detalhe)
            self._atualizar_listas()

    def _resetar_etapas(self) -> None:
        self.barra.set(0)
        modo = self._modo_escolhido() if (self.producao or hasattr(self, "modo")) else "SIMULACAO"
        do_modo = {c for c, _ in etapas_do_modo(modo)}
        for chave, (icone, nome, detalhe) in self.etapas.items():
            ativa = chave in do_modo
            icone.configure(text="○", text_color=T["inativo"])
            nome.configure(text_color=T["texto"] if ativa else T["inativo"], font=fonte(13))
            detalhe.configure(text="" if ativa else f"não faz parte do modo {ROTULO_MODO[modo]}",
                              text_color=T["suave"] if ativa else T["inativo"])

    def _marcar_etapa(self, chave: str, situacao: str, detalhe: str) -> None:
        if chave not in self.etapas:
            return
        icone, nome, rot = self.etapas[chave]
        if situacao == "ativo":
            icone.configure(text="●", text_color=T["azul"])
            nome.configure(font=fonte(13, "bold"))
            rot.configure(text="em andamento…", text_color=T["azul"])
        elif situacao == "ok":
            icone.configure(text="✓", text_color=T["ok"])
            nome.configure(font=fonte(13))
            rot.configure(text=detalhe, text_color=T["suave"])
        else:
            icone.configure(text="✕", text_color=T["erro"])
            nome.configure(font=fonte(13, "bold"))
            rot.configure(text="falhou", text_color=T["erro"])
        do_modo = [c for c, _ in etapas_do_modo(self._modo_escolhido())]
        feitas = sum(1 for c in do_modo if self.etapas[c][0].cget("text") == "✓")
        self.barra.set(feitas / max(1, len(do_modo)))

    def _mostrar_resultado_texto(self, tom: str, selo: str, mensagem: str) -> None:
        cores = {"ok": (T["ok_claro"], T["ok"]), "erro": (T["erro_claro"], T["erro"]),
                 "atencao": (T["atencao_claro"], T["atencao"]), "neutro": (T["azul_claro"], T["azul"])}
        fundo, texto = cores.get(tom, cores["neutro"])
        self.selo.configure(text=f"  {selo}  ", fg_color=fundo, text_color=texto)
        self.msg_resultado.configure(text=mensagem, text_color=T["texto"])

    def _mostrar_resultado(self, r: Resultado) -> None:
        self._mostrar_resultado_texto(TOM_ESTADO.get(r.estado, "atencao"),
                                      ROTULO_ESTADO.get(r.estado, r.estado.value), r.mensagem)
        linhas = [f"Execução {r.execucao_id}"]
        if r.numero_nota:
            linhas.append(f"CLAIM CRIADO: nota {r.numero_nota}")
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
        self.detalhes.configure(state="normal")
        self.detalhes.delete("1.0", "end")
        self.detalhes.insert("1.0", "\n".join(linhas))
        self.detalhes.configure(state="disabled")
        if r.estado in (Estado.ENSAIO_CONCLUIDO, Estado.CONCLUIDO) and self._modo_escolhido() != "SIMULACAO":
            self.bell()
        if r.estado == Estado.CONCLUIDO and r.numero_nota:
            self.clipboard_clear()
            self.clipboard_append(r.numero_nota)
            self.msg_resultado.configure(text=f"{r.mensagem} O número foi copiado para a área de transferência.")

    # ------------------------------------------------------------------ encerramento

    def _erro_inesperado(self, tipo, valor, rastro) -> None:
        """Sem console (atalho), um erro da tela não pode sumir em silêncio."""
        logging.getLogger("claim.ui").error("Erro inesperado na interface", exc_info=(tipo, valor, rastro))
        messagebox.showerror("Erro inesperado",
                             f"{valor}\n\nO detalhe foi registrado no log. Se repetir, avise o responsável "
                             "pela ferramenta.")

    def _fechar(self) -> None:
        if self.executor.ocupado and not messagebox.askyesno(
            "Execução em andamento",
            "Há uma execução em andamento. Deseja interromper e fechar?",
        ):
            return
        self.executor.interromper()
        self.destroy()


def main() -> None:
    try:
        settings = load_settings()
    except ConfigError as erro:
        tk.Tk().withdraw()
        messagebox.showerror("Configuração", f"Erro no settings.ini:\n\n{erro}")
        return
    configurar_logs(settings.pasta_dados)
    ctk.set_appearance_mode("light")
    App(settings).mainloop()


if __name__ == "__main__":
    main()
