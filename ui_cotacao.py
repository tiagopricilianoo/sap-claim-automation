# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Aba "Nova cotação" (VA21 + pastas) e aba "Cotações" (histórico e pendências).

A tela guia o orçamentista: ao preencher, a prévia mostra exatamente o que será
criado; durante a execução, o andamento mostra cada etapa; no fim, os próximos
passos aparecem como botões (criar o claim de cada linha, abrir a pasta, e-mail).
"""

from __future__ import annotations

import logging
import os
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import messagebox, ttk

import customtkinter as ctk

from controlador import (ROTULO_ESTADO, TOM_ESTADO, Evento, filtrar_cotacoes, linha_cotacao,
                         modos_cotacao_da_interface, resolver_cotacao)
from cotacao import (
    PAISES_POR_REGIAO,
    CotacaoRequest,
    regioes_do_tipo,
    tipos_disponiveis,
    validar_cotacao,
)
from cotacao_service import ETAPAS_COTACAO, ResultadoCotacao, etapas_cotacao_do_modo
from pastas import CaminhoMuitoLongo, ProjetoJaExiste, abrir_email, criar_pastas, planejar_pastas
from state import Estado
from storage_cotacao import CotacaoStorage
from tema_ui import EmSegundoPlano, T, _misturar, cartao, fonte, rotulo

log = logging.getLogger("claim.ui.cotacao")
ROTULO_MODO_COTACAO = {"SIMULACAO": "Simulação", "ENSAIO": "Ensaio", "AUTOMATICO": "Criar (grava)"}
CAMPOS = ("tipo", "regiao", "pais", "cliente", "projeto", "equipamentos")


class Lista(ttk.Combobox):
    """ttk.Combobox somente leitura com a interface de um CTkOptionMenu (get/set/configure)."""

    def __init__(self, master, comando) -> None:
        super().__init__(master, state="readonly", style="Cotacao.TCombobox", font=fonte_tk(13), height=14)
        self._comando = comando
        self.bind("<<ComboboxSelected>>", lambda _: self._comando(self.get()))

    def configure(self, values=None, state=None, **kw):  # noqa: D401 - mesma assinatura usada na aba
        if values is not None:
            kw["values"] = [v for v in values if v and v != "—"]
        if state is not None:
            kw["state"] = "readonly" if state == "normal" else "disabled"
        return super().configure(**kw)

    def set(self, valor: str) -> None:
        estado = str(self.cget("state"))
        super().configure(state="normal")
        super().set(valor)
        super().configure(state=estado)


def fonte_tk(tamanho: int, peso: str = "normal") -> tuple:
    from tema_ui import FONTE
    return (FONTE, tamanho, peso) if peso != "normal" else (FONTE, tamanho)


def estilo_listas(janela) -> None:
    estilo = ttk.Style(janela)
    estilo.configure("Cotacao.TCombobox", padding=(10, 4), fieldbackground=T["fundo"], background=T["borda"],
                     foreground=T["texto"], arrowcolor=T["suave"], bordercolor=T["borda"])
    estilo.map("Cotacao.TCombobox", fieldbackground=[("readonly", T["fundo"]), ("disabled", T["fundo"])],
               foreground=[("disabled", T["inativo"])])
    janela.option_add("*TCombobox*Listbox.font", fonte_tk(12))
    janela.option_add("*TCombobox*Listbox.selectBackground", T["azul"])


class AbaCotacao:
    def __init__(self, app, aba, aba_lista) -> None:
        self.app = app
        self.cfg = app.cfg
        self.producao = app.producao
        self.erros: dict[str, ctk.CTkLabel] = {}
        self.tocados: set[str] = set()
        self._agendado: str | None = None
        self.ultimo: ResultadoCotacao | None = None
        self.ultimo_req: CotacaoRequest | None = None

        estilo_listas(app)
        aba.grid_columnconfigure(0, weight=3, uniform="c")
        aba.grid_columnconfigure(1, weight=2, uniform="c")
        aba.grid_rowconfigure(1, weight=1)
        self.faixa = ctk.CTkLabel(aba, text="", font=fonte(12, "bold"), fg_color=T["atencao_claro"],
                                  text_color=T["atencao"], corner_radius=8, anchor="w")
        self._formulario(aba)
        self._painel(aba)
        self._lista(aba_lista)
        self._mudou_tipo(self.tipo.get())
        self.resetar_etapas()

    # ================================================================== formulário

    def _formulario(self, aba) -> None:
        caixa = cartao(aba)
        caixa.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        corpo = ctk.CTkScrollableFrame(caixa, fg_color="transparent")
        corpo.pack(fill="both", expand=True, padx=8, pady=8)

        rotulo(corpo, "Nova cotação", 20, "bold").pack(anchor="w", padx=12, pady=(4, 4))

        self._titulo(corpo, "Tipo de cotação")
        tipos = list(tipos_disponiveis(self.cfg))
        self.tipo = ctk.CTkSegmentedButton(
            corpo, values=tipos, font=fonte(13, "bold"), height=36, selected_color=T["azul"],
            selected_hover_color=T["azul_hover"], unselected_color=T["fundo"],
            unselected_hover_color=T["azul_claro"], text_color=T["texto"], command=self._mudou_tipo)
        self.tipo.pack(fill="x", padx=12)
        self.tipo.set(tipos[0] if tipos else "")
        self._erro(corpo, "tipo")

        dupla = ctk.CTkFrame(corpo, fg_color="transparent")
        dupla.pack(fill="x")
        dupla.grid_columnconfigure((0, 1), weight=1)
        col_reg = ctk.CTkFrame(dupla, fg_color="transparent")
        col_reg.grid(row=0, column=0, sticky="ew")
        col_pais = ctk.CTkFrame(dupla, fg_color="transparent")
        col_pais.grid(row=0, column=1, sticky="ew")
        self._titulo(col_reg, "Região")
        self.regiao = self._menu(col_reg, self._mudou_regiao)
        self._erro(col_reg, "regiao")
        self._titulo(col_pais, "País")
        self.pais = self._menu(col_pais, lambda _: self._mudou("pais"))
        self._erro(col_pais, "pais")

        dupla2 = ctk.CTkFrame(corpo, fg_color="transparent")
        dupla2.pack(fill="x")
        dupla2.grid_columnconfigure((0, 1), weight=1)
        col_cli = ctk.CTkFrame(dupla2, fg_color="transparent")
        col_cli.grid(row=0, column=0, sticky="ew")
        col_proj = ctk.CTkFrame(dupla2, fg_color="transparent")
        col_proj.grid(row=0, column=1, sticky="ew")
        self._titulo(col_cli, "Cliente")
        self.cliente = self._entrada(col_cli, "Nome do cliente")
        self.cliente.bind("<KeyRelease>", lambda _: self._mudou("cliente"))
        self._erro(col_cli, "cliente")
        self._titulo(col_proj, "Projeto")
        self.projeto = self._entrada(col_proj, "Nome do projeto")
        self.projeto.bind("<KeyRelease>", lambda _: self._mudou("projeto"))
        self._erro(col_proj, "projeto")

        self._titulo(corpo, "Equipamentos")
        linha = ctk.CTkFrame(corpo, fg_color="transparent")
        linha.pack(fill="x", padx=12)
        self.produto_a = ctk.BooleanVar(value=False)
        self.produto_b = ctk.BooleanVar(value=False)
        for texto, var in (("Produto A", self.produto_a), ("Produto B", self.produto_b)):
            ctk.CTkCheckBox(linha, text=texto, variable=var, font=fonte(13), text_color=T["texto"],
                            fg_color=T["azul"], hover_color=T["azul_hover"], border_color=T["borda"],
                            checkbox_width=20, checkbox_height=20,
                            command=lambda: self._mudou("equipamentos")).pack(side="left", padx=(0, 22))
        ctk.CTkCheckBox(linha, text="Gerador · em breve", font=fonte(13), state="disabled",
                        text_color_disabled=T["inativo"], checkbox_width=20, checkbox_height=20,
                        border_color=T["borda"]).pack(side="left")
        self._erro(corpo, "equipamentos")


        rodape = ctk.CTkFrame(caixa, fg_color="transparent")
        rodape.pack(fill="x", padx=20, pady=(4, 16))
        self.rotulo_modo = {m: ROTULO_MODO_COTACAO[m] for m in modos_cotacao_da_interface(self.cfg)}
        if not self.producao:
            rotulo(rodape, "Modo", 12, "bold", T["suave"]).pack(side="left")
            self.modo = ctk.CTkSegmentedButton(
                rodape, values=list(self.rotulo_modo.values()), font=fonte(12), height=32,
                selected_color=T["azul"], selected_hover_color=T["azul_hover"], unselected_color=T["fundo"],
                unselected_hover_color=T["azul_claro"], text_color=T["texto"],
                command=lambda _: (self.app._realcar(self.modo), self.resetar_etapas()))
            self.modo.pack(side="left", padx=(10, 0))
            self.modo.set(self.rotulo_modo.get("ENSAIO", "Simulação"))
            self.app._realcar(self.modo)
        self.btn_criar = ctk.CTkButton(rodape, text="Criar cotação", width=150, height=38, font=fonte(13, "bold"),
                                       fg_color=T["azul"], hover_color=T["azul_hover"], command=self._criar)
        self.btn_criar.pack(side="right")
        self.btn_parar = ctk.CTkButton(rodape, text="Interromper", width=110, height=38, font=fonte(12, "bold"),
                                       fg_color="transparent", text_color=T["erro"], border_width=1,
                                       border_color=T["erro"], hover_color=T["erro_claro"], state="disabled",
                                       command=self._interromper)
        self.btn_parar.pack(side="right", padx=8)
        self.btn_limpar = ctk.CTkButton(rodape, text="⟲  Limpar", width=100, height=38, font=fonte(12, "bold"),
                                        fg_color="transparent", text_color=T["suave"], border_width=1,
                                        border_color=T["borda"], hover_color=T["fundo"], command=self.limpar)
        self.btn_limpar.pack(side="right")

    def _titulo(self, master, texto: str) -> None:
        linha = ctk.CTkFrame(master, fg_color="transparent")
        linha.pack(fill="x", padx=12, pady=(8, 3))
        rotulo(linha, texto, 13, "bold").pack(side="left")
        rotulo(linha, " *", 13, "bold", T["erro"]).pack(side="left")

    def _entrada(self, master, dica: str) -> ctk.CTkEntry:
        campo = ctk.CTkEntry(master, placeholder_text=dica, height=36, font=fonte(13), corner_radius=8,
                             fg_color=T["cartao"], border_color=T["borda"], text_color=T["texto"])
        campo.pack(fill="x", padx=12)
        return campo

    def _menu(self, master, comando) -> "Lista":
        """Lista suspensa nativa: rola com a roda do mouse e tem barra de rolagem (países)."""
        lista = Lista(master, comando)
        lista.pack(fill="x", padx=12, ipady=5)
        return lista

    def _erro(self, master, campo: str) -> None:
        msg = rotulo(master, "", 11, cor=T["erro"], wraplength=520)
        msg.pack(anchor="w", padx=12)
        self.erros[campo] = msg

    # ------------------------------------------------------------------ reações

    def _mudou_tipo(self, tipo: str) -> None:
        self.app._realcar(self.tipo)
        regioes = list(regioes_do_tipo(tipo))
        self.regiao.configure(values=regioes or ["—"], state="normal" if regioes else "disabled")
        self.regiao.set("" if regioes else "Europa")
        self.pais.configure(values=["—"], state="disabled")
        self.pais.set("Cliente Especial" if tipo == "Cliente Especial" else "")
        especial = tipo == "Cliente Especial"
        self.cliente.configure(state="normal")
        if especial:
            self.cliente.delete(0, "end")
        self.cliente.configure(state="disabled" if especial else "normal",
                               placeholder_text="não se aplica" if especial else "Nome do cliente")
        self._mudou("tipo")

    def _mudou_regiao(self, regiao: str) -> None:
        exportacao = self.tipo.get() == "Exportação"
        paises = list(PAISES_POR_REGIAO.get(regiao, ())) if exportacao else []
        self.pais.configure(values=paises or ["—"], state="normal" if paises else "disabled")
        self.pais.set("")
        self._mudou("regiao")

    def _mudou(self, campo: str) -> None:
        self.tocados.add(campo)
        if self._agendado:
            self.app.after_cancel(self._agendado)
        self._agendado = self.app.after(250, self._atualizar)

    def _request(self) -> CotacaoRequest:
        return CotacaoRequest.from_form(
            tipo=self.tipo.get(), regiao=self.regiao.get(), pais=self.pais.get(), cliente=self.cliente.get(),
            projeto=self.projeto.get(), produto_a=self.produto_a.get(), produto_b=self.produto_b.get())

    def _atualizar(self) -> list:
        """Erros por campo + prévia do que será criado (só com dados locais, sem acessar a rede)."""
        self._agendado = None
        req = self._request()
        problemas = validar_cotacao(req, self.cfg)
        por_campo: dict[str, str] = {}
        for p in problemas:
            por_campo.setdefault(p.campo, p.mensagem)
        for campo, msg in self.erros.items():
            msg.configure(text=por_campo.get(campo, "") if campo in self.tocados else "")
        for campo, entrada in (("cliente", self.cliente), ("projeto", self.projeto)):
            entrada.configure(border_color=T["erro"] if campo in self.tocados and campo in por_campo else T["borda"])
        return problemas

    # ------------------------------------------------------------------ execução

    def _modo(self) -> str:
        if self.producao:
            return "AUTOMATICO"
        inverso = {v: k for k, v in self.rotulo_modo.items()}
        return inverso.get(self.modo.get(), "SIMULACAO")

    def _criar(self) -> None:
        if self.app.executor.ocupado:
            messagebox.showinfo("Aguarde", "Há uma execução em andamento.")
            return
        self.tocados.update(CAMPOS)
        if self._atualizar():
            self._texto_resultado("atencao", "Dados incompletos", "Corrija os campos marcados.")
            return
        req, modo = self._request(), self._modo()
        if modo == "AUTOMATICO":
            # A pasta de propostas fica na rede: conferir em segundo plano para a tela não congelar.
            # Sem confirmação extra (como no claim): o clique em "Criar cotação" com os dados
            # validados é a autorização. O resumo fica registrado no histórico da execução.
            self.btn_criar.configure(state="disabled", text="Conferindo pastas…")
            self._texto_resultado("neutro", "Conferindo", "Conferindo a pasta de propostas na rede…")

            def falhou(erro: Exception) -> None:
                self.btn_criar.configure(state="normal", text="Criar cotação")
                if isinstance(erro, (ProjetoJaExiste, CaminhoMuitoLongo)):
                    messagebox.showwarning("Cotação não criada", str(erro))
                    self._texto_resultado("atencao", "Não criada", str(erro).split("\n")[0])
                elif isinstance(erro, OSError):
                    messagebox.showerror("Rede", f"Não consegui acessar a pasta de propostas na rede:\n{erro}")
                    self._texto_resultado("erro", "Rede", "Pasta de propostas inacessível. Nada foi criado.")
                else:
                    messagebox.showerror("Cotação não criada", str(erro))
                    self._texto_resultado("erro", "Não criada", "Erro ao conferir as pastas. Nada foi criado.")

            EmSegundoPlano(self.app, lambda perguntar: planejar_pastas(req, self.cfg.cotacao, perguntar=perguntar),
                           lambda plano: self._comecar(req, modo, plano), falhou)
            return
        if modo == "ENSAIO":
            if not messagebox.askokcancel("Ensaio no SAP", "A automação vai abrir uma janela própria no SAP e "
                                          "preencher a VA21.\n\nNada será gravado e nenhuma pasta será criada."):
                return
        self._comecar(req, modo, None)

    def _comecar(self, req, modo: str, plano_pastas) -> None:
        if self.app.executor.ocupado:      # outra aba começou enquanto as pastas eram conferidas
            self.btn_criar.configure(state="normal", text="Criar cotação")
            messagebox.showinfo("Aguarde", "Há uma execução em andamento. Nada foi criado.")
            return
        self.ultimo_req = req
        self.resetar_etapas()
        self._limpar_proximos()
        self._texto_resultado("neutro", "Em andamento", "Criando a cotação…")
        self.btn_criar.configure(state="disabled", text="Criando…")
        self.btn_parar.configure(state="normal")
        self.btn_limpar.configure(state="disabled")
        self.app.executor.iniciar_cotacao(req, modo, plano_pastas)

    def _interromper(self) -> None:
        self.app.executor.interromper()
        self.btn_parar.configure(state="disabled", text="Parando…")

    def tratar(self, evento: Evento) -> None:
        if evento.tipo == "etapa":
            self._marcar(evento.etapa, evento.situacao, evento.detalhe)
            return
        self.btn_criar.configure(state="normal", text="Criar cotação")
        self.btn_parar.configure(state="disabled", text="Interromper")
        self.btn_limpar.configure(state="normal")
        if isinstance(evento.resultado, ResultadoCotacao):
            self._mostrar(evento.resultado)
        else:
            self._texto_resultado("erro", "Erro inesperado", evento.detalhe)
        self.atualizar_lista()

    # ================================================================== painel

    def _painel(self, aba) -> None:
        lado = ctk.CTkFrame(aba, fg_color="transparent")
        lado.grid(row=1, column=1, sticky="nsew", padx=(10, 0))
        lado.grid_rowconfigure(1, weight=1)
        lado.grid_columnconfigure(0, weight=1)

        andamento = cartao(lado)
        andamento.grid(row=0, column=0, sticky="ew")
        rotulo(andamento, "Andamento", 16, "bold").pack(anchor="w", padx=18, pady=(14, 2))
        self.barra = ctk.CTkProgressBar(andamento, height=8, progress_color=T["azul"], fg_color=T["borda"])
        self.barra.pack(fill="x", padx=18, pady=(6, 10))
        self.etapas = {chave: self.app._linha_etapa(andamento, titulo) for chave, titulo in ETAPAS_COTACAO}
        ctk.CTkFrame(andamento, fg_color="transparent", height=8).pack()

        resultado = cartao(lado)
        resultado.grid(row=1, column=0, sticky="nsew", pady=(16, 0))
        topo = ctk.CTkFrame(resultado, fg_color="transparent")
        topo.pack(fill="x", padx=18, pady=(14, 6))
        rotulo(topo, "Resultado", 16, "bold").pack(side="left")
        self.selo = ctk.CTkLabel(topo, text="", font=fonte(11, "bold"), corner_radius=12, height=24)
        self.selo.pack(side="right")
        self.msg = rotulo(resultado, "Nenhuma cotação nesta sessão.", 12, cor=T["suave"], wraplength=520)
        self.msg.pack(anchor="w", padx=18)
        self.proximos = ctk.CTkFrame(resultado, fg_color="transparent")
        self.proximos.pack(fill="x", padx=18, pady=(8, 0))
        self.detalhes = ctk.CTkTextbox(resultado, font=ctk.CTkFont(family="Consolas", size=11),
                                       fg_color=T["fundo"], text_color=T["texto"], corner_radius=8,
                                       wrap="none", height=110)
        self.detalhes.pack(fill="both", expand=True, padx=18, pady=(10, 16))
        self.detalhes.configure(state="disabled")

    def resetar_etapas(self) -> None:
        self.barra.set(0)
        modo = self._modo() if (self.producao or hasattr(self, "modo")) else "SIMULACAO"
        do_modo = {c for c, _ in etapas_cotacao_do_modo(modo)}
        for chave, (icone, nome, detalhe) in self.etapas.items():
            ativa = chave in do_modo
            icone.configure(text="○", text_color=T["inativo"])
            nome.configure(text_color=T["texto"] if ativa else T["inativo"], font=fonte(13))
            detalhe.configure(text="" if ativa else "não faz parte do ensaio",
                              text_color=T["suave"] if ativa else T["inativo"])

    def _marcar(self, chave: str, situacao: str, detalhe: str) -> None:
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
            rot.configure(text=detalhe[:48], text_color=T["suave"])
        else:
            icone.configure(text="✕", text_color=T["erro"])
            nome.configure(font=fonte(13, "bold"))
            rot.configure(text="falhou", text_color=T["erro"])
        do_modo = [c for c, _ in etapas_cotacao_do_modo(self._modo())]
        feitas = sum(1 for c in do_modo if self.etapas[c][0].cget("text") == "✓")
        self.barra.set(feitas / max(1, len(do_modo)))

    def _texto_resultado(self, tom: str, selo: str, mensagem: str) -> None:
        cores = {"ok": (T["ok_claro"], T["ok"]), "erro": (T["erro_claro"], T["erro"]),
                 "atencao": (T["atencao_claro"], T["atencao"]), "neutro": (T["azul_claro"], T["azul"])}
        fundo, texto = cores.get(tom, cores["neutro"])
        self.selo.configure(text=f"  {selo}  ", fg_color=fundo, text_color=texto)
        self.msg.configure(text=mensagem, text_color=T["texto"])

    def _limpar_proximos(self) -> None:
        for filho in self.proximos.winfo_children():
            filho.destroy()

    def _botao(self, master, texto: str, comando, principal: bool = False) -> ctk.CTkButton:
        if principal:
            return ctk.CTkButton(master, text=texto, height=34, font=fonte(12, "bold"), fg_color=T["azul"],
                                 hover_color=T["azul_hover"], command=comando, anchor="w")
        return ctk.CTkButton(master, text=texto, height=30, font=fonte(12), fg_color="transparent",
                             text_color=T["azul"], border_width=1, border_color=T["azul"],
                             hover_color=T["azul_claro"], command=comando)

    def _mostrar(self, r: ResultadoCotacao) -> None:
        self.ultimo = r
        self._texto_resultado(TOM_ESTADO.get(r.estado, "atencao"), ROTULO_ESTADO.get(r.estado, r.estado.value),
                              r.mensagem)
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
        self.detalhes.configure(state="normal")
        self.detalhes.delete("1.0", "end")
        self.detalhes.insert("1.0", "\n".join(linhas))
        self.detalhes.configure(state="disabled")

        self._limpar_proximos()
        if r.estado == Estado.CONCLUIDO and r.numero:
            self.app.clipboard_clear()
            self.app.clipboard_append(r.numero)
            self.app.bell()
            texto = f"{r.mensagem} O número foi copiado."
            if r.aviso_pastas:
                texto += f"\n\n{r.aviso_pastas}"
                self._texto_resultado("atencao", "Criada, sem pastas", texto)
            else:
                self.msg.configure(text=texto)
            destaque = ctk.CTkFrame(self.proximos, fg_color=T["ok_claro"], corner_radius=10)
            destaque.pack(fill="x")
            rotulo(destaque, f"Cotação {r.numero}", 22, "bold", T["ok"]).pack(anchor="w", padx=16, pady=(12, 0))
            rotulo(destaque, "Próximo passo: criar o claim de cada linha", 13, cor=T["texto"]).pack(
                anchor="w", padx=16, pady=(0, 8))
            for linha in r.linhas:
                ctk.CTkButton(destaque, text=f"＋  Criar claim · item {linha['item']} · {linha['equipamento']}",
                              height=48, font=fonte(15, "bold"), fg_color=T["azul"], hover_color=T["azul_hover"],
                              corner_radius=10,
                              command=lambda l=linha: self.app.preparar_claim(r.numero, l["item"], l["rota"])
                              ).pack(fill="x", padx=16, pady=(0, 8))
            ctk.CTkFrame(destaque, fg_color="transparent", height=4).pack()
            extras = ctk.CTkFrame(self.proximos, fg_color="transparent")
            extras.pack(fill="x", pady=(8, 0))
            if r.pasta:
                self._botao(extras, "Abrir pasta", lambda: self._abrir_pasta(r.pasta)).pack(side="left")
                self._botao(extras, "E-mail no Outlook", self._email).pack(side="left", padx=6)
        elif r.estado == Estado.ENSAIO_CONCLUIDO:
            self.app.bell()

    def _abrir_pasta(self, pasta: str) -> None:
        try:
            os.startfile(pasta)  # type: ignore[attr-defined]
        except (OSError, AttributeError) as erro:
            messagebox.showwarning("Abrir pasta", f"Não foi possível abrir:\n{pasta}\n\n{erro}")

    def _email(self) -> None:
        r, req = self.ultimo, self.ultimo_req
        if r is None or req is None:
            return
        try:
            abrir_email(req, r.numero, Path(r.pasta), req.equipamentos)
        except Exception as erro:  # noqa: BLE001
            messagebox.showerror("E-mail", f"Não foi possível abrir o Outlook:\n{erro}")

    def limpar(self) -> None:
        if self.app.executor.ocupado:
            return
        self.cliente.configure(state="normal")
        for campo in (self.cliente, self.projeto):
            campo.delete(0, "end")
        self.produto_a.set(False)
        self.produto_b.set(False)
        self.tocados.clear()
        self._mudou_tipo(self.tipo.get())
        self._limpar_proximos()
        self.selo.configure(text="", fg_color="transparent")
        self.msg.configure(text="Pronto para uma nova cotação.", text_color=T["suave"])
        self.resetar_etapas()

    # ================================================================== aba Cotações

    def _lista(self, aba) -> None:
        topo = ctk.CTkFrame(aba, fg_color="transparent")
        topo.pack(fill="x", pady=(0, 10))
        rotulo(topo, "Cotações", 18, "bold").pack(side="left")
        self.filtro = ctk.CTkEntry(topo, placeholder_text="🔍  Filtrar por cliente, projeto ou número…", width=380,
                                   height=38, font=fonte(13), corner_radius=8, fg_color=T["cartao"],
                                   border_color=T["borda"], text_color=T["texto"])
        self.filtro.pack(side="left", padx=(18, 0))
        self.filtro.bind("<KeyRelease>", lambda _: self._mostrar_lista())
        self._botao(topo, "Atualizar", self.atualizar_lista).pack(side="right")

        acoes = ctk.CTkFrame(aba, fg_color="transparent")
        acoes.pack(fill="x", pady=(0, 10))
        ctk.CTkButton(acoes, text="＋  Criar claim da cotação selecionada", height=40, font=fonte(13, "bold"),
                      fg_color=T["azul"], hover_color=T["azul_hover"], corner_radius=10,
                      command=self._claim_da_selecionada).pack(side="left")
        ctk.CTkButton(acoes, text="✕  Não foi criada", width=150, height=34, font=fonte(12, "bold"),
                      fg_color="transparent", text_color=T["erro"], border_width=1, border_color=T["erro"],
                      hover_color=T["erro_claro"], command=lambda: self._resolver(False)).pack(side="right")
        ctk.CTkButton(acoes, text="✓  Cotação existe…", width=150, height=34, font=fonte(12, "bold"),
                      fg_color=T["ok"], hover_color=_misturar(T["ok"], "#000000", 0.18),
                      command=lambda: self._resolver(True)).pack(side="right", padx=8)
        rotulo(acoes, "Sem confirmação? Confira na VA23 e informe:", 12, cor=T["suave"]).pack(side="right", padx=8)

        colunas = (("quando", "Quando", 120), ("cliente", "Cliente", 240), ("projeto", "Projeto", 240),
                   ("numero", "Cotação", 110), ("itens", "Linhas", 190), ("estado", "Situação", 170),
                   ("tipo", "Tipo", 100))
        caixa = cartao(aba)
        caixa.pack(fill="both", expand=True)
        self.tabela = ttk.Treeview(caixa, columns=[c for c, _, _ in colunas], show="headings",
                                   style="Claim.Treeview")
        for chave, titulo, largura in colunas:
            self.tabela.heading(chave, text=titulo, anchor="w")
            self.tabela.column(chave, width=largura, anchor="w")
        for tom in ("ok", "erro", "atencao"):
            self.tabela.tag_configure(tom, foreground=T[tom])
        self.tabela.bind("<Double-1>", lambda _: self._claim_da_selecionada())
        rolagem = ttk.Scrollbar(caixa, orient="vertical", command=self.tabela.yview)
        self.tabela.configure(yscrollcommand=rolagem.set)
        rolagem.pack(side="right", fill="y", padx=(0, 6), pady=10)
        self.tabela.pack(fill="both", expand=True, padx=(10, 0), pady=10)
        self._registros: list = []

    def atualizar_lista(self) -> None:
        try:
            db = CotacaoStorage(self.app.caminho_db)
            try:
                self._registros, pendentes = db.recentes(500), db.pendentes()
            finally:
                db.close()
        except Exception as erro:  # noqa: BLE001
            log.warning("Histórico de cotações ilegível: %s", erro)
            return
        self._mostrar_lista()
        if pendentes:
            self.faixa.configure(text=f"   ⚠  {len(pendentes)} cotação(ões) sem confirmação. Veja a aba Cotações.")
            self.faixa.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10), ipady=6)
        else:
            self.faixa.grid_forget()

    def _mostrar_lista(self) -> None:
        self.tabela.delete(*self.tabela.get_children())
        for c in filtrar_cotacoes(self._registros, self.filtro.get()):
            self.tabela.insert("", "end", iid=c.id, values=linha_cotacao(c),
                               tags=(TOM_ESTADO.get(c.estado, "neutro"),))

    def _selecionada(self) -> str | None:
        selecao = self.tabela.selection()
        if not selecao:
            messagebox.showinfo("Cotações", "Selecione uma cotação na lista.")
            return None
        return selecao[0]

    def _claim_da_selecionada(self) -> None:
        cid = self._selecionada()
        if not cid:
            return
        db = CotacaoStorage(self.app.caminho_db)
        try:
            registro = db.obter(cid)
        finally:
            db.close()
        if not registro.numero or not registro.lista_linhas:
            messagebox.showinfo("Cotações", "Esta cotação não tem número/linhas registrados.")
            return
        linha = registro.lista_linhas[0]
        if len(registro.lista_linhas) > 1:
            opcoes = ", ".join(f"{l['item']} ({l['equipamento']})" for l in registro.lista_linhas)
            item = ctk.CTkInputDialog(title="Criar claim", text=f"Qual item? {opcoes}").get_input()
            if item is None:            # cancelou
                return
            digitado = item.strip().lstrip("0")         # '010' = '10', como no SAP
            escolhidas = [l for l in registro.lista_linhas if l["item"].lstrip("0") == digitado]
            if not escolhidas:
                messagebox.showinfo("Criar claim", f"O item '{item.strip()}' não é desta cotação. Itens: {opcoes}.")
                return
            linha = escolhidas[0]
        self.app.preparar_claim(registro.numero, linha["item"], linha["rota"])

    def _resolver(self, criada: bool) -> None:
        if self.app.executor.ocupado:
            messagebox.showinfo("Cotações", "Há uma execução em andamento. Aguarde terminar para resolver.")
            return
        cid = self._selecionada()
        if not cid:
            return
        numero = ""
        if criada:
            numero = (ctk.CTkInputDialog(title="Cotação existe", text="Número da cotação conferido na VA23:")
                      .get_input() or "").strip()
            if not numero:
                return
        elif not messagebox.askyesno("Cotação não criada", "Confirma que esta cotação NÃO existe no SAP?",
                                     icon="warning"):
            return
        db = CotacaoStorage(self.app.caminho_db)
        registro = None
        try:
            resolver_cotacao(db, cid, criada=criada, numero=numero)
            registro = db.obter(cid)
        except Exception as erro:  # noqa: BLE001 - qualquer recusa vira mensagem (nada foi mudado)
            messagebox.showerror("Cotações", str(erro))
        finally:
            db.close()
        self.atualizar_lista()
        if criada and registro is not None:
            self._pastas_depois(registro, numero)

    def _pastas_depois(self, registro, numero: str) -> None:
        """Pastas de uma cotação resolvida como 'existe' (a execução não chegou a criá-las)."""
        if registro.modo != "AUTOMATICO":
            return
        problemas = validar_cotacao(registro.request, self.cfg)     # o histórico pode ser antigo/editado
        if problemas:
            messagebox.showwarning("Pastas", "A cotação foi registrada, mas as pastas não foram criadas: "
                                   "os dados guardados não passam mais na validação:\n"
                                   + "\n".join(p.mensagem for p in problemas))
            return

        def trabalho(perguntar):
            plano = planejar_pastas(registro.request, self.cfg.cotacao, perguntar=perguntar)
            return criar_pastas(plano, numero)

        def terminou(pasta) -> None:
            db = CotacaoStorage(self.app.caminho_db)
            try:
                db.registrar_pasta(registro.id, str(pasta))
            finally:
                db.close()
            self.atualizar_lista()
            messagebox.showinfo("Pastas criadas", f"Pastas da proposta criadas:\n{pasta}")

        def falhou(erro: Exception) -> None:
            if isinstance(erro, ProjetoJaExiste):
                messagebox.showwarning(
                    "Pastas", "A cotação foi registrada. A pasta deste projeto JÁ EXISTE na rede, então nenhuma "
                    "pasta nova foi criada. Confira se ela é desta cotação:\n\n" + str(erro).split("\n\n")[0])
            else:
                messagebox.showwarning("Pastas", f"A cotação foi registrada, mas as pastas não foram criadas:\n{erro}")

        EmSegundoPlano(self.app, trabalho, terminou, falhou)
