# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Design system: paletas (claro/escuro), tipografia e folha de estilo (QSS).

Cores da marca: azul institucional #0E7490 (mesmo do tema.ini) e azul escuro #003B70.
Nenhum componente define cor solta: tudo sai daqui, para o tema escuro funcionar inteiro.
"""

from __future__ import annotations

import sys

FONTE = "Segoe UI" if sys.platform == "win32" else "DejaVu Sans"

CLARO = {
    "nome": "claro",
    "azul": "#0E7490", "azul_escuro": "#003B70", "azul_hover": "#004C8A", "azul_suave": "#E6F0F8",
    "azul_texto": "#0E7490",
    "fundo": "#F4F6F9", "superficie": "#FFFFFF", "superficie_2": "#F9FAFB", "sidebar": "#FFFFFF",
    "texto": "#182230", "texto_2": "#667085", "texto_3": "#98A2B3",
    "borda": "#E4E7EC", "borda_forte": "#D0D5DD",
    "ok": "#12A66A", "ok_suave": "#E7F6EF", "ok_texto": "#0B7A4C",
    "atencao": "#E9A23B", "atencao_suave": "#FDF3E3", "atencao_texto": "#9A5B0B",
    "erro": "#D92D20", "erro_suave": "#FDECEA", "erro_texto": "#B42318",
    "neutro_suave": "#F2F4F7", "neutro_texto": "#475467",
    "sombra": "#101828",
}

ESCURO = {
    "nome": "escuro",
    "azul": "#3B8FD9", "azul_escuro": "#9CC7EE", "azul_hover": "#5BA3E3", "azul_suave": "#14273D",
    "azul_texto": "#7DB6EA",
    "fundo": "#0E1116", "superficie": "#161A21", "superficie_2": "#1C212A", "sidebar": "#12161C",
    "texto": "#E6E9EE", "texto_2": "#98A2B3", "texto_3": "#667085",
    "borda": "#262C36", "borda_forte": "#343B47",
    "ok": "#32C48D", "ok_suave": "#10291F", "ok_texto": "#5FD8A8",
    "atencao": "#F0B355", "atencao_suave": "#2E2411", "atencao_texto": "#F3C47A",
    "erro": "#F0645A", "erro_suave": "#311614", "erro_texto": "#F59A92",
    "neutro_suave": "#222833", "neutro_texto": "#B6BECB",
    "sombra": "#000000",
}

PALETAS = {"claro": CLARO, "escuro": ESCURO}


class Tema:
    """Paleta ativa (lida pelos componentes que se desenham sozinhos)."""
    atual: dict = CLARO

    @classmethod
    def cor(cls, nome: str) -> str:
        return cls.atual[nome]


# tom de estado (controlador.TOM_ESTADO) -> chaves da paleta
TONS = {
    "ok": ("ok_suave", "ok_texto", "ok"),
    "atencao": ("atencao_suave", "atencao_texto", "atencao"),
    "erro": ("erro_suave", "erro_texto", "erro"),
    "neutro": ("neutro_suave", "neutro_texto", "texto_3"),
    "info": ("azul_suave", "azul_texto", "azul"),
}


def qss(p: dict, check: str = "") -> str:
    return f"""
* {{ font-family: "{FONTE}"; font-size: 13px; color: {p['texto']}; }}
QMainWindow, #Raiz {{ background: {p['fundo']}; }}
QWidget#Pagina {{ background: {p['fundo']}; }}
QToolTip {{ background: {p['texto']}; color: {p['superficie']}; border: none; padding: 6px 8px; border-radius: 6px; }}

/* ---------- sidebar ---------- */
#Sidebar {{ background: {p['sidebar']}; border-right: 1px solid {p['borda']}; }}
#MarcaTitulo {{ font-size: 15px; font-weight: 600; color: {p['texto']}; }}
#MarcaSub {{ font-size: 11px; color: {p['texto_2']}; }}
#SecaoMenu {{ font-size: 11px; font-weight: 600; color: {p['texto_3']}; padding: 14px 14px 4px 14px; letter-spacing: 0.5px; }}
QPushButton#ItemMenu {{ text-align: left; padding: 9px 12px; border: none; border-radius: 8px;
    background: transparent; color: {p['texto_2']}; font-size: 13px; font-weight: 500; }}
QPushButton#ItemMenu:hover {{ background: {p['neutro_suave']}; color: {p['texto']}; }}
QPushButton#ItemMenu:checked {{ background: {p['azul_suave']}; color: {p['azul_texto']}; font-weight: 600; }}
#Contador {{ background: {p['erro']}; color: white; border-radius: 8px; font-size: 11px; font-weight: 600;
    padding: 0px 6px; min-width: 18px; max-height: 18px; }}

/* ---------- topo ---------- */
#Topo {{ background: {p['fundo']}; }}
#TituloPagina {{ font-size: 22px; font-weight: 600; color: {p['texto']}; }}
#SubtituloPagina {{ font-size: 13px; color: {p['texto_2']}; }}

/* ---------- cards ---------- */
QFrame#Card {{ background: {p['superficie']}; border: 1px solid {p['borda']}; border-radius: 12px; }}
QFrame#CardSuave {{ background: {p['superficie_2']}; border: 1px solid {p['borda']}; border-radius: 10px; }}
#CardTitulo {{ font-size: 15px; font-weight: 600; color: {p['texto']}; }}
#CardSub {{ font-size: 12px; color: {p['texto_2']}; }}
#Rotulo {{ font-size: 12px; font-weight: 600; color: {p['texto']}; }}
#Obrigatorio {{ color: {p['erro']}; font-weight: 600; }}
#Dica {{ font-size: 12px; color: {p['texto_2']}; }}
#DicaAzul {{ font-size: 12px; color: {p['azul_texto']}; }}
#Erro {{ font-size: 12px; color: {p['erro_texto']}; }}
#Valor {{ font-size: 28px; font-weight: 600; color: {p['texto']}; }}
#Mono {{ font-family: Consolas, "DejaVu Sans Mono", monospace; font-size: 12px; }}

/* ---------- badges e faixas ---------- */
QLabel#Badge {{ border-radius: 9px; padding: 3px 10px; font-size: 11px; font-weight: 600; min-height: 16px; }}
QLabel#Badge[tom="ok"] {{ border-radius: 9px; background: {p['ok_suave']}; color: {p['ok_texto']}; }}
QLabel#Badge[tom="atencao"] {{ border-radius: 9px; background: {p['atencao_suave']}; color: {p['atencao_texto']}; }}
QLabel#Badge[tom="erro"] {{ border-radius: 9px; background: {p['erro_suave']}; color: {p['erro_texto']}; }}
QLabel#Badge[tom="neutro"] {{ border-radius: 9px; background: {p['neutro_suave']}; color: {p['neutro_texto']}; }}
QLabel#Badge[tom="info"] {{ border-radius: 9px; background: {p['azul_suave']}; color: {p['azul_texto']}; }}
QFrame#Banner {{ border-radius: 10px; }}
QFrame#Banner[tom="ok"] {{ border-radius: 10px; background: {p['ok_suave']}; border: 1px solid {p['ok']}; }}
QFrame#Banner[tom="atencao"] {{ border-radius: 10px; background: {p['atencao_suave']}; border: 1px solid {p['atencao']}; }}
QFrame#Banner[tom="erro"] {{ border-radius: 10px; background: {p['erro_suave']}; border: 1px solid {p['erro']}; }}
QFrame#Banner[tom="info"] {{ border-radius: 10px; background: {p['azul_suave']}; border: 1px solid {p['azul']}; }}
QFrame#Banner[tom="neutro"] {{ border-radius: 10px; background: {p['neutro_suave']}; border: 1px solid {p['borda']}; }}
QLabel#BannerTitulo {{ font-weight: 600; font-size: 13px; background: transparent; }}
QLabel#BannerTexto {{ font-size: 12px; background: transparent; }}
QFrame#Banner[tom="ok"] QLabel {{ color: {p['ok_texto']}; }}
QFrame#Banner[tom="atencao"] QLabel {{ color: {p['atencao_texto']}; }}
QFrame#Banner[tom="erro"] QLabel {{ color: {p['erro_texto']}; }}
QFrame#Banner[tom="info"] QLabel {{ color: {p['azul_texto']}; }}
QFrame#Banner[tom="neutro"] QLabel {{ color: {p['neutro_texto']}; }}
QFrame#Destaque {{ background: {p['ok_suave']}; border: 1px solid {p['ok']}; border-radius: 12px; }}
QLabel#DestaqueNumero {{ font-size: 24px; font-weight: 600; color: {p['ok_texto']}; background: transparent; }}
QFrame#SoltarArquivo {{ background: {p['superficie_2']}; border: 1px dashed {p['borda_forte']}; border-radius: 10px; }}
QFrame#SoltarArquivo[ativo="true"] {{ background: {p['azul_suave']}; border: 1px dashed {p['azul']}; }}
QFrame#SoltarArquivo[erro="true"] {{ border: 1px dashed {p['erro']}; }}
QFrame#Divisor {{ background: {p['borda']}; max-height: 1px; min-height: 1px; border: none; }}
QLabel#ChipSap {{ border-radius: 12px; padding: 5px 12px; font-size: 12px; font-weight: 600; }}
QLabel#ChipSap[tom="ok"] {{ border-radius: 12px; background: {p['ok_suave']}; color: {p['ok_texto']}; }}
QLabel#ChipSap[tom="erro"] {{ border-radius: 12px; background: {p['erro_suave']}; color: {p['erro_texto']}; }}
QLabel#ChipSap[tom="neutro"] {{ border-radius: 12px; background: {p['neutro_suave']}; color: {p['neutro_texto']}; }}

/* ---------- campos ---------- */
QLineEdit, QPlainTextEdit, QComboBox {{ background: {p['superficie']}; border: 1px solid {p['borda_forte']};
    border-radius: 8px; padding: 8px 10px; selection-background-color: {p['azul']}; selection-color: white; }}
QLineEdit:hover, QPlainTextEdit:hover, QComboBox:hover {{ border-color: {p['texto_3']}; }}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border: 1px solid {p['azul']}; }}
QLineEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled {{ background: {p['superficie_2']};
    color: {p['texto_3']}; border-color: {p['borda']}; }}
QLineEdit[erro="true"], QPlainTextEdit[erro="true"] {{ border: 1px solid {p['erro']}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox QAbstractItemView {{ background: {p['superficie']}; border: 1px solid {p['borda']}; border-radius: 8px;
    selection-background-color: {p['azul_suave']}; selection-color: {p['texto']}; outline: none; padding: 4px; }}
QCheckBox {{ spacing: 8px; color: {p['texto']}; }}
QCheckBox:disabled {{ color: {p['texto_3']}; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid {p['borda_forte']};
    background: {p['superficie']}; }}
QCheckBox::indicator:hover {{ border-color: {p['azul']}; }}
QCheckBox::indicator:checked {{ background: {p['azul']}; border-color: {p['azul']}; image: url({check}); }}
QCheckBox::indicator:disabled {{ background: {p['superficie_2']}; border-color: {p['borda']}; }}

/* ---------- botões ---------- */
QPushButton {{ border-radius: 8px; padding: 9px 16px; font-weight: 600; font-size: 13px; }}
QPushButton[variante="primario"] {{ background: {p['azul']}; color: white; border: 1px solid {p['azul']}; }}
QPushButton[variante="primario"]:hover {{ background: {p['azul_hover']}; border-color: {p['azul_hover']}; }}
QPushButton[variante="primario"]:pressed {{ background: {p['azul_escuro']}; }}
QPushButton[variante="primario"]:disabled {{ background: {p['borda_forte']}; border-color: {p['borda_forte']};
    color: {p['superficie']}; }}
QPushButton[variante="secundario"] {{ background: {p['superficie']}; color: {p['texto']}; border: 1px solid {p['borda_forte']}; }}
QPushButton[variante="secundario"]:hover {{ background: {p['superficie_2']}; border-color: {p['texto_3']}; }}
QPushButton[variante="secundario"]:pressed {{ background: {p['neutro_suave']}; }}
QPushButton[variante="secundario"]:disabled {{ color: {p['texto_3']}; border-color: {p['borda']}; }}
QPushButton[variante="perigo"] {{ background: {p['superficie']}; color: {p['erro_texto']}; border: 1px solid {p['erro']}; }}
QPushButton[variante="perigo"]:hover {{ background: {p['erro_suave']}; }}
QPushButton[variante="perigo"]:disabled {{ color: {p['texto_3']}; border-color: {p['borda']}; }}
QPushButton[variante="sucesso"] {{ background: {p['ok']}; color: white; border: 1px solid {p['ok']}; }}
QPushButton[variante="sucesso"]:hover {{ background: {p['ok_texto']}; }}
QPushButton[variante="fantasma"] {{ background: transparent; color: {p['azul_texto']}; border: none; padding: 6px 10px; }}
QPushButton[variante="fantasma"]:hover {{ background: {p['azul_suave']}; }}
QPushButton[variante="grande"] {{ background: {p['azul']}; color: white; border: none; border-radius: 10px;
    padding: 14px 18px; font-size: 14px; text-align: left; }}
QPushButton[variante="grande"]:hover {{ background: {p['azul_hover']}; }}

/* segmentado */
#Segmentado {{ background: {p['neutro_suave']}; border-radius: 9px; }}
QPushButton#Segmento {{ background: transparent; border: 1px solid transparent; border-radius: 7px; padding: 7px 8px;
    color: {p['texto_2']}; font-weight: 500; }}
QPushButton#Segmento:hover {{ color: {p['texto']}; }}
QPushButton#Segmento:checked {{ background: {p['superficie']}; color: {p['texto']};
    border: 1px solid {p['borda']}; }}
QPushButton#Segmento:disabled {{ color: {p['texto_3']}; }}

/* ---------- tabelas ---------- */
QTableView {{ background: {p['superficie']}; border: none; gridline-color: transparent;
    selection-background-color: {p['azul_suave']}; selection-color: {p['texto']}; outline: none;
    alternate-background-color: {p['superficie_2']}; }}
QTableView::item {{ padding: 6px 8px; border-bottom: 1px solid {p['borda']}; }}
QHeaderView::section {{ background: {p['superficie']}; color: {p['texto_2']}; font-size: 12px; font-weight: 600;
    border: none; border-bottom: 1px solid {p['borda']}; padding: 10px 8px; }}
QTableCornerButton::section {{ background: {p['superficie']}; border: none; }}

/* ---------- barra de progresso ---------- */
QProgressBar {{ background: {p['neutro_suave']}; border: none; border-radius: 4px; max-height: 8px; min-height: 8px; }}
QProgressBar::chunk {{ background: {p['azul']}; border-radius: 4px; }}

/* ---------- rolagem ---------- */
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p['borda_forte']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {p['texto_3']}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p['borda_forte']}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------- diálogos ---------- */
QMessageBox, QInputDialog, QDialog {{ background: {p['superficie']}; }}
QMessageBox QLabel {{ font-size: 13px; }}
QMessageBox QPushButton, QInputDialog QPushButton {{ min-width: 90px; background: {p['superficie']};
    border: 1px solid {p['borda_forte']}; color: {p['texto']}; }}
QMessageBox QPushButton:default, QInputDialog QPushButton:default {{ background: {p['azul']}; color: white;
    border-color: {p['azul']}; }}
QMenu {{ background: {p['superficie']}; border: 1px solid {p['borda']}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 7px 16px; border-radius: 6px; }}
QMenu::item:selected {{ background: {p['azul_suave']}; }}
"""
