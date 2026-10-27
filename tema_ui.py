# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Tema visual compartilhado pelas telas (cores do tema.ini, fontes e componentes básicos)."""

from __future__ import annotations

import configparser
import os
from pathlib import Path

import customtkinter as ctk

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


# ---------------------------------------------------------------------------- correção do CustomTkinter
# O CTkScrollableFrame escuta a roda do mouse na janela inteira. Na lista suspensa nativa (países),
# o Tk entrega o widget como texto, e o CustomTkinter quebra com
# "'str' object has no attribute 'master'". Aqui a roda nessas listas é ignorada pelo formulário
# (a própria lista continua rolando normalmente).
_verificar_original = getattr(ctk.CTkScrollableFrame, "_check_if_valid_scroll", None)


def _verificar_rolagem(self, widget) -> bool:
    if isinstance(widget, str):
        return False
    try:
        return _verificar_original(self, widget)
    except AttributeError:
        return False


if _verificar_original is not None:      # outras versões do CustomTkinter podem não ter o método
    ctk.CTkScrollableFrame._check_if_valid_scroll = _verificar_rolagem


def segmentado_das_abas(abas):
    """Botões das abas do CTkTabview (parte interna da biblioteca). None se outra versão mudar o nome:
    a tela continua funcionando, só sem o realce das abas."""
    return getattr(abas, "_segmented_button", None)


def realcar_abas(segmentado, cor_texto: str) -> None:
    """Texto branco na aba selecionada e escuro nas demais. Nunca derruba a tela."""
    if segmentado is None:
        return
    try:
        atual = segmentado.get()
        for valor, botao in getattr(segmentado, "_buttons_dict", {}).items():
            botao.configure(text_color="#FFFFFF" if valor == atual else cor_texto)
    except Exception:  # noqa: BLE001 - só aparência
        pass


def aumentar_abas(segmentado, fonte_abas, largura: int = 170) -> None:
    if segmentado is None:
        return
    try:
        segmentado.configure(font=fonte_abas, height=44, corner_radius=10)
        for botao in getattr(segmentado, "_buttons_dict", {}).values():
            botao.configure(width=largura)
    except Exception:  # noqa: BLE001 - só aparência
        pass


# ============================================================================ trabalho fora da tela

class EmSegundoPlano:
    """Roda um trabalho lento (pasta na rede) fora da thread da tela, para a janela não congelar.

    trabalho(perguntar) roda numa thread; perguntar(titulo, texto) -> bool mostra a pergunta NA TELA
    e espera a resposta. ao_terminar(resultado) / ao_falhar(erro) rodam na thread da tela.
    """

    INTERVALO_MS = 60
    em_andamento: set = set()     # trabalhos de rede vivos: o fechamento da janela espera por eles

    def __init__(self, widget, trabalho, ao_terminar, ao_falhar) -> None:
        import queue
        import threading
        if not callable(getattr(widget, "after", None)):     # antes de abrir a thread: nada roda pela metade
            raise TypeError(f"EmSegundoPlano precisa de um widget Tk (com .after), não {type(widget).__name__}")
        self._widget, self._ao_terminar, self._ao_falhar = widget, ao_terminar, ao_falhar
        self._fila: queue.Queue = queue.Queue()
        self._vazia = queue.Empty
        self._threading = threading
        self._thread = threading.Thread(target=self._rodar, args=(trabalho,), daemon=True, name="rede")
        self._thread.start()
        EmSegundoPlano.em_andamento.add(self)
        widget.after(self.INTERVALO_MS, self._conferir)

    def perguntar(self, titulo: str, texto: str) -> bool:
        resposta: dict = {}
        pronto = self._threading.Event()
        self._fila.put(("pergunta", (titulo, texto, resposta, pronto)))
        pronto.wait()
        return bool(resposta.get("sim"))

    def _rodar(self, trabalho) -> None:
        # O atalho da pasta (WScript.Shell) é COM: cada thread precisa iniciar o COM antes de usar.
        com = False
        try:
            import pythoncom  # type: ignore
            pythoncom.CoInitialize()
            com = True
        except ImportError:
            pass
        try:
            self._fila.put(("ok", trabalho(self.perguntar)))
        except Exception as erro:  # noqa: BLE001 - volta para a tela como mensagem
            self._fila.put(("erro", erro))
        finally:
            if com:
                import pythoncom  # type: ignore
                pythoncom.CoUninitialize()

    @property
    def ativo(self) -> bool:
        return self._thread.is_alive()

    def _conferir(self) -> None:
        from tkinter import messagebox
        while True:
            try:
                tipo, dado = self._fila.get_nowait()
            except self._vazia:
                break
            if tipo == "pergunta":
                titulo, texto, resposta, pronto = dado
                try:
                    resposta["sim"] = messagebox.askyesno(titulo, texto)
                finally:
                    pronto.set()
                continue
            EmSegundoPlano.em_andamento.discard(self)
            (self._ao_terminar if tipo == "ok" else self._ao_falhar)(dado)
            return
        self._widget.after(self.INTERVALO_MS, self._conferir)


# ============================================================================ uma janela só

class InstanciaUnica:
    """Trava de arquivo na pasta de dados: dois programas abertos no mesmo computador poderiam resolver,
    numa janela, a execução que a outra está gravando no SAP (e liberar um claim em duplicidade).
    A trava some sozinha quando o processo termina, mesmo se ele for morto."""

    def __init__(self, pasta) -> None:
        from pathlib import Path
        self.caminho = Path(pasta) / "programa_aberto.lock"
        self._arquivo = None

    def adquirir(self) -> bool:
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        arquivo = open(self.caminho, "a+b")  # noqa: SIM115 - fica aberto enquanto o programa roda
        try:
            if os.name == "nt":
                import msvcrt
                arquivo.seek(0)
                msvcrt.locking(arquivo.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(arquivo.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            arquivo.close()
            return False
        self._arquivo = arquivo
        return True

    def liberar(self) -> None:
        if self._arquivo is not None:
            self._arquivo.close()
            self._arquivo = None
