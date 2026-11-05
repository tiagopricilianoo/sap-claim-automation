# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Aviso de atualização do Python do programa na interface anterior (CustomTkinter).

Mesmo fluxo da interface nova: perguntar, baixar com barra (sem travar a tela) e reiniciar.
"""

from __future__ import annotations

import logging
import queue
import threading

import customtkinter as ctk

import atualizacao_python as ap
from tema_ui import EmSegundoPlano, T, fonte, rotulo

log = logging.getLogger("claim.ui.atualizacao")


class JanelaAtualizacao(ctk.CTkToplevel):
    def __init__(self, app, locais: ap.Locais):
        super().__init__(app)
        self.app, self.l = app, locais
        self.title("Atualização disponível")
        self.geometry("480x220")
        self.resizable(False, False)
        self.configure(fg_color=T["cartao"])
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self._fechar)
        self.titulo = rotulo(self, "Há uma nova atualização disponível", 16, "bold")
        self.titulo.pack(anchor="w", padx=24, pady=(20, 4))
        self.texto = rotulo(self, "Deseja baixar? A nova versão entra quando o programa reiniciar.", 12,
                            cor=T["suave"], wraplength=430)
        self.texto.pack(anchor="w", padx=24)
        self.barra = ctk.CTkProgressBar(self, height=8, progress_color=T["azul"], fg_color=T["borda"])
        self.barra.set(0)
        self.detalhe = rotulo(self, "", 11, cor=T["suave"])
        botoes = ctk.CTkFrame(self, fg_color="transparent")
        botoes.pack(side="bottom", fill="x", padx=24, pady=18)
        self.b_principal = ctk.CTkButton(botoes, text="Baixar agora", width=140, height=36, font=fonte(13, "bold"),
                                         fg_color=T["azul"], hover_color=T["azul_hover"], command=self._baixar)
        self.b_principal.pack(side="right")
        self.b_secundario = ctk.CTkButton(botoes, text="Atualizar depois", width=140, height=36, font=fonte(12, "bold"),
                                          fg_color="transparent", text_color=T["texto"], border_width=1,
                                          border_color=T["borda"], hover_color=T["fundo"], command=self._fechar)
        self.b_secundario.pack(side="right", padx=8)
        self._fila: queue.Queue = queue.Queue()
        self._cancelar = threading.Event()
        self._baixando = False
        self.after(50, self.grab_set)

    def _fechar(self) -> None:
        if self._baixando:
            self._cancelar.set()
            return
        self.grab_release()
        self.destroy()

    def _baixar(self) -> None:
        self._baixando = True
        self.titulo.configure(text="Baixando a atualização…")
        self.texto.configure(text="Copiando do servidor. Pode levar alguns minutos.")
        self.barra.pack(fill="x", padx=24, pady=(12, 4))
        self.detalhe.pack(anchor="w", padx=24)
        self.b_principal.pack_forget()
        self.b_secundario.configure(text="Cancelar")

        def trabalho():
            try:
                ok = ap.baixar(self.l, lambda f, t: self._fila.put(("progresso", (f, t))), self._cancelar.is_set)
                self._fila.put(("fim", ok))
            except Exception as erro:  # noqa: BLE001
                log.exception("Falha ao baixar o Python novo")
                self._fila.put(("erro", erro))

        threading.Thread(target=trabalho, daemon=True, name="baixar-python").start()
        self.after(80, self._conferir)

    def _conferir(self) -> None:
        while True:
            try:
                tipo, dado = self._fila.get_nowait()
            except queue.Empty:
                self.after(80, self._conferir)
                return
            if tipo == "progresso":
                feito, total = dado
                self.barra.set(feito / max(1, total))
                self.detalhe.configure(text=f"{feito / 1048576:.0f} de {total / 1048576:.0f} MB")
                continue
            self._baixando = False
            if tipo == "erro":
                self._fim("Não foi possível baixar", f"{dado}\n\nO programa continua como está.", False)
            elif dado:
                self._fim("Atualização pronta", "Reinicie o programa para usar a nova versão.", True)
            else:
                self._fechar()
            return

    def _fim(self, titulo: str, texto: str, ok: bool) -> None:
        self.titulo.configure(text=titulo)
        self.texto.configure(text=texto)
        self.detalhe.pack_forget()
        self.b_secundario.configure(text="Na próxima vez" if ok else "Fechar")
        if ok:
            self.b_principal.configure(text="Reiniciar agora", command=self._reiniciar)
            self.b_principal.pack(side="right")

    def _reiniciar(self) -> None:
        if self.app.executor.ocupado:
            self.texto.configure(text="Há uma execução em andamento. Reinicie quando ela terminar (ou na próxima vez).")
            return
        try:
            ap.reiniciar_com_python_novo(self.l)
        except Exception as erro:  # noqa: BLE001
            self.texto.configure(text=f"Não foi possível reiniciar agora ({erro}). A troca acontece na próxima abertura.")
            return
        self.grab_release()
        self.destroy()
        self.app._encerrar()


def verificar(app) -> None:
    l = ap.locais()
    if l is None:
        return

    def terminou(disponivel: bool) -> None:
        if disponivel and not app.executor.ocupado and not app._fechando:
            JanelaAtualizacao(app, l)

    EmSegundoPlano(app, lambda _p: ap.disponivel(l) and not ap.pronto_para_trocar(l), terminou,
                   lambda erro: log.warning("Verificação de atualização falhou: %s", erro))
