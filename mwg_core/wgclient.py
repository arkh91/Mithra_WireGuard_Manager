# File: core/wgclient.py
# HTTPS client for the wg-api of install-wg-full.sh, with Outline-style certificate pinning (certSha256).
# Edit with: vi core/wgclient.py
"""
How a request is made (same idea as Outline Manager):
  1. open a TLS connection to apiUrl's host:port
  2. when the access config has certSha256: hash the certificate the server presented (SHA-256 of its DER bytes,
     which is what `openssl x509 -fingerprint -sha256` prints) and compare. A mismatch stops BEFORE anything is
     sent, so the token never reaches a wrong server. Without certSha256 the normal Windows CA check is used.
  3. send the request, with "Authorization: Bearer <apiToken>" when the config has a token.

Pulling all keys tries the newest route first and falls back for older servers:
  GET /access-keys  ->  GET /keys  ->  GET /usage (very old API: usage only, no private keys or configs)
Only the standard library is used.
"""
import hashlib
import http.client
import json
import re
import socket
import ssl
import time
from typing import Optional

from mwg_core.access import AccessConfig
from mwg_core import config


class ApiError(Exception):
    """
    ApiError(code, detail="", status=0)
    Usage: except ApiError as e: show(tr(e.code), e.detail)
    code is an i18n key (errCertMismatch, errUnauthorized, errUnreachable, errTimeout, errTls, errHttp,
    errOldApi, errBadReply, errPoolFull, errNoKey).
    """

    def __init__(self, code: str, detail: str = "", status: int = 0, got: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
        self.status = status
        self.got = got          # for errCertMismatch: the fingerprint the server presented


def cert_fingerprint(der: bytes) -> str:
    """
    cert_fingerprint(der) -> str
    Usage: fp = cert_fingerprint(sock.getpeercert(binary_form=True))   # "9D138F..."
    """
    return hashlib.sha256(der or b"").hexdigest().upper()


class WgClient:
    """
    WgClient(access_config, timeout=config.HTTP_TIMEOUT)
    Usage: c = WgClient(parse_access(text)); data = c.list_keys(); c.create_key("Phone"); c.remove_key("10.66.0.5")
    """

    def __init__(self, access: AccessConfig, timeout: float = config.HTTP_TIMEOUT):
        """
        __init__(access, timeout)
        Usage: WgClient(cfg)
        """
        self.access = access
        self.timeout = timeout
        self.presented_fp = ""      # fingerprint seen on the last connection
        self.verified = False       # True after a connection whose certificate matched certSha256

    # ---- low level -----------------------------------------------------------------

    def _context(self) -> ssl.SSLContext:
        """
        _context() -> ssl.SSLContext
        Usage: ctx = self._context()
        Pinned mode: no CA check (the fingerprint check replaces it). Otherwise: the system's trusted CAs.
        """
        if self.access.cert_sha256:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            return ctx
        return ssl.create_default_context()

    def request(self, method: str, path: str, body: Optional[dict] = None) -> tuple:
        """
        request(method, path, body=None) -> (status, content_type, text)
        Usage: status, ctype, text = client.request("GET", "/keys")
        Raises ApiError for network, TLS and certificate problems (HTTP error statuses are returned).
        """
        a = self.access
        conn = http.client.HTTPSConnection(a.host, a.port, timeout=self.timeout, context=self._context())
        try:
            try:
                conn.connect()
            except ssl.SSLCertVerificationError as exc:
                raise ApiError("errTls", str(exc.verify_message or exc)) from exc
            except ssl.SSLError as exc:
                raise ApiError("errTls", str(exc)) from exc
            except socket.timeout as exc:
                raise ApiError("errTimeout", f"{a.host}:{a.port}") from exc
            except OSError as exc:
                raise ApiError("errUnreachable", f"{a.host}:{a.port} ({exc.strerror or exc})") from exc
            der = conn.sock.getpeercert(binary_form=True)
            self.presented_fp = cert_fingerprint(der)
            if a.cert_sha256:
                if self.presented_fp != a.cert_sha256:
                    self.verified = False
                    raise ApiError("errCertMismatch", f"expected {a.cert_sha256}", got=self.presented_fp)
                self.verified = True
            headers = {"Accept": "application/json", "User-Agent": f"MithraWireGuardManager/{config.app_version()}"}
            if a.api_token:
                headers["Authorization"] = "Bearer " + a.api_token
            data = None
            if body is not None:
                data = json.dumps(body).encode("utf-8")
                headers["Content-Type"] = "application/json"
            try:
                conn.request(method, a.request_target(path), body=data, headers=headers)
                resp = conn.getresponse()
                raw = resp.read()
            except socket.timeout as exc:
                raise ApiError("errTimeout", f"{a.host}:{a.port}") from exc
            except (OSError, http.client.HTTPException) as exc:
                raise ApiError("errUnreachable", str(exc)) from exc
            return resp.status, (resp.getheader("Content-Type") or ""), raw.decode("utf-8", "replace")
        finally:
            conn.close()

    @staticmethod
    def _error_text(text: str) -> str:
        """
        _error_text(text) -> str
        Usage: msg = WgClient._error_text(body)   # the "error" field of a JSON error reply, else the text
        """
        try:
            obj = json.loads(text)
            if isinstance(obj, dict) and obj.get("error"):
                return str(obj["error"])
        except ValueError:
            pass
        return text.strip()[:300]

    def _check(self, status: int, text: str) -> None:
        """
        _check(status, text)
        Usage: self._check(status, text)    # raises ApiError for any non-2xx reply
        """
        if 200 <= status < 300:
            return
        msg = self._error_text(text)
        if status == 401:
            raise ApiError("errUnauthorized", msg, status)
        if status == 404 and "no such key" in msg:
            raise ApiError("errNoKey", msg, status)
        if status == 404:
            raise ApiError("errOldApi", msg, status)
        if status == 503 and "exhausted" in msg:
            raise ApiError("errPoolFull", msg, status)
        if status == 429:
            raise ApiError("errRateLimited", msg, status)
        raise ApiError("errHttp", f"HTTP {status}: {msg}", status)

    def _json(self, method: str, path: str, body: Optional[dict] = None):
        """
        _json(method, path, body=None) -> object
        Usage: obj = self._json("GET", "/keys")
        """
        status, _ctype, text = self.request(method, path, body)
        self._check(status, text)
        try:
            return json.loads(text) if text.strip() else {}
        except ValueError as exc:
            raise ApiError("errBadReply", text[:200], status) from exc

    # ---- API ---------------------------------------------------------------------------

    def health(self) -> bool:
        """
        health() -> bool
        Usage: ok = client.health()   # GET /health (public; also checks the certificate)
        Note: with a secret path the health route is under it too, so it also proves the secret is right.
        """
        try:
            self._json("GET", "/health")
            return True
        except ApiError as exc:
            if exc.code in ("errCertMismatch", "errUnauthorized", "errTls"):
                raise
            return False

    def list_keys(self) -> dict:
        """
        list_keys() -> dict
        Usage: data = client.list_keys()
        Returns {"keys": [normalized key...], "server": {...}, "legacy": bool, "route": str, "fetched": epoch}.
        Tries /access-keys, then /keys, then /usage (old servers).
        """
        last = None
        for route in ("/access-keys", "/keys"):
            try:
                obj = self._json("GET", route)
            except ApiError as exc:
                if exc.code != "errOldApi":
                    raise
                last = exc
                continue
            raw = obj.get("accessKeys") if isinstance(obj, dict) and "accessKeys" in obj else obj.get("keys", [])
            if not isinstance(raw, list):
                raise ApiError("errBadReply", "no key list in the reply")
            return {"keys": [normalize_key(k, obj.get("server") or {}) for k in raw if isinstance(k, dict)],
                    "server": obj.get("server") or {}, "legacy": False, "route": route, "fetched": time.time()}
        try:
            obj = self._json("GET", "/usage")
        except ApiError as exc:
            if exc.code == "errOldApi" and last:
                raise last
            raise
        keys = [normalize_key(k, {}) for k in obj.get("keys", []) if isinstance(k, dict)]
        return {"keys": keys, "server": {}, "legacy": True, "route": "/usage", "fetched": time.time()}

    def create_key(self, name: str = "", limit: int = 0, expiry: dict | None = None) -> dict:
        """
        create_key(name="", limit=0, expiry=None) -> dict
        Usage: key = client.create_key("Ali phone", 20_000_000_000, {"expires": "30d"})   # normalized key, with its config
        POST /create?format=json works on every server version (older ones ignore the name or answer with text).
        limit is the traffic limit in bytes (0 = unlimited; "limit" feature, API 2.1); expiry is a time limit body from
        limits.expiry_body() ("expiry" feature, API 2.2).
        """
        body = {"name": name} if name else {}
        if limit:
            body["traffic"] = int(limit)
        if expiry:
            body.update(expiry)
        status, ctype, text = self.request("POST", "/create?format=json", body)
        self._check(status, text)
        if "json" in ctype:
            try:
                return normalize_key(json.loads(text), {})
            except ValueError as exc:
                raise ApiError("errBadReply", text[:200], status) from exc
        return key_from_config(text, name)

    def remove_key(self, ip: str) -> None:
        """
        remove_key(ip)
        Usage: client.remove_key("10.66.0.5")
        """
        self._json("POST", "/remove", {"ipAddress": ip})

    def rename_key(self, ip: str, name: str) -> dict:
        """
        rename_key(ip, name) -> dict
        Usage: client.rename_key("10.66.0.5", "Office laptop")
        PUT /keys/<ip>/name. A 404 means the server API predates names (run install-wg-full.sh --update-api).
        """
        obj = self._json("PUT", f"/keys/{ip}/name", {"name": name})
        return normalize_key(obj, {}) if isinstance(obj, dict) else {}

    def set_paused(self, ip: str, paused: bool) -> dict:
        """
        set_paused(ip, paused) -> dict
        Usage: client.set_paused("10.66.0.5", True)    # POST /keys/<ip>/pause or /resume (API 2.1)
        A paused key stays configured but none of its traffic passes until it is resumed.
        """
        obj = self._json("POST", f"/keys/{ip}/{'pause' if paused else 'resume'}", {})
        return normalize_key(obj, {}) if isinstance(obj, dict) else {}

    def set_expiry(self, ip: str, expiry: dict) -> dict:
        """
        set_expiry(ip, expiry) -> dict
        Usage: client.set_expiry("10.66.0.5", {"expiresAfterFirstConnection": "1m"})   # PUT /keys/<ip>/expiry (API 2.2)
        """
        obj = self._json("PUT", f"/keys/{ip}/expiry", expiry)
        return normalize_key(obj, {}) if isinstance(obj, dict) else {}

    def set_limit(self, ip: str, limit: int) -> dict:
        """
        set_limit(ip, limit) -> dict
        Usage: client.set_limit("10.66.0.5", 20_000_000_000)   # PUT /keys/<ip>/limit; 0 = unlimited (API 2.1)
        """
        obj = self._json("PUT", f"/keys/{ip}/limit", {"traffic": int(limit) if limit else "unlimited"})
        return normalize_key(obj, {}) if isinstance(obj, dict) else {}


# ---- normalising --------------------------------------------------------------------------

def _int(v) -> int:
    """
    _int(v) -> int
    Usage: _int("12")  # 12; bad values -> 0
    """
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _limit_bytes(k: dict) -> int:
    """
    _limit_bytes(k) -> int
    Usage: limit = _limit_bytes(api_key)    # dataLimitBytes, or Outline's dataLimit {"bytes": N}; 0 = unlimited
    """
    if k.get("dataLimitBytes"):
        return _int(k["dataLimitBytes"])
    dl = k.get("dataLimit")
    return _int(dl.get("bytes")) if isinstance(dl, dict) else 0


def normalize_key(k: dict, server: dict) -> dict:
    """
    normalize_key(k, server) -> dict
    Usage: key = normalize_key(api_key_object, reply.get("server", {}))
    One key in the app's shape, whatever API version sent it.
    """
    ip = str(k.get("ipAddress") or k.get("id") or str(k.get("address") or "").split("/")[0])
    up, down = _int(k.get("uploadBytes")), _int(k.get("downloadBytes"))
    total = _int(k.get("totalBytes")) or up + down
    return {
        "id": ip,
        "ip": ip,
        "name": str(k.get("name") or ""),
        "address": str(k.get("address") or (ip + "/32" if ip else "")),
        "publicKey": str(k.get("publicKey") or ""),
        "privateKey": k.get("privateKey") or "",
        "dns": str(k.get("dns") or server.get("dns") or ""),
        "serverPublicKey": str(k.get("serverPublicKey") or server.get("publicKey") or ""),
        "endpoint": str(k.get("endpoint") or server.get("endpoint") or ""),
        "allowedIPs": str(k.get("allowedIPs") or ""),
        "keepalive": _int(k.get("persistentKeepalive")),
        "createdAt": k.get("createdAt") or "",
        "up": up,
        "down": down,
        "total": total,
        "lastHandshake": k.get("lastHandshake") or "",
        "paused": bool(k.get("paused")),
        "limit": _limit_bytes(k),
        "limitReached": bool(k.get("limitReached")),
        "expiresAt": k.get("expiresAt") or "",                       # ISO time, "" = no end (yet)
        "expiresAtServer": str(k.get("expiresAtServer") or ""),      # the same end on the server's clock (API 2.3)
        "expiresAfter": str(k.get("expiresAfterFirstConnection") or ""),   # e.g. "30d": counted from first connection
        "firstConnectedAt": k.get("firstConnectedAt") or "",     # every key (API 2.2.1+); "" = never connected
        "expired": bool(k.get("expired")),
        "config": k.get("config") or "",
    }


def key_from_config(text: str, name: str = "") -> dict:
    """
    key_from_config(text, name="") -> dict
    Usage: key = key_from_config(wg_quick_text)
    Builds a normalized key from a client config (the text reply of an old POST /create).
    """
    def field(n):
        m = re.search(r"^\s*" + n + r"\s*=\s*(.+?)\s*$", text, re.M | re.I)
        return m.group(1) if m else ""
    addr = field("Address")
    ip = addr.split("/")[0]
    return normalize_key({
        "ipAddress": ip, "address": addr, "name": name, "privateKey": field("PrivateKey"), "dns": field("DNS"),
        "serverPublicKey": field("PublicKey"), "endpoint": field("Endpoint"), "allowedIPs": field("AllowedIPs"),
        "persistentKeepalive": field("PersistentKeepalive"), "config": text if "[Interface]" in text else "",
    }, {})
