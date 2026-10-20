# File: mwg_gui/dialogs.py
# The pop-up windows: ask for text, confirm, replace the access config, and the key window (QR code, config, copy, save).
# Edit with: vi mwg_gui/dialogs.py
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QIntValidator, QPainter, QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QVBoxLayout, QWidget)

from mwg_core import config
import datetime

from mwg_core.limits import expiry_state, parse_end_on, parse_traffic, server_now
from mwg_gui.strings import tr
from mwg_gui.theme import DARK, LIGHT
from mwg_gui.util import paint_titlebar, wrap_hard
from mwg_gui.widgets import label


def button(text: str, kind: str = "") -> QPushButton:
    """
    button(text, kind="") -> QPushButton
    Usage: ok = button("Save", "gold")      # kinds: gold danger (or plain)
    """
    b = QPushButton(text)
    if kind:
        b.setProperty("kind", kind)
    b.setCursor(Qt.PointingHandCursor)
    return b


class Base(QDialog):
    """
    Base(parent, lang, title, width=460)
    Usage: dlg = Base(win, "en", "Rename key"); dlg.body.addWidget(...); dlg.exec()
    A dialog with a heading, a body layout and a button row (dlg.buttons).
    """

    def __init__(self, parent, lang: str, title: str, width: int = 460):
        super().__init__(parent)
        self.lang = lang
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(width)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 20)
        root.setSpacing(12)
        root.addWidget(label(title, "h2"))
        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        root.addLayout(self.body)
        self.buttons = QHBoxLayout()
        self.buttons.addStretch(1)
        root.addSpacing(6)
        root.addLayout(self.buttons)

    def showEvent(self, event) -> None:
        """
        showEvent(event)
        Usage: called by Qt when the dialog appears; its title bar follows the window's theme
        """
        super().showEvent(event)
        pal = getattr(self.parent(), "pal", DARK)
        paint_titlebar(self, pal, pal is not LIGHT)

    def add_buttons(self, ok_text: str, kind: str = "gold") -> QPushButton:
        """
        add_buttons(ok_text, kind="gold") -> QPushButton
        Usage: ok = dlg.add_buttons(tr(lang, "save"))   # adds Cancel and the main button
        """
        cancel = button(tr(self.lang, "cancel"))
        cancel.clicked.connect(self.reject)
        ok = button(ok_text, kind)
        ok.clicked.connect(self.accept)
        self.buttons.addWidget(cancel)
        self.buttons.addWidget(ok)
        ok.setDefault(True)
        return ok


def ask_text(parent, lang: str, title: str, placeholder: str = "", initial: str = "", ok_text: str = "") -> str | None:
    """
    ask_text(parent, lang, title, placeholder="", initial="", ok_text="") -> str or None
    Usage: name = ask_text(win, "en", "Rename key", "", "Ali phone")      # None when cancelled
    """
    d = Base(parent, lang, title)
    edit = QLineEdit(initial)
    edit.setPlaceholderText(placeholder)
    edit.setMaxLength(64)
    d.body.addWidget(edit)
    d.add_buttons(ok_text or tr(lang, "save"))
    edit.returnPressed.connect(d.accept)
    edit.setFocus()
    edit.selectAll()
    return edit.text().strip() if d.exec() == QDialog.Accepted else None


def expiry_text(lang: str, k: dict) -> str:
    """
    expiry_text(lang, key) -> str
    Usage: label.setText(expiry_text("en", key))   # "Ends 2026-11-18 14:00 (29d left)." / "1 month from its first ..."
    The current time limit of a key, in words, for the Edit key dialog.
    """
    st = expiry_state(k, time.time())
    if not st:
        return tr(lang, "expNoneNow")
    if st[0] == "pending":
        return tr(lang, "pendingFor", duration_words(lang, st[1]))
    # an end the server reports on its own clock is shown that way (the clock the "End on" choice is counted on)
    when = (k["expiresAtServer"] + " " + tr(lang, "serverTimeTag")) if k.get("expiresAtServer") else \
        time.strftime("%Y-%m-%d %H:%M", time.localtime(st[1]))
    if st[0] == "expired":
        return tr(lang, "endedOn", when)
    return tr(lang, "endsOn", when, left_text(lang, st[1] - time.time()))


def local_time(iso) -> str:
    """
    local_time(iso) -> str
    Usage: local_time("2026-10-19T08:42:45.000Z")    # "2026-10-19 01:42" in this PC's time zone; "" when empty
    """
    if not iso:
        return ""
    try:
        import datetime
        return datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return str(iso)


def duration_words(lang: str, dur: str) -> str:
    """
    duration_words(lang, dur) -> str
    Usage: duration_words("en", "1m")    # "1 month"
    """
    try:
        return tr(lang, "durText", int(dur[:-1]), dur[-1])
    except (ValueError, KeyError, IndexError):
        return dur


def left_text(lang: str, secs: float) -> str:
    """
    left_text(lang, secs) -> str
    Usage: left_text("en", 90000)    # "2d left" (rounded up); under a day: "5h left"
    """
    if secs >= 86400:
        return tr(lang, "leftD", int(-(-secs // 86400)))
    return tr(lang, "leftH", max(1, int(-(-secs // 3600))))


def offset_text(minutes: int) -> str:
    """
    offset_text(minutes) -> str
    Usage: offset_text(-420)    # "-07:00";  offset_text(210) -> "+03:30"
    """
    a = abs(minutes)
    return f"{'-' if minutes < 0 else '+'}{a // 60:02d}:{a % 60:02d}"


def ask_key(parent, lang: str, title: str, name: str = "", traffic: str = "", ok_text: str = "",
            with_limit: bool = True, with_expiry: bool = False, key: dict | None = None,
            with_end_on: bool = False, server_offset: int | None = None, server_zone: str = "") -> tuple | None:
    """
    ask_key(parent, lang, title, name="", traffic="", ok_text="", with_limit=True, with_expiry=False, key=None,
            with_end_on=False, server_offset=None, server_zone="") -> (name, traffic, expiry) or None
    Usage: r = ask_key(win, "en", "Add a key", ok_text="Create", with_expiry=True)   # ("Ali", "20G", ("now", "30d"))
    Name, traffic limit and time limit of a key; None when cancelled. The limit is checked before the dialog closes
    ("" = unlimited). expiry: None = keep (editing), ("none",), ("on", "2026-12-31 18:00") = ends then on the SERVER's
    clock (needs with_end_on, API 2.3), ("now", "30d") or ("first", "1m").
    server_offset (minutes from UTC) / server_zone only feed the "server time now" line under the date fields.
    With key (editing) the dialog shows the current time limit and starts on "Keep as it is".
    Without with_limit / with_expiry (older server API) those fields are shown greyed out with a note to update the
    server, and are not returned ("" / None).
    """
    d = Base(parent, lang, title)
    d.body.addWidget(label(tr(lang, "keyNameLabel"), "muted"))
    edit = QLineEdit(name)
    edit.setPlaceholderText(tr(lang, "keyNamePh"))
    edit.setMaxLength(64)
    d.body.addWidget(edit)
    lim = None
    err = label("", "bad", wrap=True)
    if True:                                         # always shown; greyed out when the server cannot do it yet
        d.body.addWidget(label(tr(lang, "trafficLimit"), "muted"))
        lim = QLineEdit(traffic)
        lim.setPlaceholderText(tr(lang, "trafficPh"))
        lim.setMaxLength(24)
        lim.setLayoutDirection(Qt.LeftToRight)
        d.body.addWidget(lim)
        d.body.addWidget(label(tr(lang, "trafficHint"), "faint", wrap=True))
        if not with_limit:
            lim.setEnabled(False)
    mode = amount = unit = None
    if True:
        d.body.addWidget(label(tr(lang, "timeLimit"), "muted"))
        if key is not None:
            d.body.addWidget(label(expiry_text(lang, key), "faint", wrap=True))
        mode = QComboBox()
        for v, t in ((("keep", tr(lang, "expKeep")),) if key is not None else ()) + (
                ("none", tr(lang, "expNone")), ("on", tr(lang, "expOn")), ("now", tr(lang, "expNow")),
                ("first", tr(lang, "expFirst"))):
            mode.addItem(t, v)
        if not with_end_on:                          # an older server cannot do "End on": shown, but not selectable
            mode.model().item(mode.findData("on")).setEnabled(False)
        d.body.addWidget(mode)
        # "End on": a date and a time on the server's clock (plain text fields: they stay readable in both themes)
        on_w = QWidget()
        on_l = QVBoxLayout(on_w)
        on_l.setContentsMargins(0, 0, 0, 0)
        on_l.setSpacing(6)
        on_row = QHBoxLayout()
        on_row.setSpacing(10)
        c1, c2 = QVBoxLayout(), QVBoxLayout()
        c1.addWidget(label(tr(lang, "endDate"), "faint"))
        c2.addWidget(label(tr(lang, "endTime"), "faint"))
        end_date, end_time = QLineEdit(), QLineEdit()
        for e_, ph, w_ in ((end_date, "2026-12-31", 150), (end_time, "18:00", 90)):
            e_.setPlaceholderText(ph)
            e_.setFixedWidth(w_)
            e_.setLayoutDirection(Qt.LeftToRight)
        end_date.setMaxLength(10)
        end_time.setMaxLength(5)
        c1.addWidget(end_date)
        c2.addWidget(end_time)
        on_row.addLayout(c1)
        on_row.addLayout(c2)
        on_row.addStretch(1)
        on_l.addLayout(on_row)
        clock = None
        if server_offset is not None:
            now_s = server_now(server_offset)
            clock = now_s
            on_l.addWidget(label(tr(lang, "serverNow", now_s.strftime("%Y-%m-%d %H:%M"), offset_text(server_offset),
                                    server_zone), "faint", wrap=True))
            start = now_s + datetime.timedelta(days=30)
        else:
            on_l.addWidget(label(tr(lang, "serverClockUnknown"), "faint", wrap=True))
            start = datetime.datetime.now() + datetime.timedelta(days=30)
        end_date.setText(start.strftime("%Y-%m-%d"))
        end_time.setText("23:59")
        if key is not None and parse_end_on(key.get("expiresAtServer")):      # start from the key's own end
            cur = parse_end_on(key["expiresAtServer"])
            end_date.setText(cur[:10])
            end_time.setText(cur[11:])
        d.body.addWidget(on_w)
        row_w = QWidget()
        row = QHBoxLayout(row_w)
        row.setContentsMargins(0, 0, 0, 0)
        amount = QLineEdit("30")                         # a number, 1..9999
        amount.setValidator(QIntValidator(1, 9999, amount))
        amount.setMaxLength(4)
        amount.setFixedWidth(90)
        amount.setLayoutDirection(Qt.LeftToRight)
        unit = QComboBox()
        for v, t in (("h", tr(lang, "unitHours")), ("d", tr(lang, "unitDays")), ("w", tr(lang, "unitWeeks")),
                     ("m", tr(lang, "unitMonths")), ("y", tr(lang, "unitYears"))):
            unit.addItem(t, v)
        if key is not None and key.get("expiresAfter"):     # start from the key's own duration
            dur = key["expiresAfter"]
            if dur[-1:] == "m" and dur[:-1].isdigit() and int(dur[:-1]) % 12 == 0:   # "12m" is shown as 1 year
                dur = f"{int(dur[:-1]) // 12}y"
            if dur[:-1].isdigit() and unit.findData(dur[-1]) >= 0:
                amount.setText(str(int(dur[:-1])))
                unit.setCurrentIndex(unit.findData(dur[-1]))
        row.addWidget(amount)
        row.addWidget(unit, 1)
        d.body.addWidget(row_w)
        d.body.addWidget(label(tr(lang, "expHint"), "faint", wrap=True))

        def mode_changed():
            """
            mode_changed()
            Usage: the amount and unit only matter for the two "ends after" choices
            """
            row_w.setVisible(mode.currentData() in ("now", "first"))
            on_w.setVisible(mode.currentData() == "on")
            if d.isVisible():                        # resizing before the dialog is styled would clip its fields
                d.adjustSize()

        mode.currentIndexChanged.connect(lambda _i: mode_changed())
        mode_changed()
        if not with_expiry:
            mode.setEnabled(False)
            row_w.setVisible(False)
            on_w.setVisible(False)
    if not (with_limit and with_expiry and with_end_on):
        d.body.addWidget(label(tr(lang, "needsUpdate"), "gold", wrap=True))
    err.setVisible(False)
    d.body.addWidget(err)
    ok = d.add_buttons(ok_text or tr(lang, "save"))
    ok.clicked.disconnect()

    def done():
        """
        done()
        Usage: the main button / Enter; closes only with a valid limit
        """
        if with_limit and parse_traffic(lim.text()) is None:
            err.setText(tr(lang, "errBadTraffic"))
            err.setVisible(True)
            lim.setFocus()
            return
        if with_expiry and mode.currentData() == "on":
            when = parse_end_on(f"{end_date.text().strip()} {end_time.text().strip()}")
            if not when:
                err.setText(tr(lang, "errBadEndOn"))
                err.setVisible(True)
                end_date.setFocus()
                return
            if clock is not None and datetime.datetime.strptime(when, "%Y-%m-%d %H:%M") <= clock:
                err.setText(tr(lang, "errEndPast"))
                err.setVisible(True)
                end_date.setFocus()
                return
        if with_expiry and mode.currentData() in ("now", "first") and (
                not int(amount.text() or 0) or int(amount.text()) * (12 if unit.currentData() == "y" else 1) > 9999):
            err.setText(tr(lang, "errBadDuration"))
            err.setVisible(True)
            amount.setFocus()
            return
        d.accept()

    ok.clicked.connect(done)
    edit.returnPressed.connect(done)
    if lim is not None:
        lim.returnPressed.connect(done)
    edit.setFocus()
    edit.selectAll()
    if d.exec() != QDialog.Accepted:
        return None
    expiry = None
    if with_expiry and mode.currentData() == "on":
        expiry = ("on", parse_end_on(f"{end_date.text().strip()} {end_time.text().strip()}"))
    elif with_expiry and mode.currentData() != "keep":
        m = mode.currentData()
        n = int(amount.text() or 0)
        u = unit.currentData()
        # years go to the server as months (any API 2.2 server takes them)
        spec = (f"{n * 12}m" if u == "y" else f"{n}{u}") if n > 0 else ""
        expiry = (m, spec) if m in ("now", "first") else ("none",)
    return edit.text().strip(), (lim.text().strip() if with_limit else traffic), expiry


def confirm(parent, lang: str, title: str, body: str, ok_text: str, danger: bool = True) -> bool:
    """
    confirm(parent, lang, title, body, ok_text, danger=True) -> bool
    Usage: if confirm(win, "en", "Remove this key?", "It stops working.", "Remove"): ...
    """
    d = Base(parent, lang, title)
    d.body.addWidget(label(body, "muted", wrap=True))
    d.add_buttons(ok_text, "danger" if danger else "gold")
    return d.exec() == QDialog.Accepted


def ask_access(parent, lang: str, title: str, body: str, check) -> str | None:
    """
    ask_access(parent, lang, title, body, check) -> str or None
    Usage: text = ask_access(win, "en", "Replace the access config", "Paste ...", ctl.check_access)
    A paste box for an access config with a live check line; the main button stays off until it is understood.
    """
    d = Base(parent, lang, title, 560)
    d.body.addWidget(label(body, "muted", wrap=True))
    box = QPlainTextEdit()
    box.setFixedHeight(120)
    box.setPlaceholderText(tr(lang, "pastePh"))
    d.body.addWidget(box)
    msg = label("", "faint", wrap=True)
    d.body.addWidget(msg)
    ok = d.add_buttons(tr(lang, "save"))
    ok.setEnabled(False)

    def changed():
        """
        changed()
        Usage: connected to the paste box
        """
        t = box.toPlainText().strip()
        if not t:
            msg.setText("")
            ok.setEnabled(False)
            return
        r = check(t)
        ok.setEnabled(bool(r.get("ok")))
        if r.get("ok"):
            msg.setText("✓ " + tr(lang, "okOutline" if r["format"] == "outline" else "okToken") + " • " +
                        tr(lang, "okPinned" if r["pinned"] else "okCa"))
        else:
            msg.setText(tr(lang, r["error"]["code"]))

    box.textChanged.connect(changed)
    return box.toPlainText().strip() if d.exec() == QDialog.Accepted else None


def qr_pixmap(text: str, size: int = 230) -> QPixmap:
    """
    qr_pixmap(text, size=230) -> QPixmap
    Usage: label.setPixmap(qr_pixmap(key["config"]))
    A QR code drawn module by module with QPainter (no SVG renderer needed, so it also works in the installed app),
    on a white tile with a quiet zone so every phone camera can read it. If drawing fails, the error text is printed on the tile.
    """
    pm = QPixmap(size, size)
    pm.fill(QColor("white"))
    try:
        from mwg_core._vendor import segno
        rows = [list(r) for r in segno.make(text, error="l", micro=False).matrix]
    except Exception as e:  # noqa: BLE001 - say what went wrong on the tile instead of crashing the dialog
        p = QPainter(pm)
        p.setPen(QColor("#b00020"))
        p.drawText(pm.rect().adjusted(12, 12, -12, -12), Qt.TextWordWrap, "QR code failed: " + repr(e))
        p.end()
        return pm
    n = len(rows)
    quiet = 4
    cell = size / (n + 2 * quiet)
    p = QPainter(pm)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#000000"))
    for y, row in enumerate(rows):
        for x, v in enumerate(row):
            if v:
                # round the edges outwards so neighbouring modules never leave hairlines
                x0, y0 = int((x + quiet) * cell), int((y + quiet) * cell)
                x1, y1 = int((x + quiet + 1) * cell + 0.999), int((y + quiet + 1) * cell + 0.999)
                p.drawRect(x0, y0, x1 - x0, y1 - y0)
    p.end()
    return pm


class KeyDialog(Base):
    """
    KeyDialog(parent, lang, key, toast, legacy=False)
    Usage: KeyDialog(win, "en", detail["key"], win.toast_text, legacy=False).exec()   # legacy: the server is still on the old API
    One key: QR code for the WireGuard phone app, the facts, the config text, Copy and Save .conf.
    """

    def __init__(self, parent, lang: str, key: dict, toast, legacy: bool = False):
        super().__init__(parent, lang, key["name"] or tr(lang, "unnamed"), 640)
        self.key, self.toast = key, toast
        top = QHBoxLayout()
        top.setSpacing(18)
        left = QVBoxLayout()
        qr = QLabel()
        if key["config"]:
            qr.setPixmap(qr_pixmap(key["config"]))
            left.addWidget(qr)
            left.addWidget(label(tr(lang, "scanQr"), "faint", wrap=True))
        else:
            if legacy:
                left.addWidget(label(tr(lang, "noConfig"), "muted", wrap=True))
                cmd = QPlainTextEdit(config.UPDATE_API_COMMAND)
                cmd.setReadOnly(True)
                cmd.setFixedHeight(76)
                cmd.setStyleSheet("font-family:'Cascadia Mono','Consolas',monospace;font-size:11px;")
                left.addWidget(cmd)
                cpc = button(tr(lang, "copy"))
                cpc.clicked.connect(lambda: (QGuiApplication.clipboard().setText(config.UPDATE_API_COMMAND), self.toast(tr(lang, "copied"))))
                left.addWidget(cpc, 0, Qt.AlignLeft)
            else:
                left.addWidget(label(tr(lang, "noConfigNew"), "muted", wrap=True))
        left.addStretch(1)
        top.addLayout(left)
        facts = QVBoxLayout()
        facts.setSpacing(2)
        for k, v in ((tr(lang, "address"), key["address"]), (tr(lang, "publicKey"), key["publicKey"]),
                     (tr(lang, "allowedIPs"), key["allowedIPs"]), (tr(lang, "endpoint"), key["endpoint"]),
                     (tr(lang, "dns"), key["dns"]), (tr(lang, "created"), local_time(key["createdAt"])),
                     (tr(lang, "firstConnected"), local_time(key.get("firstConnectedAt"))),
                     (tr(lang, "lastSeenAt"), local_time(key.get("lastHandshake")))):
            if v:
                facts.addWidget(label(k, "faint"))
                lv = label(wrap_hard(str(v), 34), "mono", wrap=True)
                lv.setTextInteractionFlags(Qt.TextSelectableByMouse)
                facts.addWidget(lv)
        facts.addStretch(1)
        top.addLayout(facts, 1)
        self.body.addLayout(top)
        if key["config"]:
            self.box = QPlainTextEdit(key["config"])
            self.box.setReadOnly(True)
            self.box.setFixedHeight(150)
            self.box.setStyleSheet("font-family:'Cascadia Mono','Consolas',monospace;font-size:12px;")
            self.body.addWidget(self.box)
            cp = button(tr(lang, "copyConfig"))
            cp.clicked.connect(self.copy)
            sv = button(tr(lang, "saveConf"), "gold")
            sv.clicked.connect(self.save)
            self.buttons.insertWidget(0, cp)
            self.buttons.insertWidget(1, sv)
            share = QHBoxLayout()
            share.addWidget(label(tr(lang, "share") + ":", "faint"))
            for text, fn in ((tr(lang, "copyQr"), self.copy_qr), (tr(lang, "saveQr"), self.save_qr)):
                b = button(text)
                b.clicked.connect(fn)
                share.addWidget(b)
            share.addStretch(1)
            self.body.addLayout(share)
        close = button(tr(lang, "close"))
        close.clicked.connect(self.accept)
        self.buttons.addWidget(close)

    def copy(self) -> None:
        """
        copy()
        Usage: connected to the Copy config button
        """
        QGuiApplication.clipboard().setText(self.key["config"])
        self.toast(tr(self.lang, "copied"))

    def copy_qr(self) -> None:
        """
        copy_qr()
        Usage: Copy QR image button; paste the picture into a chat or an e-mail
        """
        QGuiApplication.clipboard().setPixmap(qr_pixmap(self.key["config"], 520))
        self.toast(tr(self.lang, "copied"))

    def save_qr(self) -> None:
        """
        save_qr()
        Usage: Save QR button; writes a PNG of the QR code
        """
        stem = self.key["fileName"].rsplit(".", 1)[0]
        path, _ = QFileDialog.getSaveFileName(self, tr(self.lang, "saveQr"), stem + ".png", "PNG (*.png)")
        if path:
            qr_pixmap(self.key["config"], 520).save(path, "PNG")
            self.toast(tr(self.lang, "saved"))

    def save(self) -> None:
        """
        save()
        Usage: connected to the Save .conf button
        """
        path, _ = QFileDialog.getSaveFileName(self, tr(self.lang, "saveConf"), self.key["fileName"], "WireGuard (*.conf)")
        if path:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(self.key["config"])
            self.toast(tr(self.lang, "saved"))
