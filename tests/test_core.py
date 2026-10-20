# File: tests/test_core.py
# Tests of the access config parser, the pinned HTTPS client (with fallbacks for older servers), the store and the
# controller. A small HTTPS mock server with a self-signed certificate stands in for wg-api.
# Run: python -m pytest tests      Edit with: vi tests/test_core.py
import hashlib
import json
import os
import shutil
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from mwg_core.access import AccessError, parse_access
from mwg_core.wgclient import ApiError, WgClient, key_from_config, normalize_key

TOKEN = "a" * 64
SECRET = "SecretPath_abcdefghij"
CONF = "[Interface]\nPrivateKey = cHJpdg==\nAddress = 10.66.0.9/32\nDNS = 1.1.1.1\n\n[Peer]\nPublicKey = c3J2\nEndpoint = vpn.example.com:51820\nAllowedIPs = 0.0.0.0/0\nPersistentKeepalive = 25\n"


# ---- access config ------------------------------------------------------------------------------

def test_parse_token_format():
    """
    test_parse_token_format()
    Usage: pytest -k token_format
    The exact config of the user's server is understood.
    """
    c = parse_access('{"apiUrl":"https://vpn.example.com:2053","apiToken":"' + "35c4" * 16 +
                     '","certSha256":"ABABABABABABABABABABABABABABABABABABABABABABABABABABABABABABABAB"}')
    assert (c.host, c.port, c.secret_path) == ("vpn.example.com", 2053, False)
    assert c.request_target("/access-keys") == "/access-keys"
    assert c.cert_sha256.startswith("ABAB")


def test_parse_outline_format_in_text_lowercase_colons():
    """
    test_parse_outline_format_in_text_lowercase_colons()
    Usage: pytest -k outline_format
    """
    fp = ":".join(["9d"] * 32)
    c = parse_access(f'Access: {{"apiUrl":"https://h.example:8443/{SECRET}/","certSha256":"{fp}"}} done')
    assert c.secret_path and not c.api_token
    assert c.request_target("/access-keys") == f"/{SECRET}/access-keys"
    assert c.cert_sha256 == "9D" * 32


@pytest.mark.parametrize("text,code", [
    ("hello", "errNoJson"),
    ('{"apiUrl":"http://h:1","apiToken":"x"}', "errNotHttps"),
    ('{"apiUrl":"https://h:2053"}', "errNoSecret"),
    ('{"apiUrl":"https://h:2053","apiToken":"x","certSha256":"12"}', "errBadCert"),
])
def test_parse_errors(text, code):
    """
    test_parse_errors(text, code)
    Usage: pytest -k parse_errors
    """
    with pytest.raises(AccessError) as e:
        parse_access(text)
    assert str(e.value) == code


def test_key_from_config_and_normalize():
    """
    test_key_from_config_and_normalize()
    Usage: pytest -k key_from_config
    """
    k = key_from_config(CONF, "phone")
    assert k["ip"] == "10.66.0.9" and k["endpoint"] == "vpn.example.com:51820" and k["config"] == CONF
    n = normalize_key({"ipAddress": "10.66.0.2", "uploadBytes": 5, "downloadBytes": 7}, {"dns": "9.9.9.9"})
    assert n["total"] == 12 and n["dns"] == "9.9.9.9"


# ---- mock HTTPS server -------------------------------------------------------------------------

class Mock:
    """
    Mock
    Usage: the state of the mock wg-api (mode "new" serves /access-keys, "old" serves /usage only)
    """
    mode = "new"
    keys = []


class Handler(BaseHTTPRequestHandler):
    """
    Handler
    Usage: request handler of the mock wg-api
    """

    def log_message(self, *a):
        """
        log_message()
        Usage: silence
        """

    def _auth_path(self):
        """
        _auth_path() -> str or None
        Usage: path = self._auth_path()   # None = unauthorized; strips the secret path like server.js
        """
        p = self.path
        if p.startswith("/" + SECRET):
            return p[len(SECRET) + 1:] or "/"
        if self.headers.get("Authorization") == "Bearer " + TOKEN:
            return p
        return None

    def _send(self, code, obj, ctype="application/json"):
        """
        _send(code, obj, ctype)
        Usage: self._send(200, {...})
        """
        body = obj.encode() if isinstance(obj, str) else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        """
        do_GET()
        Usage: /access-keys, /keys, /usage
        """
        p = self._auth_path()
        if p is None:
            return self._send(401, {"error": "Unauthorized"})
        if Mock.mode == "new" and p == "/access-keys":
            return self._send(200, {"server": {"dns": "1.1.1.1"}, "count": len(Mock.keys), "accessKeys": Mock.keys})
        if p == "/usage":
            return self._send(200, {"keys": [{"ipAddress": k["ipAddress"], "uploadBytes": 1, "downloadBytes": 2} for k in Mock.keys]})
        return self._send(404, "Cannot GET", "text/html")

    def do_POST(self):
        """
        do_POST()
        Usage: /create (JSON in new mode, text in old mode), /remove
        """
        p = self._auth_path()
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if p is None:
            return self._send(401, {"error": "Unauthorized"})
        if p.startswith("/create"):
            if Mock.mode == "old":
                return self._send(200, CONF, "text/plain")
            k = {"ipAddress": "10.66.0.9", "name": body.get("name", ""), "config": CONF}
            Mock.keys.append(k)
            return self._send(200, k)
        if p == "/remove":
            Mock.keys = [k for k in Mock.keys if k["ipAddress"] != body.get("ipAddress")]
            return self._send(200, {"success": True})
        return self._send(404, "nope", "text/html")


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    """
    server(tmp_path_factory) -> (port, fingerprint)
    Usage: def test_x(server): port, fp = server
    """
    if not shutil.which("openssl"):
        pytest.skip("openssl needed")
    d = tmp_path_factory.mktemp("tls")
    cert, key = str(d / "c.pem"), str(d / "k.pem")
    subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes",
                    "-days", "2", "-keyout", key, "-out", cert, "-subj", "/CN=localhost"], check=True, capture_output=True)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    der = ssl.PEM_cert_to_DER_cert(open(cert).read())
    yield srv.server_address[1], hashlib.sha256(der).hexdigest().upper()
    srv.shutdown()


def _cfg(port, fp, outline=False, token=TOKEN):
    """
    _cfg(port, fp, outline=False, token=TOKEN) -> AccessConfig
    Usage: c = WgClient(_cfg(port, fp))
    """
    if outline:
        return parse_access(json.dumps({"apiUrl": f"https://127.0.0.1:{port}/{SECRET}", "certSha256": fp}))
    return parse_access(json.dumps({"apiUrl": f"https://127.0.0.1:{port}", "apiToken": token, "certSha256": fp}))


@pytest.fixture(autouse=True)
def reset_mock():
    """
    reset_mock()
    Usage: automatic - every test starts with two keys on a new-API server
    """
    Mock.mode = "new"
    Mock.keys = [{"ipAddress": "10.66.0.2", "name": "a", "config": CONF}, {"ipAddress": "10.66.0.3", "name": "", "config": None}]
    os.environ.pop("NO_PROXY", None)


def test_pull_token_and_outline(server):
    """
    test_pull_token_and_outline(server)
    Usage: pytest -k pull_token
    Both config formats pull every key; the certificate is verified.
    """
    port, fp = server
    for outline in (False, True):
        c = WgClient(_cfg(port, fp, outline))
        d = c.list_keys()
        assert d["route"] == "/access-keys" and len(d["keys"]) == 2 and c.verified
        assert d["keys"][0]["config"] == CONF and d["keys"][1]["config"] == ""


def test_cert_mismatch_stops_before_sending(server):
    """
    test_cert_mismatch_stops_before_sending(server)
    Usage: pytest -k mismatch
    """
    port, fp = server
    with pytest.raises(ApiError) as e:
        WgClient(_cfg(port, "0" * 64)).list_keys()
    assert e.value.code == "errCertMismatch" and e.value.got == fp


def test_bad_token(server):
    """
    test_bad_token(server)
    Usage: pytest -k bad_token
    """
    port, fp = server
    with pytest.raises(ApiError) as e:
        WgClient(_cfg(port, fp, token="b" * 64)).list_keys()
    assert e.value.code == "errUnauthorized"


def test_old_server_falls_back_to_usage_and_text_create(server):
    """
    test_old_server_falls_back_to_usage_and_text_create(server)
    Usage: pytest -k old_server
    """
    port, fp = server
    Mock.mode = "old"
    c = WgClient(_cfg(port, fp))
    d = c.list_keys()
    assert d["legacy"] and d["route"] == "/usage" and d["keys"][0]["total"] == 3
    k = c.create_key("x")
    assert k["ip"] == "10.66.0.9" and k["config"] == CONF


def test_controller_add_create_remove(server, tmp_path):
    """
    test_controller_add_create_remove(server, tmp_path)
    Usage: pytest -k controller
    """
    from mwg_core.applog import AppLog
    from mwg_core.controller import Controller
    from mwg_core.store import ServerStore, Settings
    port, fp = server
    ctl = Controller(ServerStore(tmp_path / "s.json"), Settings(tmp_path / "set.json"), AppLog(to_file=False))
    text = _cfg(port, fp).to_json()
    r = ctl.add_server("paste: " + text, "Test")
    assert r["ok"] and r["count"] == 2
    assert ctl.add_server(text)["existing"]
    sid = r["sid"]
    assert ctl.state()["server"]["verified"]
    assert ctl.create_key(sid, "phone")["ok"]
    assert len(ctl.keys(sid)["keys"]) == 3
    assert "privateKey" not in ctl.keys(sid)["keys"][0] and "config" not in ctl.keys(sid)["keys"][0]
    assert ctl.key_detail(sid, "10.66.0.9")["key"]["qr"].startswith("<svg")
    assert ctl.remove_key(sid, "10.66.0.9")["ok"] and len(ctl.keys(sid)["keys"]) == 2
    out = tmp_path / "out"
    out.mkdir()
    assert ctl.export_all(sid, str(out))["count"] == 1
    # reload from disk: the server is remembered and its access config can still be read
    ctl2 = Controller(ServerStore(tmp_path / "s.json"), Settings(tmp_path / "set.json"), AppLog(to_file=False))
    assert ctl2.access_json(sid) == text
    bad = _cfg(port, "1" * 64).to_json()
    assert ctl.add_server(bad)["error"]["code"] == "errCertMismatch"


def test_legacy_server_keeps_configs_of_keys_created_here(server, tmp_path):
    """
    test_legacy_server_keeps_configs_of_keys_created_here(server, tmp_path)
    Usage: pytest -k legacy_server_keeps
    An older server hands out a key's config only once (when it is created). The app remembers it (encrypted), so the
    key can still be copied or scanned after the next refresh and after a restart, and the log names the server.
    """
    from tests.core_import import ctl_for
    ctl, sid, port, fp = ctl_for(server, tmp_path, legacy=True)
    r = ctl.create_key(sid, "Phone")
    assert r["ok"]
    Mock.keys.append({"ipAddress": "10.66.0.9"})           # what /usage reports after the create
    ctl.refresh(sid, wait=True)
    k = next(k for k in ctl.keys(sid)["keys"] if k["ip"] == "10.66.0.9")
    assert k["hasConfig"] and k["name"] == "Phone"
    assert ctl.key_detail(sid, "10.66.0.9")["key"]["config"] == CONF
    assert any("created 10.66.0.9 (Phone) on Test (" in row["tx"] for row in ctl.log.rows())
