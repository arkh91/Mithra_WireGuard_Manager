# File: core/store.py
# Files the app keeps on disk: settings and the list of servers. Access configs are secrets (they open every key),
# so they are encrypted with Windows DPAPI for the current Windows user.
# Edit with: vi core/store.py
"""
  %LOCALAPPDATA%\\MithraWireGuard\\settings.json   theme, language, auto refresh
  %LOCALAPPDATA%\\MithraWireGuard\\servers.json    [{id, name, added, access (DPAPI, base64)}]
Off Windows (development only) the access config is stored base64-encoded, file mode 600.
"""
import base64
import ctypes
import json
import os
import threading
import time
import uuid
from pathlib import Path

from mwg_core import config


def _read_json(path: Path, default):
    """
    _read_json(path, default) -> object
    Usage: data = _read_json(p, {})
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data) -> None:
    """
    _write_json(path, data)
    Usage: _write_json(p, {"a": 1})    # atomic: temp file, then replace
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    if os.name != "nt":
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)


class Settings:
    """
    Settings(path=None)
    Usage: s = Settings(); s.get("theme"); s.set("theme", "light")
    """
    DEFAULTS = {"theme": "dark", "lang": "en", "refresh": config.REFRESH_DEFAULT, "selected": ""}

    def __init__(self, path: Path = None):
        """
        __init__(path=None)
        Usage: Settings()
        """
        self.path = path or (config.user_dir() / "settings.json")
        self.data = dict(self.DEFAULTS)
        self.data.update(_read_json(self.path, {}))

    def get(self, key: str):
        """
        get(key) -> value
        Usage: theme = settings.get("theme")
        """
        return self.data.get(key, self.DEFAULTS.get(key))

    def set(self, key: str, value) -> None:
        """
        set(key, value)
        Usage: settings.set("lang", "fa")    # saves immediately
        """
        self.data[key] = value
        try:
            _write_json(self.path, self.data)
        except OSError:
            pass


# ---- DPAPI ----------------------------------------------------------------------------------

class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data: bytes, encrypt: bool) -> bytes:
    """
    _dpapi(data, encrypt) -> bytes
    Usage: blob = _dpapi(b"secret", True); back = _dpapi(blob, False)
    CryptProtectData / CryptUnprotectData for the current Windows user. Raises OSError on failure.
    """
    crypt32 = ctypes.windll.crypt32      # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32    # type: ignore[attr-defined]
    buf = ctypes.create_string_buffer(data, len(data))
    src = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    dst = _Blob()
    fn = crypt32.CryptProtectData if encrypt else crypt32.CryptUnprotectData
    if not fn(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(dst)):
        raise OSError("DPAPI call failed")
    try:
        return ctypes.string_at(dst.pbData, dst.cbData)
    finally:
        kernel32.LocalFree(dst.pbData)


def seal(text: str) -> str:
    """
    seal(text) -> str
    Usage: stored = seal(access_json)
    Encrypts for this Windows user (DPAPI) and returns base64. Off Windows: base64 only.
    """
    raw = text.encode("utf-8")
    if os.name == "nt":
        raw = _dpapi(raw, True)
    return base64.b64encode(raw).decode("ascii")


def unseal(stored: str) -> str:
    """
    unseal(stored) -> str
    Usage: access_json = unseal(entry["access"])     # "" if it cannot be read (other user / other PC)
    """
    try:
        raw = base64.b64decode(stored)
        if os.name == "nt":
            raw = _dpapi(raw, False)
        return raw.decode("utf-8")
    except (OSError, ValueError):
        return ""


class ServerStore:
    """
    ServerStore(path=None)
    Usage: st = ServerStore(); sid = st.add("pak01", access_json); st.all(); st.rename(sid, "x"); st.remove(sid)
    Entries returned by all() carry the decrypted access text under "access".
    """

    def __init__(self, path: Path = None):
        """
        __init__(path=None)
        Usage: ServerStore()
        """
        self.path = path or (config.user_dir() / "servers.json")
        self._lock = threading.Lock()
        raw = _read_json(self.path, [])
        self._items = raw if isinstance(raw, list) else []

    def _save(self) -> None:
        """
        _save()
        Usage: self._save()
        """
        try:
            _write_json(self.path, self._items)
        except OSError:
            pass

    def all(self) -> list:
        """
        all() -> list
        Usage: for s in store.all(): print(s["id"], s["name"], s["access"])
        """
        with self._lock:
            return [{"id": i["id"], "name": i.get("name", ""), "added": i.get("added", 0),
                     "access": unseal(i.get("access", ""))} for i in self._items]

    def add(self, name: str, access_json: str) -> str:
        """
        add(name, access_json) -> str
        Usage: sid = store.add("Pakistan 01", cfg.to_json())
        """
        sid = uuid.uuid4().hex[:12]
        with self._lock:
            self._items.append({"id": sid, "name": name, "added": int(time.time()), "access": seal(access_json)})
            self._save()
        return sid

    def update_access(self, sid: str, access_json: str) -> None:
        """
        update_access(sid, access_json)
        Usage: store.update_access(sid, new_cfg.to_json())    # e.g. after a server reinstall
        """
        with self._lock:
            for i in self._items:
                if i["id"] == sid:
                    i["access"] = seal(access_json)
            self._save()

    def rename(self, sid: str, name: str) -> None:
        """
        rename(sid, name)
        Usage: store.rename(sid, "Karachi")
        """
        with self._lock:
            for i in self._items:
                if i["id"] == sid:
                    i["name"] = name
            self._save()

    def remove(self, sid: str) -> None:
        """
        remove(sid)
        Usage: store.remove(sid)     # forgets the server in this app; nothing changes on the server
        """
        with self._lock:
            self._items = [i for i in self._items if i["id"] != sid]
            self._save()


class KeyCache:
    """
    KeyCache(path=None)
    Usage: kc = KeyCache(); kc.put(sid, "10.66.0.5", "Ali phone", config_text); kc.get(sid); kc.forget(sid, "10.66.0.5")
    Remembers the configs of keys this app created, encrypted like the access configs (DPAPI on Windows). Older servers
    only hand out a key's config once, when it is created; this lets you copy, scan or save it again later.
    """

    def __init__(self, path: Path = None):
        """
        __init__(path=None)
        Usage: KeyCache()
        """
        self.path = path or (config.user_dir() / "keys.json")
        self._lock = threading.Lock()
        raw = _read_json(self.path, {})
        self._data = raw if isinstance(raw, dict) else {}

    def _save(self) -> None:
        """
        _save()
        Usage: internal
        """
        try:
            _write_json(self.path, self._data)
        except OSError:
            pass

    def put(self, sid: str, ip: str, name: str, config_text: str) -> None:
        """
        put(sid, ip, name, config_text)
        Usage: cache.put(sid, "10.66.0.5", "Ali phone", wg_quick_text)
        """
        with self._lock:
            self._data.setdefault(sid, {})[ip] = {"name": name, "config": seal(config_text), "t": int(time.time())}
            self._save()

    def get(self, sid: str) -> dict:
        """
        get(sid) -> dict
        Usage: cache.get(sid)     # {ip: {"name": ..., "config": decrypted text}}
        """
        with self._lock:
            return {ip: {"name": v.get("name", ""), "config": unseal(v.get("config", "")), "t": v.get("t", 0)}
                    for ip, v in self._data.get(sid, {}).items()}

    def forget(self, sid: str, ip: str = "") -> None:
        """
        forget(sid, ip="")
        Usage: cache.forget(sid, "10.66.0.5")     # one key;  cache.forget(sid) drops the whole server
        """
        with self._lock:
            if ip:
                self._data.get(sid, {}).pop(ip, None)
            else:
                self._data.pop(sid, None)
            self._save()
