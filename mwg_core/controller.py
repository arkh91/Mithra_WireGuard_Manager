# File: core/controller.py
# The brain of Mithra WireGuard Manager: the saved servers, their keys, background refreshes and every action.
# Edit with: vi core/controller.py
"""
The UI polls state() about once a second. Key lists can be large (a /16 pool holds about 65,000 keys), so state()
carries only a revision number per server; the UI asks for the keys themselves (keys(sid)) when it changes.
All network work runs in worker threads; the window calls the slow ones through mwg_gui.util.run_async.
"""
import datetime
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser

from mwg_core import config
from mwg_core.access import AccessError, parse_access
from mwg_core.applog import AppLog
from mwg_core.limits import expiry_body, limit_text, parse_duration, parse_end_on, parse_traffic, parse_utc_offset
from mwg_core.store import KeyCache, ServerStore, Settings
from mwg_core.wgclient import ApiError, WgClient, key_from_config


def _iso_age(iso: str, now: float) -> float:
    """
    _iso_age(iso, now) -> float
    Usage: age = _iso_age("2026-10-18T06:00:00.000Z", time.time())   # seconds; inf when empty or bad
    """
    if not iso:
        return float("inf")
    try:
        t = datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
        return max(0.0, now - t)
    except ValueError:
        return float("inf")


def _ver(v) -> tuple:
    """
    _ver(v) -> tuple
    Usage: _ver("2.10") > _ver("2.9")    # True; anything unreadable counts as 0
    """
    try:
        return tuple(int(x) for x in str(v or "0").split("."))
    except ValueError:
        return (0,)


def api_behind(version) -> list:
    """
    api_behind(version) -> list
    Usage: api_behind("2.1")    # ["time limits"]: what the server misses compared with config.SERVER_API_LATEST
    [] when the server is up to date (or newer than this app).
    """
    have = _ver(version)
    if have >= _ver(config.SERVER_API_LATEST):
        return []
    return [what for v, what in config.SERVER_API_ADDS if _ver(v) > have]


def safe_filename(text: str) -> str:
    """
    safe_filename(text) -> str
    Usage: safe_filename("Ali / phone")   # "Ali_phone"
    A Windows-safe file name stem (WireGuard for Windows also wants tunnel names of at most 32 characters).
    """
    s = re.sub(r"[^A-Za-z0-9_.=+-]+", "_", text or "").strip("._")
    return (s or "wireguard")[:32]


class ServerState:
    """
    ServerState(sid, name, access_text)
    Usage: internal to Controller - one saved server and what the app last pulled from it.
    """

    def __init__(self, sid: str, name: str, access_text: str):
        """
        __init__(sid, name, access_text)
        Usage: ServerState("ab12", "Pakistan", '{"apiUrl": ...}')
        """
        self.sid = sid
        self.name = name
        self.access_text = access_text
        self.access = None
        self.bad_access = ""
        try:
            self.access = parse_access(access_text)
        except AccessError as exc:
            self.bad_access = str(exc)
        self.keys = []
        self.server = {}
        self.legacy = False
        self.route = ""
        self.status = "idle"        # idle | loading | ok | error
        self.error = None           # {"code", "detail", "got"}
        self.fetched = 0.0
        self.rev = 0
        self.verified = False
        self.presented_fp = ""
        self.prev = {}              # ip -> (total, up, down, t) from the previous pull, for live speed
        self.spark = []             # [bytes per second] over the last refreshes
        self.rate = 0
        self.lock = threading.Lock()

    def client(self) -> WgClient:
        """
        client() -> WgClient
        Usage: c = st.client()
        """
        if not self.access:
            raise ApiError(self.bad_access or "errNoJson")
        return WgClient(self.access)


class Controller:
    """
    Controller(store=None, settings=None, log=None)
    Usage: ctl = Controller(); ctl.start(); ctl.state(); ctl.add_server(text, ""); ctl.create_key(sid, "phone")
    """

    def __init__(self, store: ServerStore = None, settings: Settings = None, log: AppLog = None):
        """
        __init__(store=None, settings=None, log=None)
        Usage: Controller()    # tests pass their own store/settings/log
        """
        self.store = store or ServerStore()
        self.settings = settings or Settings()
        self.cache = KeyCache(self.store.path.with_name('keys.json'))
        self.log = log or AppLog()
        self.servers = {}
        self.order = []
        for item in self.store.all():
            self.servers[item["id"]] = ServerState(item["id"], item["name"], item["access"])
            self.order.append(item["id"])
        sel = self.settings.get("selected")
        self.selected = sel if sel in self.servers else (self.order[0] if self.order else "add")
        self.busy = ""              # the running key action, e.g. "create" or "remove:10.66.0.5"
        self._stop = threading.Event()
        self._thread = None

    # ---- life cycle --------------------------------------------------------------------------

    def start(self) -> None:
        """
        start()
        Usage: ctl.start()    # pulls every server once, then auto-refreshes the open one
        """
        self.log.info("app", f"{config.APP_NAME} {config.app_version()} started, {len(self.order)} server(s)")
        for sid in list(self.order):
            self.refresh(sid)
        self._thread = threading.Thread(target=self._loop, name="auto-refresh", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        """
        shutdown()
        Usage: ctl.shutdown()
        """
        self._stop.set()

    def _loop(self) -> None:
        """
        _loop()
        Usage: background thread started by start(); refreshes the open server every `refresh` seconds
        """
        while not self._stop.wait(1.0):
            every = int(self.settings.get("refresh") or 0)
            st = self.servers.get(self.selected)
            if every <= 0 or not st or st.status == "loading" or self.busy:
                continue
            if time.time() - st.fetched >= every:
                self.refresh(st.sid)

    # ---- state for the UI ----------------------------------------------------------------------

    def _server_summary(self, st: ServerState, now: float) -> dict:
        """
        _server_summary(st, now) -> dict
        Usage: rows = [self._server_summary(s, now) for s in ...]
        """
        a = st.access
        online = sum(1 for k in st.keys if _iso_age(k["lastHandshake"], now) < config.ONLINE_WINDOW)
        return {
            "id": st.sid, "name": st.name or (a.default_name() if a else "?"),
            "host": a.host if a else "", "port": a.port if a else 0,
            "format": ("outline" if a and a.secret_path and not a.api_token else "token") if a else "",
            "pinned": bool(a and a.cert_sha256), "status": st.status, "error": st.error,
            "count": len(st.keys), "online": online, "rev": st.rev,
        }

    def state(self) -> dict:
        """
        state() -> dict
        Usage: s = ctl.state()     # everything the screen needs except the key lists
        """
        now = time.time()
        sel = self.servers.get(self.selected)
        detail = None
        if sel:
            a = sel.access
            tot_up = sum(k["up"] for k in sel.keys)
            tot_down = sum(k["down"] for k in sel.keys)
            detail = dict(self._server_summary(sel, now))
            detail.update({
                "apiUrlShown": (f"https://{a.host}:{a.port}" + ("/••••••" if a.secret_path else "")) if a else "",
                "certSha256": a.cert_sha256 if a else "", "verified": sel.verified, "presented": sel.presented_fp,
                "endpoint": sel.server.get("endpoint") or next((k["endpoint"] for k in sel.keys if k["endpoint"]), ""),
                "serverPublicKey": sel.server.get("publicKey") or next((k["serverPublicKey"] for k in sel.keys if k["serverPublicKey"]), ""),
                "dns": sel.server.get("dns") or next((k["dns"] for k in sel.keys if k["dns"]), ""),
                "legacy": sel.legacy, "route": sel.route, "fetched": sel.fetched,
                "ago": int(now - sel.fetched) if sel.fetched else None,
                "up": tot_up, "down": tot_down, "total": tot_up + tot_down,
                "rate": sel.rate, "spark": list(sel.spark),
                "withConfig": sum(1 for k in sel.keys if k["config"]),
                "features": list(sel.server.get("features") or []),
                "apiVersion": str(sel.server.get("apiVersion") or ""),
                "serverOffset": parse_utc_offset(sel.server.get("utcOffset")),      # minutes, None on older servers
                "serverZone": str(sel.server.get("timeZone") or ""),
                "apiBehind": api_behind(sel.server.get("apiVersion")) if sel.status == "ok" and not sel.legacy else [],
                "paused": sum(1 for k in sel.keys if k.get("paused") or k.get("limitReached") or k.get("expired")),
            })
        return {
            "version": config.app_version(), "theme": self.settings.get("theme"), "lang": self.settings.get("lang"),
            "refresh": int(self.settings.get("refresh") or 0), "refreshChoices": list(config.REFRESH_CHOICES),
            "servers": [self._server_summary(self.servers[s], now) for s in self.order],
            "selected": self.selected, "server": detail, "busy": self.busy,
            "installCommand": config.INSTALL_COMMAND,
        }

    def keys(self, sid: str) -> dict:
        """
        keys(sid) -> dict
        Usage: k = ctl.keys(sid)    # {"rev", "keys": [...]} with "online", "rateDown", "rateUp" added
        """
        st = self.servers.get(sid)
        if not st:
            return {"rev": -1, "keys": []}
        now = time.time()
        with st.lock:
            out = []
            for k in st.keys:
                row = dict(k)
                row["hsAge"] = None if _iso_age(k["lastHandshake"], now) == float("inf") else int(_iso_age(k["lastHandshake"], now))
                row["online"] = row["hsAge"] is not None and row["hsAge"] < config.ONLINE_WINDOW
                row["hasConfig"] = bool(k["config"])
                row.pop("privateKey", None)
                row.pop("config", None)
                out.append(row)
            return {"rev": st.rev, "keys": out}

    # ---- servers ---------------------------------------------------------------------------------

    def check_access(self, text: str) -> dict:
        """
        check_access(text) -> dict
        Usage: r = ctl.check_access(pasted)   # {ok, error, host, format, pinned} without contacting the server
        """
        try:
            a = parse_access(text)
        except AccessError as exc:
            return {"ok": False, "error": {"code": str(exc)}}
        return {"ok": True, "host": a.host, "port": a.port, "pinned": bool(a.cert_sha256),
                "format": "outline" if a.secret_path and not a.api_token else "token"}

    def add_server(self, text: str, name: str = "") -> dict:
        """
        add_server(text, name="") -> dict
        Usage: r = ctl.add_server('{"apiUrl": ...}')   # {ok, sid, count} or {ok: False, error: {code, detail, got}}
        Connects first (certificate check + pulling the keys) and saves the server only when that works,
        like Outline Manager. Adding a server that is already saved just opens it.
        """
        try:
            a = parse_access(text)
        except AccessError as exc:
            return {"ok": False, "error": {"code": str(exc)}}
        for st in self.servers.values():
            if st.access and st.access.to_json() == a.to_json():
                self.select(st.sid)
                return {"ok": True, "sid": st.sid, "count": len(st.keys), "existing": True}
        client = WgClient(a)
        self.log.info("server", f"connecting to {a.host}:{a.port} ({'pinned certificate' if a.cert_sha256 else 'CA certificate'})")
        try:
            data = client.list_keys()
        except ApiError as exc:
            self.log.error("server", f"{a.host}:{a.port} {exc.code} {exc.detail}")
            return {"ok": False, "error": {"code": exc.code, "detail": exc.detail, "got": exc.got}}
        sid = self.store.add(name.strip()[:64] or a.default_name(), a.to_json())
        st = ServerState(sid, name.strip()[:64] or a.default_name(), a.to_json())
        self._apply(st, data, client)
        self.servers[sid] = st
        self.order.append(sid)
        self.select(sid)
        self.log.info("server", f"added {self._where(st)}: {len(st.keys)} key(s) via {data['route']}")
        return {"ok": True, "sid": sid, "count": len(st.keys)}

    def replace_access(self, sid: str, text: str) -> dict:
        """
        replace_access(sid, text) -> dict
        Usage: ctl.replace_access(sid, new_text)   # after a reinstall made a new certificate or token
        """
        st = self.servers.get(sid)
        if not st:
            return {"ok": False, "error": {"code": "errGeneric"}}
        try:
            a = parse_access(text)
        except AccessError as exc:
            return {"ok": False, "error": {"code": str(exc)}}
        client = WgClient(a)
        try:
            data = client.list_keys()
        except ApiError as exc:
            return {"ok": False, "error": {"code": exc.code, "detail": exc.detail, "got": exc.got}}
        self.store.update_access(sid, a.to_json())
        st.access, st.access_text, st.bad_access = a, a.to_json(), ""
        self._apply(st, data, client)
        self.log.info("server", f"access config of {self._where(st)} replaced")
        return {"ok": True}

    def remove_server(self, sid: str) -> dict:
        """
        remove_server(sid) -> dict
        Usage: ctl.remove_server(sid)    # only forgets it here; the server and its keys are untouched
        """
        if sid in self.servers:
            where = self._where(sid)
            self.store.remove(sid)
            self.cache.forget(sid)
            del self.servers[sid]
            self.order.remove(sid)
            self.select(self.order[0] if self.order else "add")
            self.log.info("server", f"{where} removed from the app")
        return {"ok": True}

    def rename_server(self, sid: str, name: str) -> dict:
        """
        rename_server(sid, name) -> dict
        Usage: ctl.rename_server(sid, "Karachi")
        """
        st = self.servers.get(sid)
        name = (name or "").strip()[:64]
        if st and name:
            st.name = name
            self.store.rename(sid, name)
        return {"ok": bool(st and name)}

    def select(self, sid: str) -> dict:
        """
        select(sid) -> dict
        Usage: ctl.select(sid)   or   ctl.select("add")    # the Add server screen
        """
        if sid == "add" or sid in self.servers:
            self.selected = sid
            if sid != "add":
                self.settings.set("selected", sid)
                st = self.servers[sid]
                if st.status != "loading" and time.time() - st.fetched > 10:
                    self.refresh(sid)
        return {"ok": True}

    def access_json(self, sid: str) -> str:
        """
        access_json(sid) -> str
        Usage: text = ctl.access_json(sid)    # the access config, for "Copy access config"
        """
        st = self.servers.get(sid)
        return st.access.to_json() if st and st.access else ""

    # ---- pulling keys ------------------------------------------------------------------------

    def _where(self, sid) -> str:
        """
        _where(sid_or_state) -> str
        Usage: self.log.info("key", f"created {ip} on {self._where(sid)}")     # "Pakistan 01 (pak.example.com:2053)"
        """
        st = sid if isinstance(sid, ServerState) else self.servers.get(sid)
        if not st:
            return "?"
        a = st.access
        return f"{st.name} ({a.host}:{a.port})" if a else st.name

    def _prune_cache(self, st: ServerState, keys: list) -> None:
        """
        _prune_cache(st, keys)
        Usage: self._prune_cache(st, data["keys"])
        Forgets the remembered configs of keys that are gone from the server (removed here, by another manager, by the
        API or by hand), so a new key that later gets the same address never shows an old config.
        """
        cached = self.cache.get(st.sid)
        live = {k["ip"] for k in keys}
        # a key created a moment ago may not be listed yet by an old server: keep entries younger than 2 minutes
        for ip in [ip for ip, v in cached.items() if ip not in live and time.time() - v.get("t", 0) > 120]:
            self.cache.forget(st.sid, ip)
            self.log.info("key", f"{ip} is no longer on {self._where(st)}: its remembered config was deleted")

    def _fill_from_cache(self, st: ServerState, keys: list) -> None:
        """
        _fill_from_cache(st, keys)
        Usage: self._fill_from_cache(st, data["keys"])
        Older servers never repeat a key's config; the ones this app created are put back from its encrypted cache.
        """
        cached = self.cache.get(st.sid)
        if not cached:
            return
        for k in keys:
            c = cached.get(k["ip"])
            if not c or k.get("config"):
                continue
            kk = key_from_config(c["config"], c["name"])
            for f in ("config", "privateKey", "name", "address", "dns", "endpoint", "serverPublicKey", "allowedIPs", "keepalive"):
                if not k.get(f) and kk.get(f):
                    k[f] = kk[f]

    def _apply(self, st: ServerState, data: dict, client: WgClient) -> None:
        """
        _apply(st, data, client)
        Usage: self._apply(st, client.list_keys(), client)
        Stores a fresh key list and works out live speeds from the previous one.
        """
        now = data.get("fetched", time.time())
        self._prune_cache(st, data["keys"])
        self._fill_from_cache(st, data["keys"])
        with st.lock:
            rate_sum = 0.0
            new_prev = {}
            for k in data["keys"]:
                p = st.prev.get(k["ip"])
                k["rateDown"] = k["rateUp"] = 0
                if p and now > p[3]:
                    dt = now - p[3]
                    dd, du = k["down"] - p[2], k["up"] - p[1]
                    if dd >= 0 and du >= 0:          # counters reset when wg0 restarts
                        k["rateDown"], k["rateUp"] = int(dd / dt), int(du / dt)
                        rate_sum += (dd + du) / dt
                new_prev[k["ip"]] = (k["total"], k["up"], k["down"], now)
            had_prev = bool(st.prev)
            st.prev = new_prev
            st.keys = data["keys"]
            st.server = data.get("server") or {}
            st.legacy = data.get("legacy", False)
            st.route = data.get("route", "")
            st.fetched = now
            st.status = "ok"
            st.error = None
            st.verified = client.verified
            st.presented_fp = client.presented_fp
            if had_prev:
                st.rate = int(rate_sum)
                st.spark = (st.spark + [st.rate])[-config.SPARK_POINTS:]
            st.rev += 1

    def refresh(self, sid: str, wait: bool = False) -> dict:
        """
        refresh(sid, wait=False) -> dict
        Usage: ctl.refresh(sid)   # in the background;  ctl.refresh(sid, wait=True) to block (tests)
        """
        st = self.servers.get(sid)
        if not st:
            return {"ok": False}
        if st.status == "loading" and not wait:
            return {"ok": True}
        st.status = "loading"

        def work():
            """
            work()
            Usage: threading.Thread(target=work).start()
            """
            client = None
            try:
                client = st.client()
                data = client.list_keys()
                self._apply(st, data, client)
            except ApiError as exc:
                st.status = "error"
                st.error = {"code": exc.code, "detail": exc.detail, "got": exc.got}
                if client:
                    st.presented_fp = client.presented_fp
                st.fetched = time.time()
                st.rev += 1
                self.log.error("api", f"{self._where(st)}: {exc.code} {exc.detail}")
            except Exception as exc:  # noqa: BLE001 - never let a worker die silently
                st.status = "error"
                st.error = {"code": "errGeneric", "detail": str(exc)}
                st.fetched = time.time()
                st.rev += 1
                self.log.error("api", f"{self._where(st)}: unexpected {exc!r}")

        if wait:
            work()
        else:
            threading.Thread(target=work, daemon=True).start()
        return {"ok": True}

    # ---- key actions ---------------------------------------------------------------------------

    def _find(self, sid: str, ip: str):
        """
        _find(sid, ip) -> (ServerState, key) or (st, None)
        Usage: st, key = self._find(sid, "10.66.0.5")
        """
        st = self.servers.get(sid)
        if not st:
            return None, None
        with st.lock:
            return st, next((k for k in st.keys if k["ip"] == ip), None)

    def _act(self, label: str, sid: str, fn):
        """
        _act(label, sid, fn) -> dict
        Usage: return self._act("create", sid, lambda c: c.create_key(name))
        Runs one key action with the busy flag set, then pulls the keys again.
        """
        st = self.servers.get(sid)
        if not st:
            return {"ok": False, "error": {"code": "errGeneric"}}
        if self.busy:
            return {"ok": False, "error": {"code": "errBusy"}}
        self.busy = label
        try:
            client = st.client()
            result = fn(client)
            try:
                self._apply(st, client.list_keys(), client)
            except ApiError:
                pass
            return {"ok": True, "result": result}
        except ApiError as exc:
            self.log.error("key", f"{label.split(':')[0]} failed on {self._where(st)}: {exc.code} {exc.detail}")
            return {"ok": False, "error": {"code": exc.code, "detail": exc.detail, "got": exc.got}}
        finally:
            self.busy = ""

    def features(self, sid: str) -> list:
        """
        features(sid) -> list
        Usage: if "pause" in ctl.features(sid): ...     # what the server's API can do (from GET /keys -> server)
        """
        st = self.servers.get(sid)
        return list((st.server.get("features") or [])) if st else []

    def _expiry(self, sid: str, expiry) -> tuple:
        """
        _expiry(sid, expiry) -> (body or None, error dict or None)
        Usage: body, err = self._expiry(sid, ("now", "30 days"))
        expiry: None or ("keep",) = leave as is; ("none",) = no time limit; ("now", "30d") = ends that long from now;
        ("first", "1m") = ends that long after the key's first connection; ("on", "2026-12-31 18:00") = ends then,
        on the server's clock (API 2.3).
        """
        if not expiry or expiry[0] == "keep":
            return None, None
        if expiry[0] == "on":
            when = parse_end_on(expiry[1] if len(expiry) > 1 else "")
            if not when:
                return None, {"code": "errBadEndOn"}
            if "expiryOn" not in self.features(sid):
                return None, {"code": "errOldApi"}
            return expiry_body("on", when), None
        dur = ""
        if expiry[0] in ("now", "first"):
            dur = parse_duration(expiry[1] if len(expiry) > 1 else "")
            if not dur:
                return None, {"code": "errBadDuration"}
        if "expiry" not in self.features(sid):
            return None, {"code": "errOldApi"}
        return expiry_body(expiry[0], dur), None

    def create_key(self, sid: str, name: str = "", traffic="", expiry=None) -> dict:
        """
        create_key(sid, name="", traffic="", expiry=None) -> dict
        Usage: r = ctl.create_key(sid, "Ali phone", "20G", ("first", "1m"))   # {ok, result: {"ip": ...}}
        traffic "" = unlimited; expiry: see _expiry() (None = no time limit)
        """
        name = re.sub(r"[\x00-\x1f\x7f]", " ", name or "").strip()[:64]
        limit = parse_traffic(traffic)
        if limit is None:
            return {"ok": False, "error": {"code": "errBadTraffic"}}
        if limit and "limit" not in self.features(sid):
            return {"ok": False, "error": {"code": "errOldApi"}}
        exp_body, err = self._expiry(sid, expiry if expiry and expiry[0] != "none" else None)
        if err:
            return {"ok": False, "error": err}

        def go(c):
            """
            go(client) -> dict
            Usage: internal to create_key
            """
            k = c.create_key(name, limit, exp_body)
            if k.get("config"):
                self.cache.put(sid, k["ip"], name, k["config"])
            self.log.info("key", f"created {k['ip']}" + (f" ({name})" if name else "") +
                          (f", limit {limit_text(limit)}" if limit else "") +
                          (f", time limit {exp_body}" if exp_body else "") + f" on {self._where(sid)}")
            return {"ip": k["ip"]}
        return self._act("create", sid, go)

    def remove_key(self, sid: str, ip: str) -> dict:
        """
        remove_key(sid, ip) -> dict
        Usage: ctl.remove_key(sid, "10.66.0.5")
        """
        def go(c):
            """
            go(client)
            Usage: internal to remove_key
            """
            c.remove_key(ip)
            self.cache.forget(sid, ip)
            self.log.info("key", f"removed {ip} from {self._where(sid)}")
        return self._act("remove:" + ip, sid, go)

    def rename_key(self, sid: str, ip: str, name: str) -> dict:
        """
        rename_key(sid, ip, name) -> dict
        Usage: ctl.rename_key(sid, "10.66.0.5", "Office")
        """
        name = re.sub(r"[\x00-\x1f\x7f]", " ", name or "").strip()[:64]
        if not name:
            return {"ok": False, "error": {"code": "errNameEmpty"}}

        def go(c):
            """
            go(client)
            Usage: internal to rename_key
            """
            c.rename_key(ip, name)
            self.log.info("key", f"renamed {ip} to \"{name}\" on {self._where(sid)}")
        return self._act("rename:" + ip, sid, go)

    def set_paused(self, sid: str, ip: str, paused: bool) -> dict:
        """
        set_paused(sid, ip, paused) -> dict
        Usage: ctl.set_paused(sid, "10.66.0.5", True)    # pause; False resumes
        """
        if "pause" not in self.features(sid):
            return {"ok": False, "error": {"code": "errOldApi"}}

        def go(c):
            """
            go(client)
            Usage: internal to set_paused
            """
            c.set_paused(ip, paused)
            self.log.info("key", f"{'paused' if paused else 'resumed'} {ip} on {self._where(sid)}")
        return self._act(("pause:" if paused else "resume:") + ip, sid, go)

    def edit_key(self, sid: str, ip: str, name: str, traffic, expiry=None) -> dict:
        """
        edit_key(sid, ip, name, traffic, expiry=None) -> dict
        Usage: ctl.edit_key(sid, "10.66.0.5", "Office", "50G", ("now", "30d"))
        traffic "" = unlimited; expiry: see _expiry() (None = keep); only changed fields are sent
        """
        name = re.sub(r"[\x00-\x1f\x7f]", " ", name or "").strip()[:64]
        if not name:
            return {"ok": False, "error": {"code": "errNameEmpty"}}
        limit = parse_traffic(traffic)
        if limit is None:
            return {"ok": False, "error": {"code": "errBadTraffic"}}
        _st, k = self._find(sid, ip)
        old_name, old_limit = (k or {}).get("name", ""), (k or {}).get("limit", 0)
        if limit != old_limit and "limit" not in self.features(sid):
            return {"ok": False, "error": {"code": "errOldApi"}}
        exp_body, err = self._expiry(sid, expiry)
        if err:
            return {"ok": False, "error": err}

        def go(c):
            """
            go(client)
            Usage: internal to edit_key
            """
            if name != old_name:
                c.rename_key(ip, name)
                self.log.info("key", f"renamed {ip} to \"{name}\" on {self._where(sid)}")
            if limit != old_limit:
                c.set_limit(ip, limit)
                self.log.info("key", f"limit of {ip} set to {limit_text(limit) or 'unlimited'} on {self._where(sid)}")
            if exp_body:
                c.set_expiry(ip, exp_body)
                self.log.info("key", f"time limit of {ip} set to {exp_body} on {self._where(sid)}")
        return self._act("edit:" + ip, sid, go)

    def key_detail(self, sid: str, ip: str) -> dict:
        """
        key_detail(sid, ip) -> dict
        Usage: d = ctl.key_detail(sid, "10.66.0.5")   # the full key incl. private key, config and a QR code (SVG)
        """
        st, k = self._find(sid, ip)
        if not k:
            return {"ok": False}
        d = dict(k)
        d["qr"] = qr_svg(k["config"]) if k["config"] else ""
        d["fileName"] = safe_filename((k["name"] or (st.name + "-" + ip)).replace(" ", "_")) + ".conf"
        return {"ok": True, "key": d}

    def key_config(self, sid: str, ip: str) -> str:
        """
        key_config(sid, ip) -> str
        Usage: text = ctl.key_config(sid, "10.66.0.5")    # "" when the server never stored its private key
        """
        _st, k = self._find(sid, ip)
        return (k or {}).get("config", "")

    def export_all(self, sid: str, folder: str) -> dict:
        """
        export_all(sid, folder) -> dict
        Usage: ctl.export_all(sid, r"C:\\Users\\me\\Desktop\\keys")   # one <name or ip>.conf per key with a config
        """
        st = self.servers.get(sid)
        if not st or not folder:
            return {"ok": False, "count": 0}
        n, used = 0, set()
        with st.lock:
            keys = list(st.keys)
        for k in keys:
            if not k["config"]:
                continue
            stem = safe_filename(k["name"] or k["ip"])
            base, i = stem, 2
            while stem.lower() in used:
                stem, i = f"{base}-{i}", i + 1
            used.add(stem.lower())
            try:
                with open(os.path.join(folder, stem + ".conf"), "w", encoding="utf-8", newline="\n") as f:
                    f.write(k["config"])
                n += 1
            except OSError as exc:
                self.log.error("export", f"{self._where(st)}: {exc}")
                return {"ok": False, "count": n}
        self.log.info("export", f"wrote {n} config file(s) of {self._where(st)} to {folder}")
        return {"ok": True, "count": n}

    # ---- settings, logs, links ------------------------------------------------------------------

    def set_theme(self, theme: str) -> None:
        """
        set_theme(theme)
        Usage: ctl.set_theme("light")
        """
        if theme in ("dark", "light"):
            self.settings.set("theme", theme)

    def set_language(self, lang: str) -> None:
        """
        set_language(lang)
        Usage: ctl.set_language("fa")
        """
        if lang in ("en", "fa"):
            self.settings.set("lang", lang)

    def set_refresh(self, seconds: int) -> None:
        """
        set_refresh(seconds)
        Usage: ctl.set_refresh(60)     # 0 turns auto refresh off
        """
        if int(seconds) in config.REFRESH_CHOICES:
            self.settings.set("refresh", int(seconds))

    def open_link(self, name: str) -> bool:
        """
        open_link(name) -> bool
        Usage: ctl.open_link("about")    # only the names in config.LINKS
        """
        url = config.LINKS.get(name)
        if not url:
            return False
        webbrowser.open(url)
        return True

    def open_log_folder(self) -> bool:
        """
        open_log_folder() -> bool
        Usage: ctl.open_log_folder()
        """
        path = str(config.log_dir())
        try:
            if os.name == "nt":
                os.startfile(path)      # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
            return True
        except OSError:
            return False


def qr_svg(text: str) -> str:
    """
    qr_svg(text) -> str
    Usage: html = qr_svg(config_text)    # an inline <svg> QR code the WireGuard mobile app can scan
    """
    try:
        from mwg_core._vendor import segno
    except ImportError:
        return ""
    try:
        q = segno.make(text, error="l", micro=False)
        return q.svg_inline(scale=4, border=2, dark="#0b0e14", light="#ffffff")
    except Exception:  # noqa: BLE001 - a QR code is optional
        return ""
