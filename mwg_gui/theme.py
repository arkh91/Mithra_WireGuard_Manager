# File: mwg_gui/theme.py
# Colours (dark and light, same gold look as Mithra DNS), the Qt style sheet and the small line icons.
# Edit with: vi mwg_gui/theme.py
from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

DARK = dict(
    bg="#090c12", panel="#0e1219", card="#111620", card2="#151b27", border="#1c2330", border2="#262f3f",
    gold="#e8b73a", goldb="#f4cb62", golddim="#a5822c", goldsoft="rgba(232,183,58,0.12)", goldline="rgba(232,183,58,0.45)",
    text="#eef1f6", text2="#9099aa", text3="#5c667a", green="#3ecf6e", greensoft="rgba(62,207,110,0.14)",
    red="#e5534b", redsoft="rgba(229,83,75,0.14)", btntext="#1a1405", hover="#171e2b", bar="#1d2535",
)
LIGHT = dict(
    bg="#f3f0e8", panel="#fbf9f4", card="#ffffff", card2="#faf6ec", border="#e6e0d1", border2="#d8d0bb",
    gold="#b0800d", goldb="#c9941a", golddim="#8a6409", goldsoft="rgba(176,128,13,0.12)", goldline="rgba(176,128,13,0.50)",
    text="#1d222b", text2="#586172", text3="#8a92a1", green="#1f9d4f", greensoft="rgba(31,157,79,0.13)",
    red="#cf3b33", redsoft="rgba(207,59,51,0.11)", btntext="#ffffff", hover="#f4efe1", bar="#e9e3d2",
)

# 24x24 line icons (stroke only); {c} is replaced by the colour.
_ICONS = {
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "refresh": '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M19.1 4.9L17 7M7 17l-2.1 2.1"/>',
    "logs": '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4M9 12h6M9 16h6"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8v.01"/>',
    "power": '<path d="M12 3v9"/><path d="M6.3 6.3a8 8 0 1 0 11.4 0"/>',
    "qr": '<rect x="4" y="4" width="6" height="6"/><rect x="14" y="4" width="6" height="6"/><rect x="4" y="14" width="6" height="6"/><path d="M14 14h2v2h-2zM18 18h2v2h-2zM14 18v2M20 14v2"/>',
    "edit": '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
    "trash": '<path d="M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13M10 11v6M14 11v6"/>',
    "server": '<rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 7.5v.01M7 16.5v.01"/>',
    "key": '<circle cx="8" cy="15" r="4"/><path d="M11 12l8-8M16 7l3 3M14 9l2 2"/>',
    "search": '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "lock": '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    "download": '<path d="M12 4v11M7 11l5 5 5-5M5 20h14"/>',
    "upload": '<path d="M12 20V9M7 13l5-5 5 5M5 4h14"/>',
    "eye": '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "check": '<path d="M5 12l5 5 9-10"/>',
    "pause": '<path d="M9 5v14M15 5v14"/>',
    "play": '<path d="M8 5l11 7-11 7z"/>',
}


def icon(name: str, color: str, size: int = 20) -> QIcon:
    """
    icon(name, color, size=20) -> QIcon
    Usage: button.setIcon(icon("plus", pal["btntext"]))
    A crisp line icon drawn from the built-in SVG paths.
    """
    body = _ICONS.get(name, "")
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
           f'stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')
    scale = 2
    pm = QPixmap(size * scale, size * scale)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    QSvgRenderer(QByteArray(svg.encode())).render(p)
    p.end()
    pm.setDevicePixelRatio(scale)
    return QIcon(pm)


def stylesheet(p: dict) -> str:
    """
    stylesheet(palette) -> str
    Usage: app.setStyleSheet(stylesheet(DARK))
    The whole look of the app as one Qt style sheet; widgets pick their style by objectName or the "kind" property.
    """
    return f"""
* {{ font-family: 'Segoe UI Variable', 'Segoe UI', 'Inter', sans-serif; font-size: 14px; color: {p['text']}; }}
QMainWindow, QDialog, QWidget#root, QStackedWidget, QWidget#page {{ background: {p['bg']}; }}
QWidget#sidebar, QWidget#rail, QScrollArea#rail {{ background: {p['panel']}; }}
QFrame#sideline {{ background: {p['border']}; max-width: 1px; min-width: 1px; }}
QFrame[card="true"] {{ background: {p['card']}; border: 1px solid {p['border']}; border-radius: 14px; }}
QFrame[card="true"] QLabel {{ background: transparent; }}
QFrame#banner {{ background: {p['redsoft']}; border: 1px solid {p['red']}; border-radius: 10px; }}
QFrame#banner QLabel {{ color: {p['red']}; background: transparent; }}
QFrame#okbox {{ background: {p['greensoft']}; border: 1px solid {p['green']}; border-radius: 10px; }}
QLabel {{ background: transparent; }}
QLabel[role="h1"] {{ font-size: 28px; font-weight: 700; }}
QLabel[role="h2"] {{ font-size: 18px; font-weight: 700; }}
QLabel[role="eyebrow"] {{ color: {p['gold']}; font-size: 11px; font-weight: 700; letter-spacing: 2px; }}
QLabel[role="muted"] {{ color: {p['text2']}; }}
QLabel[role="faint"] {{ color: {p['text3']}; font-size: 12px; }}
QLabel[role="num"] {{ font-size: 26px; font-weight: 700; }}
QLabel[role="mono"] {{ font-family: 'Cascadia Mono', 'Consolas', monospace; font-size: 12px; }}
QLabel[role="good"] {{ color: {p['green']}; font-weight: 600; }}
QLabel[role="bad"] {{ color: {p['red']}; }}
QLabel[role="gold"] {{ color: {p['gold']}; font-weight: 700; }}
QLabel[role="brand"] {{ font-size: 15px; font-weight: 800; letter-spacing: 3px; }}
QPushButton {{ border: 1px solid {p['border2']}; border-radius: 10px; padding: 8px 16px; background: {p['card']}; }}
QPushButton:hover {{ background: {p['hover']}; border-color: {p['goldline']}; }}
QPushButton:disabled {{ color: {p['text3']}; }}
QPushButton[kind="gold"] {{ background: {p['gold']}; color: {p['btntext']}; border: 1px solid {p['gold']}; font-weight: 700; }}
QPushButton[kind="gold"]:hover {{ background: {p['goldb']}; }}
QPushButton[kind="gold"]:disabled {{ background: {p['golddim']}; color: {p['btntext']}; }}
QPushButton[kind="danger"] {{ color: {p['red']}; border-color: {p['red']}; background: transparent; }}
QPushButton[kind="danger"]:hover {{ background: {p['redsoft']}; }}
QPushButton[kind="nav"] {{ border: none; background: transparent; text-align: left; padding: 10px 14px; color: {p['text2']}; }}
QPushButton[kind="nav"]:hover {{ background: {p['hover']}; color: {p['text']}; }}
QPushButton[kind="nav"]:checked {{ background: {p['goldsoft']}; color: {p['gold']}; }}
QPushButton[kind="add"] {{ border: 1px dashed {p['goldline']}; background: transparent; color: {p['gold']}; text-align: left; padding: 10px 14px; }}
QPushButton[kind="add"]:hover {{ background: {p['goldsoft']}; }}
QPushButton[kind="chip"] {{ border-radius: 14px; padding: 5px 11px; color: {p['text2']}; background: transparent; }}
QPushButton[kind="chip"]:checked {{ background: {p['goldsoft']}; color: {p['gold']}; border-color: {p['goldline']}; font-weight: 600; }}
QPushButton[kind="srv"] {{ text-align: left; padding: 9px 12px; background: transparent; border: 1px solid transparent; border-radius: 12px; }}
QPushButton[kind="srv"]:hover {{ background: {p['hover']}; }}
QPushButton[kind="srv"]:checked {{ background: {p['goldsoft']}; border-color: {p['goldline']}; }}
QPushButton[kind="tool"] {{ padding: 6px; border-radius: 9px; min-width: 18px; }}
QPushButton[kind="rail"] {{ text-align: left; border: none; border-top: 1px solid {p['border']}; border-radius: 0; background: transparent; padding: 11px 4px; }}
QPushButton[kind="rail"]:hover {{ color: {p['gold']}; background: transparent; }}
QPushButton[kind="link"] {{ border: none; background: transparent; color: {p['gold']}; text-align: left; padding: 3px 0; }}
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox {{ background: {p['bg']}; border: 1px solid {p['border2']}; border-radius: 10px; padding: 8px 12px; selection-background-color: {p['gold']}; selection-color: {p['btntext']}; }}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border-color: {p['gold']}; }}
QComboBox:disabled {{ color: {p['text3']}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {p['card']}; border: 1px solid {p['border2']}; selection-background-color: {p['goldsoft']}; selection-color: {p['gold']}; }}
QTableWidget {{ background: {p['card']}; border: 1px solid {p['border']}; border-radius: 14px; gridline-color: transparent; outline: none; }}
QTableWidget::item {{ border-bottom: 1px solid {p['border']}; padding: 4px 8px; }}
QTableWidget::item:selected {{ background: {p['goldsoft']}; color: {p['text']}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: {p['card']}; color: {p['text3']}; border: none; border-bottom: 1px solid {p['border']}; padding: 10px 8px; font-size: 11px; font-weight: 700; letter-spacing: 1px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p['border2']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {p['golddim']}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p['border2']}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollArea {{ border: none; background: transparent; }}
QToolTip {{ background: {p['card']}; color: {p['text']}; border: 1px solid {p['border2']}; padding: 4px 8px; }}
QDialog {{ background: {p['card']}; }}
"""
