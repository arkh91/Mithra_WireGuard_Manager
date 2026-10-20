# File: mwg_gui/pages.py
# The screens of the main window: server (keys), add server, settings, logs, about.
# Each page gets the MainWindow (win) and implements update() which only touches what actually changed.
# Edit with: vi mwg_gui/pages.py
import time

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy,
                               QTableWidget, QVBoxLayout, QWidget)

from mwg_core import config
from mwg_core.limits import expiry_state
from mwg_gui import dialogs
from mwg_gui.dialogs import button, duration_words, left_text
from mwg_gui.strings import tr
from mwg_gui.theme import icon
from mwg_gui.util import fmt_bytes, fmt_rate, ip_num, run_async, wrap_hard
from mwg_gui.widgets import Dot, Sparkline, UsageBar, card, label

MAX_ROWS = 400


def set_text(widget, text: str) -> None:
    """
    set_text(widget, text)
    Usage: set_text(self.title, "Pakistan 01")     # only touches the label when the text really changed
    """
    if widget.text() != text:
        widget.setText(text)


def chips(options, current, on_change) -> tuple:
    """
    chips(options, current, on_change) -> (QWidget, QButtonGroup)
    Usage: row, group = chips([("all", "All"), ("online", "Online")], "all", fn)
    A row of round toggle buttons where exactly one is on; on_change(value) runs when the choice changes.
    """
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    grp = QButtonGroup(w)
    grp.setExclusive(True)
    for value, text in options:
        b = QPushButton(text)
        b.setProperty("kind", "chip")
        b.setCheckable(True)
        b.setCursor(Qt.PointingHandCursor)
        b.setChecked(value == current)
        b.clicked.connect(lambda _=False, v=value: on_change(v))
        grp.addButton(b)
        lay.addWidget(b)
    lay.addStretch(1)
    return w, grp


def scroller(inner: QWidget) -> QScrollArea:
    """
    scroller(inner) -> QScrollArea
    Usage: page_layout.addWidget(scroller(content))
    """
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.NoFrame)
    sa.setWidget(inner)
    if not inner.objectName():
        inner.setObjectName("page")
    return sa


def ago_text(lang: str, secs) -> str:
    """
    ago_text(lang, secs) -> str
    Usage: ago_text("en", 125)    # "2 min ago"; None -> "never"
    """
    if secs is None:
        return tr(lang, "never")
    secs = int(secs)
    if secs < 10:
        return tr(lang, "justNow")
    if secs < 60:
        return tr(lang, "agoS", secs)
    if secs < 3600:
        return tr(lang, "agoM", secs // 60)
    if secs < 86400:
        return tr(lang, "agoH", secs // 3600)
    return tr(lang, "agoD", secs // 86400)


def error_text(win, err: dict) -> str:
    """
    error_text(win, err) -> str
    Usage: banner.setText(error_text(win, {"code": "errCertMismatch", "detail": "expected ..", "got": "AB.."}))
    The readable message; a certificate mismatch also shows both fingerprints.
    """
    if not err:
        return ""
    code = err.get("code") or "errGeneric"
    text = tr(win.lang, code)
    if code == "errCertMismatch":
        exp = str(err.get("detail") or "").replace("expected ", "")
        text += f"\n\n{tr(win.lang, 'expected')}:\n{exp}\n{tr(win.lang, 'presented')}:\n{err.get('got') or '–'}"
    elif err.get("detail") and code in ("errHttp", "errUnreachable", "errTls", "errBadReply", "errGeneric", "errOldApi"):
        text += f"\n{err['detail']}"
    return text


# =====================================================================================================
# Server page
# =====================================================================================================

class ServerPage(QWidget):
    """
    ServerPage(win)
    Usage: page = ServerPage(win); page.update()
    The open server: summary tiles, search and filters, the key table, and the side panel with the connection,
    throughput, server facts and actions.
    """

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.pal, self.lang = win.pal, win.lang
        self.q, self.filter, self.sort = "", "all", "usage"
        self.rows = []                       # [(key dict, live label, seen label, dot)] of the built table
        self.built = None                    # signature of the built table
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(28, 22, 22, 18)
        cl.setSpacing(14)
        root.addWidget(center, 1)

        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.eyebrow = label(tr(self.lang, "wgServer").upper(), "eyebrow")
        self.name = label("", "h1")
        self.sub = label("", "muted")
        for w in (self.eyebrow, self.name, self.sub):
            titles.addWidget(w)
        head.addLayout(titles, 1)
        self.btn_refresh = button("")
        self.btn_refresh.setProperty("kind", "tool")
        self.btn_refresh.setIcon(icon("refresh", self.pal["text"]))
        self.btn_refresh.setToolTip(tr(self.lang, "refresh"))
        self.btn_refresh.clicked.connect(win.refresh_server)
        self.btn_add = button(tr(self.lang, "addKey"), "gold")
        self.btn_add.setIcon(icon("plus", self.pal["btntext"]))
        self.btn_add.clicked.connect(win.add_key)
        head.addWidget(self.btn_refresh, 0, Qt.AlignTop)
        head.addWidget(self.btn_add, 0, Qt.AlignTop)
        cl.addLayout(head)

        self.banner = QFrame()
        self.banner.setObjectName("banner")
        bl = QVBoxLayout(self.banner)
        self.banner_text = label("", "", wrap=True)
        self.banner_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bl.addWidget(self.banner_text)
        self.banner_copy = button(tr(self.lang, "copy"))
        self.banner_copy.clicked.connect(lambda: (QGuiApplication.clipboard().setText(config.UPDATE_API_COMMAND),
                                                  win.toast_text(tr(self.lang, "copied"))))
        bl.addWidget(self.banner_copy, 0, Qt.AlignLeft)
        cl.addWidget(self.banner)

        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self.tiles = {}
        for key, title in (("keys", "keys"), ("online", "onlineNow"), ("usage", "totalUsage"), ("live", "liveSpeed")):
            c = card(spacing=2)
            t = label(tr(self.lang, title), "muted")
            v = label("0", "num")
            s = label("", "faint")
            for w in (t, v, s):
                c.layout().addWidget(w)
            tiles.addWidget(c, 1)
            self.tiles[key] = (v, s)
        cl.addLayout(tiles)

        tools = QHBoxLayout()
        tools.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr(self.lang, "search"))
        self.search.addAction(icon("search", self.pal["text3"], 18), QLineEdit.LeadingPosition)
        self.search.setMinimumWidth(150)
        self.search.textChanged.connect(self.on_search)
        tools.addWidget(self.search, 1)
        f_row, _ = chips([("all", tr(self.lang, "all")), ("online", tr(self.lang, "online")), ("idle", tr(self.lang, "idle")),
                          ("paused", tr(self.lang, "filterPaused"))],
                         "all", self.on_filter)
        self.sort_box = QComboBox()
        for v, t in (("usage", tr(self.lang, "sortUsage")), ("seen", tr(self.lang, "sortSeen")),
                     ("name", tr(self.lang, "sortName")), ("ip", tr(self.lang, "sortIp"))):
            self.sort_box.addItem(t, v)
        self.sort_box.currentIndexChanged.connect(lambda _i: self.on_sort(self.sort_box.currentData()))
        tools.addWidget(f_row)
        tools.addWidget(self.sort_box)
        cl.addLayout(tools)

        # columns: key, usage, time limit, live, last seen, actions
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([tr(self.lang, "colKey").upper(), tr(self.lang, "colUsage").upper(),
                                              tr(self.lang, "timeLimit").upper(), tr(self.lang, "colLive").upper(),
                                              tr(self.lang, "sortSeen").upper(), ""])
        self.table.verticalHeader().setVisible(False)
        self.table.setLayoutDirection(Qt.LeftToRight)
        self.table.setShowGrid(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.Fixed)
        hh.setSectionResizeMode(2, QHeaderView.Fixed)
        hh.setSectionResizeMode(3, QHeaderView.Fixed)
        hh.setSectionResizeMode(4, QHeaderView.Fixed)
        hh.setSectionResizeMode(5, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 190)
        self.table.setColumnWidth(2, 150)
        self.table.setColumnWidth(3, 100)
        self.table.setColumnWidth(4, 98)
        self.table.setColumnWidth(5, 250)
        cl.addWidget(self.table, 1)
        self.empty = label("", "muted", wrap=True)
        self.empty.setAlignment(Qt.AlignCenter)
        cl.addWidget(self.empty)

        # ---- the side panel
        rail_in = QWidget()
        rl = QVBoxLayout(rail_in)
        rl.setContentsMargins(16, 22, 16, 16)
        rl.setSpacing(12)
        rail = scroller(rail_in)
        rail.setObjectName("rail")
        rail.setFixedWidth(296)
        rail.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        rail_in.setObjectName("rail")
        root.addWidget(rail)

        conn = card(QHBoxLayout, spacing=12)
        self.dot = Dot(self.pal["text3"], 14)
        conn.layout().addWidget(self.dot, 0, Qt.AlignTop)
        ct = QVBoxLayout()
        ct.setSpacing(2)
        self.c_title = label("", "h2", wrap=True)
        self.c_host = label("", "muted")
        self.c_badges = label("", "faint", wrap=True)
        for w in (self.c_title, self.c_host, self.c_badges):
            ct.addWidget(w)
        conn.layout().addLayout(ct, 1)
        rl.addWidget(conn)

        tp = card(spacing=4)
        tp.layout().addWidget(label(tr(self.lang, "liveSpeed"), "muted"))
        self.t_rate = label("0 B/s", "num")
        tp.layout().addWidget(self.t_rate)
        self.spark = Sparkline(self.pal)
        tp.layout().addWidget(self.spark)
        row = QHBoxLayout()
        self.t_down = label("0 B", "mono")
        self.t_up = label("0 B", "mono")
        row.addWidget(label("↓", "faint"))
        row.addWidget(self.t_down)
        row.addSpacing(10)
        row.addWidget(label("↑", "faint"))
        row.addWidget(self.t_up)
        tp.layout().addLayout(row)
        rl.addWidget(tp)

        sv = card(spacing=2)
        sv.layout().addWidget(label(tr(self.lang, "server"), "gold"))
        self.facts = {}
        for key, title in (("endpoint", "endpoint"), ("apiUrl", "apiUrl"), ("serverKey", "serverKey"), ("dns", "dns"),
                           ("route", "apiRoute"), ("cert", "certSha256")):
            sv.layout().addSpacing(6)
            sv.layout().addWidget(label(tr(self.lang, title) if title != "certSha256" else "certSha256", "faint"))
            v = label("", "mono", wrap=True)
            v.setTextInteractionFlags(Qt.TextSelectableByMouse)
            sv.layout().addWidget(v)
            self.facts[key] = v
        rl.addWidget(sv)

        ac = card(spacing=0, margins=(18, 12, 18, 6))
        ac.layout().addWidget(label(tr(self.lang, "actions"), "gold"))
        for key, name, ico, fn in (("export", "exportAll", "folder", win.export_all), ("copy", "copyAccess", "copy", win.copy_access),
                                   ("rename", "renameServer", "edit", win.rename_server),
                                   ("replace", "replaceAccess", "lock", win.replace_access),
                                   ("remove", "removeServer", "trash", win.remove_server)):
            b = button(tr(self.lang, name))
            b.setProperty("kind", "rail")
            b.setIcon(icon(ico, self.pal["red"] if key == "remove" else self.pal["gold"]))
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(fn)
            ac.layout().addWidget(b)
        rl.addWidget(ac)
        rl.addStretch(1)

    # ---- filters ---------------------------------------------------------------------------------

    def on_search(self, text: str) -> None:
        """
        on_search(text)
        Usage: connected to the search box
        """
        self.q = text.strip().lower()
        self.rebuild()

    def on_filter(self, value: str) -> None:
        """
        on_filter(value)
        Usage: connected to the All / Online / Idle chips
        """
        self.filter = value
        self.rebuild()

    def on_sort(self, value: str) -> None:
        """
        on_sort(value)
        Usage: connected to the sort chips
        """
        self.sort = value
        self.rebuild()

    # ---- drawing ---------------------------------------------------------------------------------

    def update_page(self) -> None:
        """
        update_page()
        Usage: page.update_page()      # on every tick; only changed labels are written
        """
        S, sv = self.win.S, self.win.S["server"]
        if not sv:
            return
        L = self.lang
        set_text(self.name, sv["name"])
        updated = tr(L, "justNow") if sv["ago"] is None or sv["ago"] < 10 else ago_text(L, sv["ago"])
        sub = tr(L, "serverSub", f"{sv['host']}:{sv['port']}", sv["count"])
        if sv["ago"] is not None:
            sub += " • " + tr(L, "updatedAgo", updated)
        set_text(self.sub, sub)
        busy = sv["status"] == "loading"
        self.btn_refresh.setEnabled(not busy)
        self.btn_add.setEnabled(not busy)

        err = sv["error"] if sv["status"] == "error" else None
        self.banner.setVisible(bool(err))
        self.banner_copy.setVisible(False)
        if err:
            set_text(self.banner_text, error_text(self.win, err))
        if sv.get("legacy"):
            self.banner.setVisible(True)
            set_text(self.banner_text, tr(L, "legacy") + "\n" + config.UPDATE_API_COMMAND)
            self.banner_copy.setVisible(True)
        elif not err and sv.get("apiBehind"):
            # an older server API: everything it has works; the banner says what the update adds and how
            self.banner.setVisible(True)
            set_text(self.banner_text, tr(L, "updateApi", sv.get("apiVersion") or "?", config.SERVER_API_LATEST,
                                          ", ".join(sv["apiBehind"])) + "\n" + config.UPDATE_API_COMMAND)
            self.banner_copy.setVisible(True)

        v, s = self.tiles["keys"]
        set_text(v, str(sv["count"]))
        set_text(s, f"{sv['withConfig']}/{sv['count']} {tr(L, 'config')}")
        v, s = self.tiles["online"]
        set_text(v, str(sv["online"]))
        set_text(s, "< 3 min")
        v, s = self.tiles["usage"]
        set_text(v, fmt_bytes(sv["total"]))
        set_text(s, f"↓ {fmt_bytes(sv['down'])} • ↑ {fmt_bytes(sv['up'])}")
        v, s = self.tiles["live"]
        set_text(v, fmt_rate(sv["rate"]))
        every = S["refresh"]
        set_text(s, tr(L, "autoRefresh") + ": " + (tr(L, "off") if not every else tr(L, "everySec", every)))

        ok = sv["status"] == "ok"
        self.dot.set_color(self.pal["green"] if ok else self.pal["gold"] if busy else self.pal["red"])
        set_text(self.c_title, tr(L, "connected") if ok else tr(L, "connecting") if busy or sv["status"] == "idle"
                 else tr(L, "errorTitle"))
        set_text(self.c_host, f"{sv['host']}:{sv['port']}")
        cert = (tr(L, "certVerified") if sv["verified"] else tr(L, "certPinned")) if sv["pinned"] else tr(L, "certCa")
        set_text(self.c_badges, f"🔒 {cert}   •   " + tr(L, "formatOutline" if sv["format"] == "outline" else "formatToken"))
        set_text(self.t_rate, fmt_rate(sv["rate"]))
        self.spark.set_values(sv["spark"])
        set_text(self.t_down, fmt_bytes(sv["down"]))
        set_text(self.t_up, fmt_bytes(sv["up"]))
        for key, val in (("endpoint", sv["endpoint"] or "–"), ("apiUrl", sv["apiUrlShown"]),
                         ("serverKey", sv["serverPublicKey"] or "–"), ("dns", sv["dns"] or "–"),
                         ("route", "GET " + (sv["route"] or "–")), ("cert", sv["certSha256"] or "–")):
            set_text(self.facts[key], wrap_hard(val))
        self.tick_ages()
        self.rebuild()

    def visible_keys(self) -> tuple:
        """
        visible_keys() -> (list, total)
        Usage: rows, n = self.visible_keys()      # filtered, sorted, capped at MAX_ROWS
        """
        lst = list(self.win.keys)
        now = time.time()
        for k in lst:
            k["age"] = None if k["hsAge"] is None else k["hsAge"] + (now - self.win.keys_t)
            k["on"] = k["age"] is not None and k["age"] < config.ONLINE_WINDOW
        if self.q:
            lst = [k for k in lst if self.q in k["name"].lower() or self.q in k["ip"] or self.q in k["publicKey"].lower()]
        if self.filter == "online":
            lst = [k for k in lst if k["on"]]
        elif self.filter == "idle":
            lst = [k for k in lst if not k["on"]]
        elif self.filter == "paused":
            lst = [k for k in lst if k.get("paused") or k.get("limitReached") or k.get("expired")]
        inf = float("inf")
        order = {
            "usage": lambda k: -k["total"],
            "seen": lambda k: inf if k["age"] is None else k["age"],
            "name": lambda k: (not k["name"], k["name"].lower(), ip_num(k["ip"])),
            "ip": lambda k: ip_num(k["ip"]),
        }
        lst.sort(key=order[self.sort])
        return lst[:MAX_ROWS], len(lst)

    def rebuild(self) -> None:
        """
        rebuild()
        Usage: page.rebuild()      # redraws the table only when the key list, filter, sort, search or language changed
        """
        sv = self.win.S["server"]
        feats = tuple(sv.get("features", []))
        sig = (sv["id"], self.win.keys_rev, self.q, self.filter, self.sort, self.win.keys_sid, feats)
        if sig == self.built:
            return
        self.built = sig
        L = self.lang
        rows, n = self.visible_keys()
        self.table.setUpdatesEnabled(False)
        self.table.clearContents()
        self.table.setRowCount(len(rows))
        self.rows = []
        scale = max((k["total"] for k in rows), default=1)
        for i, k in enumerate(rows):
            self.table.setRowHeight(i, 64)
            cell = QWidget()
            cl = QHBoxLayout(cell)
            cl.setContentsMargins(8, 4, 8, 4)
            cl.setSpacing(12)
            exp = expiry_state(k, time.time())
            blocked = ("paused" if k.get("paused") else "limit" if k.get("limitReached")
                       else "expired" if exp and exp[0] == "expired" else "")
            dot = Dot(self.pal["green"] if k["on"] and not blocked else self.pal["text3"], 12)
            cl.addWidget(dot)
            tv = QVBoxLayout()
            tv.setSpacing(0)
            top = QHBoxLayout()
            top.setSpacing(8)
            nm = label(k["name"] or tr(L, "unnamed"), "")
            nm.setTextFormat(Qt.PlainText)          # names come from the server: never render them as HTML
            nm.setStyleSheet("font-weight:700;" + ("" if k["name"] and not blocked else f"color:{self.pal['text3']};"))
            top.addWidget(nm)
            if blocked:
                col = self.pal["gold"] if blocked == "paused" else self.pal["red"]
                badge = label(tr(L, {"paused": "statusPaused", "limit": "statusLimit", "expired": "statusExpired"}[blocked]), "")
                badge.setStyleSheet(f"color:{col}; border:1px solid {col}; border-radius:8px; padding:0 7px;"
                                    "font-size:11px; font-weight:700;")
                top.addWidget(badge)
            top.addStretch(1)
            tv.addLayout(top)
            tv.addWidget(label(k["ip"], "mono"))
            cl.addLayout(tv, 1)
            self.table.setCellWidget(i, 0, cell)
            lim = k.get("limit") or 0
            used = fmt_bytes(k["total"]) + (" / " + fmt_bytes(lim) if lim else "")
            self.table.setCellWidget(i, 1, UsageBar(self.pal, k["down"], k["up"], scale, used,
                                                    "↓ " + fmt_bytes(k["down"]), lim))
            live = label("", "good")
            live.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            self.table.setCellWidget(i, 2, self.time_cell(k, exp))
            self.table.setCellWidget(i, 3, live)
            seen = label("", "faint")
            seen.setStyleSheet("font-size:13px;")
            self.table.setCellWidget(i, 4, seen)
            act = QWidget()
            al = QHBoxLayout(act)
            al.setContentsMargins(4, 0, 4, 0)
            al.setSpacing(6)
            al.addStretch(1)
            tools = [("qr" if k["hasConfig"] else "info", tr(L, "scanQr") if k["hasConfig"] else tr(L, "noConfigShortNew" if not sv.get("legacy") else "noConfigShort"),
                      self.win.show_key, self.pal["text"]),
                     ("edit", tr(L, "editKeyTitle"), self.win.rename_key,
                      self.pal["text"]),
                     ("trash", tr(L, "remove"), self.win.remove_key, self.pal["red"])]
            if "pause" in feats:
                tools.insert(1, ("play", tr(L, "resumeKey"), self.win.resume_key, self.pal["green"]) if k.get("paused")
                             else ("pause", tr(L, "pauseKey"), self.win.pause_key, self.pal["gold"]))
            if k["hasConfig"]:
                tools.insert(0, ("copy", tr(L, "copyKey"), self.win.copy_key, self.pal["gold"]))
            for ico, tip, fn, col in tools:
                b = button("")
                b.setProperty("kind", "tool")
                b.setIcon(icon(ico, col))
                b.setToolTip(tip)
                b.setCursor(Qt.PointingHandCursor)
                b.clicked.connect(lambda _=False, f=fn, ip=k["ip"]: f(ip))
                al.addWidget(b)
            self.table.setCellWidget(i, 5, act)
            self.rows.append((k, live, seen, dot))
        self.table.setUpdatesEnabled(True)
        self.tick_ages()
        loading = self.win.keys_sid != sv["id"]
        if loading or (not self.win.keys and sv["status"] != "error"):
            text = tr(L, "loadingKeys") if (loading or sv["status"] == "loading") else tr(L, "noKeys")
        elif not rows:
            text = tr(L, "noMatch")
        elif n > len(rows):
            text = tr(L, "showing", len(rows), n)
        else:
            text = ""
        self.empty.setText(text)
        self.empty.setVisible(bool(text))
        self.table.setVisible(bool(rows))

    def time_cell(self, k: dict, exp) -> QWidget:
        """
        time_cell(key, expiry_state) -> QWidget
        Usage: self.table.setCellWidget(row, 2, self.time_cell(k, expiry_state(k, time.time())))
        The Time limit column: "29d left" over the end date (gold in the last 3 days), red "Expired" over the date it
        ended, "1 month" over "from 1st use" while it waits for the first connection, or "–" without a time limit.
        """
        L = self.lang
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 0, 4, 0)
        v.setSpacing(0)
        if not exp:
            main, sub, col = "–", "", self.pal["text3"]
        elif exp[0] == "pending":
            main, sub, col = duration_words(L, exp[1]), tr(L, "fromFirstUse"), self.pal["text"]
        else:
            # the end on the server's clock when the server says it (that is the clock the end is counted on)
            day = k.get("expiresAtServer") or time.strftime("%Y-%m-%d %H:%M", time.localtime(exp[1]))
            if k.get("expiresAtServer"):
                w.setToolTip(tr(L, "serverTimeTag") + ": " + day + "\n" +
                             time.strftime("%Y-%m-%d %H:%M", time.localtime(exp[1])))
            if exp[0] == "expired":
                main, sub, col = tr(L, "statusExpired"), day, self.pal["red"]
            else:
                left = exp[1] - time.time()
                main, sub, col = left_text(L, left), day, self.pal["gold"] if left < 3 * 86400 else self.pal["text"]
        top = label(main, "")
        top.setStyleSheet(f"color:{col}; font-weight:700;")
        v.addStretch(1)
        v.addWidget(top)
        if sub:
            v.addWidget(label(sub, "faint"))
        v.addStretch(1)
        return w

    def tick_ages(self) -> None:
        """
        tick_ages()
        Usage: every tick; updates "last handshake", the live speed and the online light in place without a rebuild
        """
        now = time.time()
        for k, live, seen, dot in self.rows:
            age = None if k["hsAge"] is None else k["hsAge"] + (now - self.win.keys_t)
            on = age is not None and age < config.ONLINE_WINDOW
            dot.set_color(self.pal["green"] if on and not (k.get("paused") or k.get("limitReached") or k.get("expired"))
                          else self.pal["text3"])
            set_text(seen, ago_text(self.lang, age))
            if on and (k["rateDown"] or k["rateUp"]):
                set_text(live, f"↓ {fmt_rate(k['rateDown'])}\n↑ {fmt_rate(k['rateUp'])}")
            else:
                set_text(live, "–")


# =====================================================================================================
# Add server page
# =====================================================================================================

class AddPage(QWidget):
    """
    AddPage(win)
    Usage: page = AddPage(win)
    Paste the access config, see it understood, press Done: the app connects, checks the certificate, pulls the keys.
    """

    def __init__(self, win):
        super().__init__()
        self.win, self.lang, self.pal = win, win.lang, win.pal
        self.busy = False
        L = self.lang
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        inner = QWidget()
        outer.addWidget(scroller(inner))
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(40, 30, 40, 30)
        lay.setSpacing(14)
        lay.addWidget(label(tr(L, "addTitle"), "h1"))
        lay.addWidget(label(tr(L, "addSub"), "muted", wrap=True))

        c1 = card(spacing=8)
        c1.layout().addWidget(label(tr(L, "step1"), "gold"))
        c1.layout().addWidget(label(tr(L, "step1Body"), "muted", wrap=True))
        cmd = QPlainTextEdit(config.INSTALL_COMMAND)
        cmd.setReadOnly(True)
        cmd.setFixedHeight(64)
        cmd.setStyleSheet("font-family:'Cascadia Mono','Consolas',monospace;font-size:12px;")
        c1.layout().addWidget(cmd)
        cp = button(tr(L, "copy"))
        cp.setIcon(icon("copy", self.pal["text"]))
        cp.clicked.connect(lambda: (QGuiApplication.clipboard().setText(config.INSTALL_COMMAND), win.toast_text(tr(L, "copied"))))
        c1.layout().addWidget(cp, 0, Qt.AlignLeft)
        c1.layout().addWidget(label(tr(L, "step1Have"), "faint", wrap=True))
        lay.addWidget(c1)

        c2 = card(spacing=8)
        c2.layout().addWidget(label(tr(L, "step2"), "gold"))
        self.paste = QPlainTextEdit()
        self.paste.setPlaceholderText(tr(L, "pastePh"))
        self.paste.setFixedHeight(130)
        self.paste.setStyleSheet("font-family:'Cascadia Mono','Consolas',monospace;font-size:12px;")
        self.paste.textChanged.connect(self.check)
        c2.layout().addWidget(self.paste)
        self.msg = label("", "faint", wrap=True)
        c2.layout().addWidget(self.msg)
        c2.layout().addWidget(label(tr(L, "nameOpt"), "muted"))
        self.name = QLineEdit()
        self.name.setPlaceholderText(tr(L, "namePh"))
        self.name.setMaxLength(64)
        c2.layout().addWidget(self.name)
        self.err = QFrame()
        self.err.setObjectName("banner")
        QVBoxLayout(self.err).addWidget(label("", "", wrap=True))
        self.err_label = self.err.findChild(QLabel)
        self.err_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.err.hide()
        c2.layout().addWidget(self.err)
        self.done = button(tr(L, "done"), "gold")
        self.done.setEnabled(False)
        self.done.clicked.connect(self.submit)
        c2.layout().addWidget(self.done, 0, Qt.AlignLeft)
        lay.addWidget(c2)
        lay.addStretch(1)

    def check(self) -> None:
        """
        check()
        Usage: connected to the paste box; reads the config without contacting the server
        """
        t = self.paste.toPlainText().strip()
        self.err.hide()
        if not t:
            self.msg.setText("")
            self.done.setEnabled(False)
            return
        r = self.win.ctl.check_access(t)
        self.done.setEnabled(bool(r.get("ok")) and not self.busy)
        if r.get("ok"):
            self.msg.setText(f"✓ {r['host']}:{r['port']} • " + tr(self.lang, "okOutline" if r["format"] == "outline" else "okToken") +
                             " • " + tr(self.lang, "okPinned" if r["pinned"] else "okCa"))
            self.msg.setStyleSheet(f"color:{self.pal['green']};")
        else:
            self.msg.setText(tr(self.lang, r["error"]["code"]))
            self.msg.setStyleSheet(f"color:{self.pal['red']};")

    def submit(self) -> None:
        """
        submit()
        Usage: connected to Done
        """
        text, name = self.paste.toPlainText().strip(), self.name.text().strip()
        self.busy = True
        self.done.setEnabled(False)
        self.done.setText(tr(self.lang, "connectingBtn"))
        self.err.hide()
        run_async(lambda: self.win.ctl.add_server(text, name), self.finished)

    def finished(self, r: dict) -> None:
        """
        finished(result)
        Usage: callback of submit
        """
        self.busy = False
        self.done.setText(tr(self.lang, "done"))
        self.done.setEnabled(True)
        if r.get("ok"):
            self.paste.clear()
            self.name.clear()
            self.win.toast_text(tr(self.lang, "added", r.get("count", 0)))
            self.win.show_view("server")
            return
        self.err_label.setText(error_text(self.win, r.get("error") or {}))
        self.err.show()


# =====================================================================================================
# Settings, logs, about
# =====================================================================================================

class SettingsPage(QWidget):
    """
    SettingsPage(win)
    Usage: page = SettingsPage(win)
    Theme, language and auto refresh; theme and language rebuild the window.
    """

    def __init__(self, win):
        super().__init__()
        self.win, L = win, win.lang
        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 30, 40, 30)
        lay.setSpacing(14)
        lay.addWidget(label(tr(L, "settings"), "h1"))
        c = card(spacing=10)
        c.layout().addWidget(label(tr(L, "appearance"), "gold"))
        c.layout().addWidget(label(tr(L, "theme"), "muted"))
        row, _ = chips([("dark", tr(L, "dark")), ("light", tr(L, "light"))], win.S["theme"], win.set_theme)
        c.layout().addWidget(row)
        c.layout().addWidget(label(tr(L, "language"), "muted"))
        row, _ = chips([("en", "English"), ("fa", "فارسی")], win.S["lang"], win.set_language)
        c.layout().addWidget(row)
        c.layout().addWidget(label(tr(L, "autoRefresh"), "muted"))
        self.combo = QComboBox()
        for s in win.S["refreshChoices"]:
            self.combo.addItem(tr(L, "off") if not s else tr(L, "everySec", s), s)
        self.combo.setCurrentIndex(max(0, self.combo.findData(win.S["refresh"])))
        self.combo.currentIndexChanged.connect(lambda _i: win.ctl.set_refresh(self.combo.currentData()))
        self.combo.setMaximumWidth(220)
        c.layout().addWidget(self.combo)
        lay.addWidget(c)
        d = card()
        d.layout().addWidget(label(tr(L, "data"), "gold"))
        d.layout().addWidget(label(tr(L, "dataBody"), "muted", wrap=True))
        lay.addWidget(d)
        lay.addStretch(1)


class LogsPage(QWidget):
    """
    LogsPage(win)
    Usage: page = LogsPage(win); page.update_page()
    The app log with a level filter, Copy, Open folder and Clear.
    """

    def __init__(self, win):
        super().__init__()
        self.win, L = win, win.lang
        self.sig = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 30, 40, 24)
        lay.setSpacing(12)
        top = QHBoxLayout()
        top.addWidget(label(tr(L, "logs"), "h1"), 1)
        self.level = QComboBox()
        for v, t in (("", tr(L, "all")), ("WARN", "WARN +"), ("ERROR", "ERROR")):
            self.level.addItem(t, v)
        self.level.currentIndexChanged.connect(lambda _i: self.update_page(True))
        top.addWidget(self.level)
        for text, fn in ((tr(L, "copyLogs"), self.copy), (tr(L, "openFolder"), win.ctl.open_log_folder), (tr(L, "clear"), self.clear)):
            b = button(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            top.addWidget(b)
        lay.addLayout(top)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setStyleSheet("font-family:'Cascadia Mono','Consolas',monospace;font-size:12px;")
        lay.addWidget(self.view, 1)

    def update_page(self, force: bool = False) -> None:
        """
        update_page(force=False)
        Usage: page.update_page()    # rewrites the text only when the log changed
        """
        rows = self.win.ctl.log.rows(800, self.level.currentData() or "")
        sig = (len(rows), rows[0]["ts"] if rows else "", self.level.currentData())
        if sig == self.sig and not force:
            return
        self.sig = sig
        text = "\n".join(f"{r['ts']}  {r['lv']:<5} {r['cp']:<9} {r['tx']}" for r in rows) or tr(self.win.lang, "noLogs")
        self.view.setPlainText(text)

    def copy(self) -> None:
        """
        copy()
        Usage: Copy button
        """
        QGuiApplication.clipboard().setText(self.win.ctl.log.text())
        self.win.toast_text(tr(self.win.lang, "copied"))

    def clear(self) -> None:
        """
        clear()
        Usage: Clear button
        """
        self.win.ctl.log.clear()
        self.update_page(True)


class AboutPage(QWidget):
    """
    AboutPage(win)
    Usage: page = AboutPage(win)
    """

    def __init__(self, win):
        super().__init__()
        L = win.lang
        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 30, 40, 30)
        lay.setSpacing(14)
        lay.addWidget(label(tr(L, "about"), "h1"))
        c = card(spacing=8)
        logo = QLabel()
        logo.setPixmap(QPixmap(str(config.resource_dir() / "assets" / "mithracorp_logo.png")).scaledToHeight(
            88, Qt.SmoothTransformation))
        c.layout().addWidget(logo, 0, Qt.AlignLeft)
        c.layout().addWidget(label(config.APP_NAME, "h2"))
        c.layout().addWidget(label(f"{tr(L, 'version')} {win.S['version']}", "faint"))
        c.layout().addWidget(label(tr(L, "aboutBody"), "muted", wrap=True))
        for text, name in ((tr(L, "website"), "about"), (tr(L, "serverScripts"), "installer")):
            b = button(text)
            b.setProperty("kind", "link")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, n=name: win.ctl.open_link(n))
            c.layout().addWidget(b, 0, Qt.AlignLeft)
        lay.addWidget(c)
        lay.addStretch(1)
