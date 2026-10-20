# File: core/access.py
# Reads a server's access config, the line install-wg-full.sh prints (and saves in /etc/wg-api/access*.json).
# Edit with: vi core/access.py
"""
Two formats are accepted, both open every key on the server:

  token format    {"apiUrl":"https://vpn.example.com:2053","apiToken":"35c4...","certSha256":"9D13..."}
  Outline format  {"apiUrl":"https://vpn.example.com:2053/Xy7secretPath","certSha256":"9D13..."}

Like Outline Manager, the text may contain other words around the JSON (a pasted terminal block); the first
{...} that has an apiUrl is used. certSha256 may be upper or lower case, with or without colons, or missing/null
(a real CA certificate such as Let's Encrypt is then checked the normal way).
"""
import json
import re
from dataclasses import dataclass
from urllib.parse import urlsplit


class AccessError(ValueError):
    """
    AccessError(code)
    Usage: raise AccessError("errNoJson")
    A config that cannot be used. The code is an i18n key the UI shows.
    """


@dataclass(frozen=True)
class AccessConfig:
    """
    AccessConfig(api_url, api_token, cert_sha256, host, port, secret_path)
    Usage: cfg = parse_access(text); cfg.url("/access-keys")
    """
    api_url: str          # without trailing slash; in Outline format it ends with the secret path
    api_token: str        # "" in Outline format
    cert_sha256: str      # 64 upper-case hex characters, or "" for normal CA verification
    host: str
    port: int
    secret_path: bool     # True when the secret is the path of api_url (Outline format)

    def url(self, path: str) -> str:
        """
        url(path) -> str
        Usage: cfg.url("/access-keys")   # -> https://host:2053[/secret]/access-keys
        """
        return self.api_url + ("/" + path.lstrip("/") if path else "")

    def request_target(self, path: str) -> str:
        """
        request_target(path) -> str
        Usage: conn.request("GET", cfg.request_target("/keys"))
        The path part of url(path), as sent in the HTTP request line.
        """
        parts = urlsplit(self.url(path))
        return (parts.path or "/") + ("?" + parts.query if parts.query else "")

    def to_json(self) -> str:
        """
        to_json() -> str
        Usage: text = cfg.to_json()    # the canonical one-line access config (same shape the server prints)
        """
        data = {"apiUrl": self.api_url}
        if self.api_token:
            data["apiToken"] = self.api_token
        data["certSha256"] = self.cert_sha256 or None
        return json.dumps(data, separators=(",", ":"))

    def default_name(self) -> str:
        """
        default_name() -> str
        Usage: name = cfg.default_name()   # "pak.pak01dir.mithracorp.com"
        """
        return self.host


def _json_objects(text: str):
    """
    _json_objects(text) -> iterator of dict
    Usage: for obj in _json_objects(pasted): ...
    Every JSON object found in the text, in order (a plain JSON paste is just the first one).
    """
    dec = json.JSONDecoder()
    i = 0
    while True:
        i = text.find("{", i)
        if i < 0:
            return
        try:
            obj, end = dec.raw_decode(text, i)
        except ValueError:
            i += 1
            continue
        if isinstance(obj, dict):
            yield obj
        i = end


def normalize_fingerprint(value) -> str:
    """
    normalize_fingerprint(value) -> str
    Usage: normalize_fingerprint("9d:13:8f...")   # "9D138F..."
    Upper-case hex without separators, "" for None/empty. Raises AccessError when it is not a SHA-256.
    """
    if value is None:
        return ""
    fp = re.sub(r"[\s:]", "", str(value)).upper()
    if not fp:
        return ""
    if not re.fullmatch(r"[0-9A-F]{64}", fp):
        raise AccessError("errBadCert")
    return fp


def parse_access(text: str) -> AccessConfig:
    """
    parse_access(text) -> AccessConfig
    Usage: cfg = parse_access('{"apiUrl":"https://h:2053","apiToken":"...","certSha256":"..."}')
    Raises AccessError with an i18n key when the text is not a usable access config.
    """
    text = (text or "").strip()
    # smart quotes from chat apps break JSON
    text = text.replace("“", '"').replace("”", '"')
    obj = next((o for o in _json_objects(text) if "apiUrl" in o), None)
    if obj is None:
        raise AccessError("errNoJson")
    api_url = str(obj.get("apiUrl") or "").strip().rstrip("/")
    token = str(obj.get("apiToken") or obj.get("token") or "").strip()
    fp = normalize_fingerprint(obj.get("certSha256"))
    parts = urlsplit(api_url)
    if parts.scheme.lower() != "https" or not parts.hostname:
        raise AccessError("errNotHttps")
    try:
        port = parts.port or 443
    except ValueError as exc:
        raise AccessError("errBadUrl") from exc
    secret = bool(parts.path.strip("/"))
    if not token and not secret:
        raise AccessError("errNoSecret")
    if any(c in token for c in "\r\n\t "):
        raise AccessError("errBadToken")
    return AccessConfig(api_url=api_url, api_token=token, cert_sha256=fp, host=parts.hostname,
                        port=port, secret_path=secret)
