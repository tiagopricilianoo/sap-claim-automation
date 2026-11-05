# Automação de Claims SAP — © 2026 Elder Tiago Priciliano Ruas. Todos os direitos reservados.
# Uso, cópia, modificação ou distribuição somente com autorização por escrito do autor. Ver LICENSE.
"""Ícones SVG de traço (24x24, desenho próprio), coloridos na hora conforme o tema."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_P = {
    "painel": '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/>'
              '<rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
    "claim": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>'
             '<path d="M12 11v6M9 14h6"/>',
    "cotacao": '<path d="M6 3h12v18l-3-2-3 2-3-2-3 2z"/><path d="M9 8h6M9 12h6M9 16h3"/>',
    "execucao": '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    "historico": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "pendencia": '<path d="M12 3 2 20h20z"/><path d="M12 10v4"/><path d="M12 17v.01"/>',
    "config": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1'
              'a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3'
              'l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1'
              'a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9'
              'a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8'
              'l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    "sol": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2'
           'M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "lua": '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
    "check": '<path d="M5 12.5 10 17.5 19 7"/>',
    "x": '<path d="M6 6l12 12M18 6 6 18"/>',
    "alerta": '<circle cx="12" cy="12" r="9"/><path d="M12 8v5"/><path d="M12 16.5v.01"/>',
    "ponto": '<circle cx="12" cy="12" r="4"/>',
    "anexo": '<path d="M20 11.5 12.2 19.3a5 5 0 0 1-7.1-7.1l8-8a3.3 3.3 0 0 1 4.7 4.7l-8 8a1.7 1.7 0 0 1-2.4-2.4l7.3-7.3"/>',
    "atualizar": '<path d="M20 11a8 8 0 0 0-14.6-4.5L4 8"/><path d="M4 3v5h5"/><path d="M4 13a8 8 0 0 0 14.6 4.5L20 16"/>'
                 '<path d="M20 21v-5h-5"/>',
    "busca": '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
    "pasta": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "email": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
    "mais": '<path d="M12 5v14M5 12h14"/>',
    "play": '<path d="M7 4v16l13-8z"/>',
    "parar": '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    "limpar": '<path d="M4 7h16"/><path d="M10 11v6M14 11v6"/><path d="M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12"/>'
              '<path d="M9 7V4h6v3"/>',
    "sap": '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    "seta": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 7.5v.01"/>',
    "upload": '<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
    "usuario": '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
}


def svg(nome: str, cor: str, espessura: float = 1.8) -> bytes:
    corpo = _P[nome]
    preenchido = nome in ("ponto", "play")
    fill = cor if preenchido else "none"
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="{fill}" stroke="{cor}" '
            f'stroke-width="{espessura}" stroke-linecap="round" stroke-linejoin="round">{corpo}</svg>').encode()


def pixmap(nome: str, cor: str, tamanho: int = 18, escala: float = 2.0) -> QPixmap:
    lado = int(tamanho * escala)
    imagem = QImage(lado, lado, QImage.Format_ARGB32_Premultiplied)
    imagem.fill(Qt.transparent)
    pintor = QPainter(imagem)
    QSvgRenderer(QByteArray(svg(nome, cor))).render(pintor, QRectF(0, 0, lado, lado))
    pintor.end()
    pm = QPixmap.fromImage(imagem)
    pm.setDevicePixelRatio(escala)
    return pm


def icone(nome: str, cor: str, tamanho: int = 18) -> QIcon:
    return QIcon(pixmap(nome, cor, tamanho))


def salvar_png(nome: str, cor: str, caminho, tamanho: int = 18) -> str:
    """Para o QSS (indicador da caixa de seleção): o QSS só aceita arquivo."""
    lado = tamanho * 2
    imagem = QImage(lado, lado, QImage.Format_ARGB32_Premultiplied)
    imagem.fill(Qt.transparent)
    pintor = QPainter(imagem)
    QSvgRenderer(QByteArray(svg(nome, cor, 2.6))).render(pintor, QRectF(3, 3, lado - 6, lado - 6))
    pintor.end()
    imagem.save(str(caminho))
    return str(caminho).replace("\\", "/")
