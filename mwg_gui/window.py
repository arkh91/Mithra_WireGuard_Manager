# File: mwg_gui/window.py
# The main window of Mithra WireGuard Manager: a normal Windows window (native title bar) with the server list on the left,
# the open page in the middle and, on the server page, the side panel on the right. All data comes from the Controller.
# Edit with: vi mwg_gui/window.py
import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFileDialog, QFrame, QHBoxLayout, QMainWindow, QPushButton,
                               QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from mwg_core import config
from mwg_core.limits import limit_text
from mwg_gui import dialogs
from mwg_gui.pages import AboutPage, AddPage, LogsPage, ServerPage, SettingsPage, error_text
from mwg_gui.strings import tr
from mwg_gui.theme import DARK, LIGHT, icon, stylesheet
from mwg_gui.util import paint_titlebar, run_async
from mwg_gui.widgets import Dot, LogoLink, Toast, label

_windows = []          # keeps the live window referenced (a rebuild replaces it)


class MainWindow(QMainWindow):
    """
    MainWindow(controller, geometry=None)
    Usage: win = MainWindow(Controller()); win.show()
    """

    def __init__(self, ctl, geometry=None):
        super().__init__()
        self.ctl = ctl
        self.S = ctl.state()
        self.lang = self.S["lang"] or "en"
        self.pal = LIGHT if self.S["theme"] == "light" else DARK
        self.keys, self.keys_sid, self.keys_rev, self.keys_t = [], "", -2, time.time()
        self.view = "server" if self.S["server"] else "add"
        self.rebuilding = False
        self.srv_sig = None
        self.srv_buttons = []

        app = QApplication.instance()
        app.setStyleSheet(stylesheet(self.pal))
        app.setLayoutDirection(Qt.RightToLeft if self.lang == "fa" else Qt.LeftToRight)
        self.setWindowTitle(config.APP_NAME)
        self.setWindowIcon(QIcon(str(config.resource_dir() / "assets" / "mithracorp_logo.ico")))
        self.setMinimumSize(1240, 680)
        if geometry:
            self.restoreGeometry(geometry)
        else:
            self.resize(1320, 820)

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.build_sidebar())
        self.stack = QStackedWidget()
        self.pages = {"server": ServerPage(self), "add": AddPage(self), "settings": SettingsPage(self),
                      "logs": LogsPage(self), "about": AboutPage(self)}
        for name in ("server", "add", "settings", "logs", "about"):
            self.stack.addWidget(self.pages[name])
        lay.addWidget(self.stack, 1)
        self.toast = Toast(root, self.pal)

        self.show_view(self.view)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)
        self.tick()

    # ---- layout ----------------------------------------------------------------------------------

    def build_sidebar(self) -> QWidget:
        """
        build_sidebar() -> QWidget
        Usage: layout.addWidget(self.build_sidebar())
        Brand (a link to mithracorp.com), the scrolling server list with Add server, Settings / Logs / About / Exit and
        the footer logo (also a link). The footer never gets squeezed: only the server list scrolls.
        """
        L, p = self.lang, self.pal
        logo_path = str(config.resource_dir() / "assets" / "mithracorp_logo.png")
        open_site = lambda: self.ctl.open_link("about")
        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(256)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(14, 16, 14, 14)
        lay.setSpacing(6)

        brand = QHBoxLayout()
        top_logo = LogoLink(logo_path, 40, open_site)
        brand.addWidget(top_logo, 0, Qt.AlignVCenter)
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(label("MITHRA", "brand"))
        w = label("WIREGUARD MANAGER", "brand")
        w.setStyleSheet(f"color:{p['gold']};font-size:11px;letter-spacing:1px;")
        names.addWidget(w)
        brand.addLayout(names, 1)
        lay.addLayout(brand)
        lay.addSpacing(14)
        lay.addWidget(label(tr(L, "navServers").upper(), "faint"))

        holder = QWidget()
        holder.setObjectName("sidebar")
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(4)
        self.srv_box = QVBoxLayout()
        self.srv_box.setSpacing(4)
        hl.addLayout(self.srv_box)
        self.btn_add = QPushButton("  " + tr(L, "navAdd"))
        self.btn_add.setProperty("kind", "add")
        self.btn_add.setIcon(icon("plus", p["gold"]))
        self.btn_add.setCursor(Qt.PointingHandCursor)
        self.btn_add.clicked.connect(lambda: self.show_view("add"))
        hl.addWidget(self.btn_add)
        hl.addStretch(1)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        area.setWidget(holder)
        area.setObjectName("sidebar")
        lay.addWidget(area, 1)

        self.nav = {}
        for name, ico, text in (("settings", "settings", "navSettings"), ("logs", "logs", "navLogs"), ("about", "info", "navAbout")):
            b = QPushButton("  " + tr(L, text))
            b.setProperty("kind", "nav")
            b.setCheckable(True)
            b.setIcon(icon(ico, p["text2"]))
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, n=name: self.show_view(n))
            lay.addWidget(b)
            self.nav[name] = b
        ex = QPushButton("  " + tr(L, "navExit"))
        ex.setProperty("kind", "nav")
        ex.setIcon(icon("power", p["text2"]))
        ex.setCursor(Qt.PointingHandCursor)
        ex.clicked.connect(self.close)
        lay.addWidget(ex)
        lay.addSpacing(10)

        foot = LogoLink(logo_path, 84, open_site, "MITHRA CORP")
        lay.addWidget(foot, 0, Qt.AlignHCenter)
        m = label(tr(L, "motto"), "faint", wrap=True)
        m.setAlignment(Qt.AlignHCenter)
        lay.addWidget(m)
        return side

    # ---- navigation ------------------------------------------------------------------------------

    def show_view(self, name: str) -> None:
        """
        show_view(name)
        Usage: self.show_view("settings")      # server | add | settings | logs | about
        """
        if name == "server":
            self.tick()                      # a server may have just been added: read the fresh state first
            if not self.S["server"]:
                name = "add"
        self.view = name
        self.stack.setCurrentWidget(self.pages[name])
        self.sync_nav()
        if name == "logs":
            self.pages["logs"].update_page(True)
        if name == "server":
            self.pages["server"].update_page()

    def sync_nav(self) -> None:
        """
        sync_nav()
        Usage: after any view or server change; checks the right buttons
        """
        for n, b in self.nav.items():
            b.setChecked(self.view == n)
        sel = self.S["selected"]
        for sid, b in self.srv_buttons:
            b.setChecked(self.view == "server" and sid == sel)

    def rebuild_servers(self) -> None:
        """
        rebuild_servers()
        Usage: when the saved servers (or their counts / status) changed
        """
        sig = tuple((s["id"], s["name"], s["host"], s["port"], s["count"], s["status"]) for s in self.S["servers"])
        if sig == self.srv_sig:
            return
        self.srv_sig = sig
        while self.srv_box.count():
            it = self.srv_box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.srv_buttons = []
        for s in self.S["servers"]:
            b = QPushButton()
            b.setProperty("kind", "srv")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            row = QHBoxLayout(b)
            row.setContentsMargins(10, 6, 10, 6)
            ok = s["status"] == "ok"
            row.addWidget(Dot(self.pal["green"] if ok else self.pal["red"] if s["status"] == "error" else self.pal["gold"], 10))
            col = QVBoxLayout()
            col.setSpacing(0)
            n = label(s["name"], "")
            n.setStyleSheet("font-weight:700;background:transparent;")
            n.setAttribute(Qt.WA_TransparentForMouseEvents)
            h = label(f"{s['host']}:{s['port']}", "faint")
            h.setAttribute(Qt.WA_TransparentForMouseEvents)
            col.addWidget(n)
            col.addWidget(h)
            row.addLayout(col, 1)
            c = label(str(s["count"]), "faint")
            c.setAttribute(Qt.WA_TransparentForMouseEvents)
            row.addWidget(c)
            b.setFixedHeight(54)
            b.clicked.connect(lambda _=False, sid=s["id"]: self.pick_server(sid))
            self.srv_box.addWidget(b)
            self.srv_buttons.append((s["id"], b))
        self.sync_nav()

    def pick_server(self, sid: str) -> None:
        """
        pick_server(sid)
        Usage: clicking a server in the list
        """
        self.ctl.select(sid)
        self.S = self.ctl.state()
        self.keys_sid, self.keys_rev = "", -2
        self.show_view("server")
        self.tick()

    # ---- the heartbeat ---------------------------------------------------------------------------

    def tick(self) -> None:
        """
        tick()
        Usage: every second; reads the controller's state and updates only what changed
        """
        self.S = self.ctl.state()
        sv = self.S["server"]
        if sv and (self.keys_sid != sv["id"] or self.keys_rev != sv["rev"]):
            k = self.ctl.keys(sv["id"])
            self.keys, self.keys_sid, self.keys_rev, self.keys_t = k["keys"], sv["id"], k["rev"], time.time()
        if not sv and self.view == "server":
            self.show_view("add")
        self.rebuild_servers()
        self.sync_nav()
        if self.view == "server" and sv:
            self.pages["server"].update_page()
        elif self.view == "logs":
            self.pages["logs"].update_page()

    # ---- messages --------------------------------------------------------------------------------

    def toast_text(self, text: str, ok: bool = True) -> None:
        """
        toast_text(text, ok=True)
        Usage: self.toast_text(tr(self.lang, "copied"))
        """
        self.toast.show_text(text, ok)

    def toast_result(self, r: dict, success: str) -> bool:
        """
        toast_result(result, success) -> bool
        Usage: if self.toast_result(r, tr(L, "keyCreated", ip)): ...
        Shows the success text, or the readable error, and returns whether it worked.
        """
        if r.get("ok"):
            self.toast_text(success)
            return True
        self.toast_text(error_text(self, r.get("error") or {}).split("\n")[0], False)
        return False

    # ---- actions on keys -------------------------------------------------------------------------

    def sid(self) -> str:
        """
        sid() -> str
        Usage: sid = self.sid()
        """
        return self.S["server"]["id"] if self.S["server"] else ""

    def refresh_server(self) -> None:
        """
        refresh_server()
        Usage: the refresh button
        """
        if self.sid():
            self.ctl.refresh(self.sid())
            self.tick()

    def server_clock(self) -> dict:
        """
        server_clock() -> dict
        Usage: dialogs.ask_key(..., **self.server_clock())    # {"server_offset": -420, "server_zone": "America/Vancouver"}
        The selected server's time zone as its API reported it (API 2.3); empty on older servers.
        """
        srv = self.S.get("server") or {}
        if srv.get("serverOffset") is None:
            return {}
        return {"server_offset": srv["serverOffset"], "server_zone": srv.get("serverZone") or ""}

    def add_key(self) -> None:
        """
        add_key()
        Usage: the Add key button
        """
        sid = self.sid()
        feats = self.ctl.features(sid)
        r = dialogs.ask_key(self, self.lang, tr(self.lang, "newKeyTitle"), ok_text=tr(self.lang, "create"),
                            with_limit="limit" in feats, with_expiry="expiry" in feats,
                            with_end_on="expiryOn" in feats, **self.server_clock())
        if r is None:
            return
        name, traffic, expiry = r
        run_async(lambda: self.ctl.create_key(sid, name, traffic, expiry), self.key_created)

    def key_created(self, r: dict) -> None:
        """
        key_created(result)
        Usage: callback of add_key; shows the new key at once (QR code, copy, save) so it can be shared right away
        """
        ip = (r.get("result") or {}).get("ip", "")
        self.toast_result(r, tr(self.lang, "keyCreated", ip))
        self.tick()
        if r.get("ok") and ip:
            self.show_key(ip)

    def copy_key(self, ip: str) -> None:
        """
        copy_key(ip)
        Usage: the copy button of a key row; puts the whole WireGuard config on the clipboard
        """
        text = self.ctl.key_config(self.sid(), ip)
        if text:
            QGuiApplication.clipboard().setText(text)
            self.toast_text(tr(self.lang, "copied"))

    def key_name(self, ip: str) -> str:
        """
        key_name(ip) -> str
        Usage: name = self.key_name("10.66.0.5")
        """
        return next((k["name"] for k in self.keys if k["ip"] == ip), "")

    def show_key(self, ip: str) -> None:
        """
        show_key(ip)
        Usage: the QR / info button of a key row
        """
        d = self.ctl.key_detail(self.sid(), ip)
        if d.get("ok"):
            dialogs.KeyDialog(self, self.lang, d["key"], self.toast_text, legacy=bool((self.S.get("server") or {}).get("legacy"))).exec()

    def rename_key(self, ip: str) -> None:
        """
        rename_key(ip)
        Usage: the pencil button of a key row: name and (API 2.1) traffic limit
        """
        sid = self.sid()
        feats = self.ctl.features(sid)
        k = next((k for k in self.keys if k["ip"] == ip), {})
        r = dialogs.ask_key(self, self.lang, tr(self.lang, "editKeyTitle"), k.get("name", ""), limit_text(k.get("limit", 0)),
                            with_limit="limit" in feats, with_expiry="expiry" in feats, key=k,
                            with_end_on="expiryOn" in feats, **self.server_clock())
        if r is None:
            return
        name, traffic, expiry = r
        run_async(lambda: self.ctl.edit_key(sid, ip, name, traffic, expiry),
                  lambda res: (self.toast_result(res, tr(self.lang, "saved")), self.tick()))

    def pause_key(self, ip: str) -> None:
        """
        pause_key(ip)
        Usage: the pause button of a key row (asks first)
        """
        L = self.lang
        if not dialogs.confirm(self, L, tr(L, "pauseKeyTitle"), tr(L, "pauseKeyBody"), tr(L, "pauseKey"), danger=False):
            return
        sid = self.sid()
        run_async(lambda: self.ctl.set_paused(sid, ip, True), lambda r: (self.toast_result(r, tr(L, "keyPaused", ip)), self.tick()))

    def resume_key(self, ip: str) -> None:
        """
        resume_key(ip)
        Usage: the play button of a paused key's row
        """
        L = self.lang
        sid = self.sid()
        run_async(lambda: self.ctl.set_paused(sid, ip, False), lambda r: (self.toast_result(r, tr(L, "keyResumed", ip)), self.tick()))

    def remove_key(self, ip: str) -> None:
        """
        remove_key(ip)
        Usage: the bin button of a key row
        """
        L = self.lang
        if not dialogs.confirm(self, L, tr(L, "removeKeyTitle"), tr(L, "removeKeyBody", self.key_name(ip) or ip), tr(L, "remove")):
            return
        sid = self.sid()
        run_async(lambda: self.ctl.remove_key(sid, ip), lambda r: (self.toast_result(r, tr(L, "keyRemoved", ip)), self.tick()))

    # ---- actions on the server -------------------------------------------------------------------

    def export_all(self) -> None:
        """
        export_all()
        Usage: Actions > Export all configs
        """
        folder = QFileDialog.getExistingDirectory(self, tr(self.lang, "exportAll"))
        if folder:
            r = self.ctl.export_all(self.sid(), folder)
            self.toast_text(tr(self.lang, "exported", r.get("count", 0)), bool(r.get("ok")))

    def copy_access(self) -> None:
        """
        copy_access()
        Usage: Actions > Copy access config
        """
        QGuiApplication.clipboard().setText(self.ctl.access_json(self.sid()))
        self.toast_text(tr(self.lang, "copied"))

    def rename_server(self) -> None:
        """
        rename_server()
        Usage: Actions > Rename server
        """
        sv = self.S["server"]
        name = dialogs.ask_text(self, self.lang, tr(self.lang, "renameServer"), tr(self.lang, "namePh"), sv["name"])
        if name:
            self.ctl.rename_server(sv["id"], name)
            self.tick()

    def replace_access(self) -> None:
        """
        replace_access()
        Usage: Actions > Replace access config
        """
        L = self.lang
        text = dialogs.ask_access(self, L, tr(L, "replaceTitle"), tr(L, "replaceBody"), self.ctl.check_access)
        if not text:
            return
        sid = self.sid()
        run_async(lambda: self.ctl.replace_access(sid, text), lambda r: (self.toast_result(r, tr(L, "saved")), self.tick()))

    def remove_server(self) -> None:
        """
        remove_server()
        Usage: Actions > Remove server
        """
        L = self.lang
        if dialogs.confirm(self, L, tr(L, "removeServerTitle"), tr(L, "removeServerBody"), tr(L, "removeServer")):
            self.ctl.remove_server(self.sid())
            self.keys_sid, self.keys_rev = "", -2
            self.tick()

    # ---- settings --------------------------------------------------------------------------------

    def set_theme(self, theme: str) -> None:
        """
        set_theme(theme)
        Usage: Settings > Theme
        """
        self.ctl.set_theme(theme)
        self.rebuild("settings")

    def set_language(self, lang: str) -> None:
        """
        set_language(lang)
        Usage: Settings > Language
        """
        self.ctl.set_language(lang)
        self.rebuild("settings")

    def rebuild(self, view: str) -> None:
        """
        rebuild(view)
        Usage: self.rebuild("settings")      # new window with the new theme or language, same size, same page
        """
        new = MainWindow(self.ctl, self.saveGeometry())
        new.show_view(view)
        _windows.append(new)
        new.show()
        self.rebuilding = True
        self.close()

    def showEvent(self, event) -> None:
        """
        showEvent(event)
        Usage: called by Qt when the window appears; paints the title bar in the app colours (dark or light)
        """
        super().showEvent(event)
        paint_titlebar(self, self.pal, self.S["theme"] != "light")

    def closeEvent(self, event) -> None:
        """
        closeEvent(event)
        Usage: called by Qt on close / Exit; stops the controller unless the window is only being rebuilt
        """
        self.timer.stop()
        if not self.rebuilding:
            self.ctl.shutdown()
        event.accept()


def run(ctl) -> int:
    """
    run(ctl) -> int
    Usage: sys.exit(run(Controller()))
    Starts Qt, opens the main window and returns the exit code.
    """
    if getattr(sys, "frozen", False):
        os.environ.setdefault("QT_PLUGIN_PATH", str(Path(sys._MEIPASS) / "PySide6" / "plugins"))
    app = QApplication.instance() or QApplication([])
    app.setApplicationName(config.APP_NAME)
    win = MainWindow(ctl)
    _windows.append(win)
    win.show()
    return app.exec()
