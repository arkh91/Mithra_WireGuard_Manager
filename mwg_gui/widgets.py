# File: mwg_gui/widgets.py
# Small custom widgets: card frame, live-throughput sparkline, usage bar, status dot, toast.
# Edit with: vi mwg_gui/widgets.py
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


def card(layout_cls=QVBoxLayout, margins=(18, 16, 18, 16), spacing=6) -> QFrame:
    """
    card(layout_cls=QVBoxLayout, margins, spacing) -> QFrame
    Usage: box = card(); box.layout().addWidget(label)
    A rounded panel with the card colours; its layout is already set.
    """
    f = QFrame()
    f.setProperty("card", True)
    lay = layout_cls(f)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return f


def label(text: str = "", role: str = "", wrap: bool = False) -> QLabel:
    """
    label(text, role="", wrap=False) -> QLabel
    Usage: label("Keys", "muted")    # roles: h1 h2 eyebrow muted faint num mono good bad gold brand
    """
    lb = QLabel(text)
    if role:
        lb.setProperty("role", role)
    lb.setWordWrap(wrap)
    return lb


class Sparkline(QWidget):
    """
    Sparkline(palette)
    Usage: sp = Sparkline(pal); sp.set_values([1, 2, 3])
    A filled gold line of the recent throughput.
    """

    def __init__(self, pal: dict):
        super().__init__()
        self.pal = pal
        self.values = []
        self.setMinimumHeight(60)

    def set_values(self, values) -> None:
        """
        set_values(values)
        Usage: sp.set_values(state["server"]["spark"])
        """
        values = [float(v) for v in values]
        if values != self.values:
            self.values = values
            self.update()

    def paintEvent(self, _e) -> None:
        """
        paintEvent(event)
        Usage: called by Qt
        """
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        gold = QColor(self.pal["gold"])
        p.setPen(QPen(QColor(self.pal["border2"]), 1))
        p.drawLine(0, h - 1, w, h - 1)
        vals = self.values
        if len(vals) < 2:
            return
        top = max(max(vals), 1.0)
        pts = [(i * (w - 2) / (len(vals) - 1) + 1, h - 4 - (v / top) * (h - 12)) for i, v in enumerate(vals)]
        path = QPainterPath()
        path.moveTo(*pts[0])
        for x, y in pts[1:]:
            path.lineTo(x, y)
        fill = QPainterPath(path)
        fill.lineTo(pts[-1][0], h)
        fill.lineTo(pts[0][0], h)
        fill.closeSubpath()
        g = QLinearGradient(0, 0, 0, h)
        c1, c2 = QColor(gold), QColor(gold)
        c1.setAlpha(90)
        c2.setAlpha(0)
        g.setColorAt(0, c1)
        g.setColorAt(1, c2)
        p.fillPath(fill, QBrush(g))
        p.setPen(QPen(gold, 2))
        p.drawPath(path)


class UsageBar(QWidget):
    """
    UsageBar(pal, down, up, scale, text, sub, limit=0)
    Usage: cell.setCellWidget(row, 1, UsageBar(pal, k["down"], k["up"], biggest_total, "155 MB", "↓ 91 MB"))
    Download in gold, upload in green, scaled to the busiest key. With a traffic limit the bar is scaled to the limit
    instead, and turns red once it is reached.
    """

    def __init__(self, pal: dict, down: int, up: int, scale: int, text: str, sub: str, limit: int = 0):
        super().__init__()
        self.limit = max(int(limit or 0), 0)
        self.pal, self.down, self.up = pal, down, up
        self.scale = self.limit or max(scale, 1)
        self.text, self.sub = text, sub
        self.setMinimumHeight(40)

    def paintEvent(self, _e) -> None:
        """
        paintEvent(event)
        Usage: called by Qt
        """
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width() - 8, self.height()
        f = p.font()
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(self.pal["text"]))
        # with a limit the text is "used / limit" and needs more room; the corner then shows the percentage used
        split = 0.78 if self.limit else 0.5
        p.drawText(QRectF(4, 2, w * split, 18), Qt.AlignLeft | Qt.AlignAbsolute | Qt.AlignVCenter, self.text)
        f.setBold(False)
        f.setPointSizeF(max(f.pointSizeF() - 1.5, 7))
        p.setFont(f)
        total = self.down + self.up
        sub = f"{min(total * 100 // self.limit, 999)}%" if self.limit else self.sub
        p.setPen(QColor(self.pal["red"] if self.limit and total >= self.limit else self.pal["text3"]))
        p.drawText(QRectF(w * (split - 0.1), 2, w * (1.1 - split), 18), Qt.AlignRight | Qt.AlignAbsolute | Qt.AlignVCenter, sub)
        y = h - 12
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self.pal["bar"]))
        p.drawRoundedRect(QRectF(4, y, w, 5), 2.5, 2.5)
        total = self.down + self.up
        full = w * min(total / self.scale, 1.0)
        if self.limit and total >= self.limit:
            p.setBrush(QColor(self.pal["red"]))
            p.drawRoundedRect(QRectF(4, y, w, 5), 2.5, 2.5)
        elif full > 0 and total > 0:
            dw = full * self.down / total
            p.setBrush(QColor(self.pal["gold"]))
            p.drawRoundedRect(QRectF(4, y, max(dw, 2), 5), 2.5, 2.5)
            p.setBrush(QColor(self.pal["green"]))
            p.drawRoundedRect(QRectF(4 + dw, y, max(full - dw, 1.5), 5), 2.5, 2.5)


class Dot(QWidget):
    """
    Dot(color)
    Usage: d = Dot("#3ecf6e"); d.set_color("#e5534b")
    A small round status light.
    """

    def __init__(self, color: str = "#888888", size: int = 10):
        super().__init__()
        self.color = color
        self.setFixedSize(size, size)

    def set_color(self, color: str) -> None:
        """
        set_color(color)
        Usage: dot.set_color(pal["green"])
        """
        if color != self.color:
            self.color = color
            self.update()

    def paintEvent(self, _e) -> None:
        """
        paintEvent(event)
        Usage: called by Qt
        """
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self.color))
        p.drawEllipse(1, 1, self.width() - 2, self.height() - 2)


class Toast(QLabel):
    """
    Toast(parent, pal)
    Usage: toast.show_text("Saved", ok=True)
    A short message that fades after a moment, shown at the bottom of the window.
    """

    def __init__(self, parent, pal: dict):
        super().__init__(parent)
        self.pal = pal
        self.setAlignment(Qt.AlignCenter)
        self.hide()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)

    def show_text(self, text: str, ok: bool = True) -> None:
        """
        show_text(text, ok=True)
        Usage: self.toast.show_text(tr("copied"))
        """
        col = self.pal["green"] if ok else self.pal["red"]
        self.setStyleSheet(f"background:{self.pal['card']};border:1px solid {col};border-radius:12px;padding:10px 18px;"
                           f"color:{self.pal['text']};")
        self.setText(text)
        self.adjustSize()
        par = self.parentWidget()
        self.move((par.width() - self.width()) // 2, par.height() - self.height() - 28)
        self.raise_()
        self.show()
        self.timer.start(2600)


class LogoLink(QWidget):
    """
    LogoLink(pixmap_path, height, on_click, text="", pal=None, horizontal=False)
    Usage: LogoLink(png, 78, lambda: ctl.open_link("about"), "MITHRA CORP")
    The whole logo (picture and name together) is one clickable link; the pointer turns into a hand.
    """

    def __init__(self, path: str, height: int, on_click, text: str = "", pal: dict = None):
        super().__init__()
        self.on_click = on_click
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("mithracorp.com")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.setAlignment(Qt.AlignHCenter)
        pic = QLabel()
        pm = QPixmap(path).scaledToHeight(height, Qt.SmoothTransformation)
        pic.setPixmap(pm)
        pic.setFixedSize(pm.size())
        lay.addWidget(pic, 0, Qt.AlignHCenter)
        if text:
            t = QLabel(text)
            t.setAlignment(Qt.AlignHCenter)
            t.setProperty("role", "gold")
            lay.addWidget(t)
        for w in self.findChildren(QLabel):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)

    def mousePressEvent(self, event) -> None:
        """
        mousePressEvent(event)
        Usage: called by Qt; a left click opens the link
        """
        if event.button() == Qt.LeftButton:
            self.on_click()
