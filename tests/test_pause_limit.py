# File: tests/test_pause_limit.py
# Pause/resume and traffic limits: the parser, and the controller against the REAL server.js (devtools/test_server.py).
# Edit with: vi tests/test_pause_limit.py
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from mwg_core.limits import limit_text, parse_traffic

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("text,value", [
    ("20G", 20_000_000_000), ("20 GB", 20_000_000_000), ("500m", 500_000_000), ("1.5T", 1_500_000_000_000),
    ("1,5G", 1_500_000_000), ("2GiB", 2 * 1024 ** 3), ("12345", 12345), ("", 0), ("unlimited", 0), ("0", 0),
    ("نامحدود", 0), (None, 0), ("lots", None), ("-5G", None), ("20X", None), ("2" * 30, None),
])
def test_parse_traffic(text, value):
    """
    test_parse_traffic(text, value)
    Usage: pytest -k parse_traffic
    """
    assert parse_traffic(text) == value


@pytest.mark.parametrize("n", [0, 20_000_000_000, 1_500_000_000_000, 500_000_000, 12345, 2 * 1024 ** 3])
def test_limit_text_round_trip(n):
    """
    test_limit_text_round_trip(n)
    Usage: pytest -k round_trip     # what the edit field shows reads back as the same number
    """
    assert parse_traffic(limit_text(n)) == n


def _free_port() -> int:
    """
    _free_port() -> int
    Usage: port = _free_port()
    """
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def real_api(tmp_path_factory):
    """
    real_api(tmp_path_factory) -> access config text
    Usage: def test_x(real_api): ctl.add_server(real_api)
    Starts devtools/test_server.py (real server.js, fake helper) on a free port; skipped without node/npm.
    """
    if not (shutil.which("node") and shutil.which("npm") and shutil.which("openssl")):
        pytest.skip("node, npm and openssl are needed")
    d = tmp_path_factory.mktemp("api")
    port, internal = _free_port(), _free_port()
    env = dict(os.environ, NO_PROXY="localhost,127.0.0.1", no_proxy="localhost,127.0.0.1")
    p = subprocess.Popen([sys.executable, str(ROOT / "devtools" / "test_server.py"), "--port", str(port), "--internal",
                          str(internal), "--keys", "4", "--dir", str(d)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, env=env)
    cfg = ""
    t0 = time.time()
    while time.time() - t0 < 180:
        line = p.stdout.readline()
        if line.startswith("TOKEN"):
            cfg = line.split(None, 1)[1].strip()
        if "wg-api listening" in line and cfg:
            break
        if p.poll() is not None:
            break
    if not cfg:
        p.kill()
        pytest.skip("test server did not start")
    yield cfg
    p.terminate()
    p.wait(10)


def test_pause_resume_and_limits_on_real_api(real_api, tmp_path):
    """
    test_pause_resume_and_limits_on_real_api(real_api, tmp_path)
    Usage: pytest -k real_api
    """
    from tests.core_paths import make
    ctl = make(tmp_path)
    r = ctl.add_server(real_api, "Real")
    assert r["ok"], r
    sid = r["sid"]
    assert {"pause", "limit"} <= set(ctl.features(sid))
    assert ctl.state()["server"]["paused"] == 2                 # the fake server starts with one paused, one expired key

    r = ctl.create_key(sid, "Phone", "20G")
    assert r["ok"], r
    ip = r["result"]["ip"]
    k = next(k for k in ctl.keys(sid)["keys"] if k["ip"] == ip)
    assert k["limit"] == 20_000_000_000 and not k["paused"] and not k["limitReached"]

    assert ctl.set_paused(sid, ip, True)["ok"]
    assert next(k for k in ctl.keys(sid)["keys"] if k["ip"] == ip)["paused"]
    assert ctl.set_paused(sid, ip, False)["ok"]
    assert not next(k for k in ctl.keys(sid)["keys"] if k["ip"] == ip)["paused"]

    assert ctl.edit_key(sid, ip, "Phone 2", "1K")["ok"]         # below its usage once traffic flows
    k = next(k for k in ctl.keys(sid)["keys"] if k["ip"] == ip)
    assert k["name"] == "Phone 2" and k["limit"] == 1000
    assert ctl.edit_key(sid, ip, "Phone 2", "")["ok"]           # unlimited
    assert next(k for k in ctl.keys(sid)["keys"] if k["ip"] == ip)["limit"] == 0

    assert ctl.edit_key(sid, ip, "Phone 2", "lots")["error"]["code"] == "errBadTraffic"
    assert ctl.create_key(sid, "x", "20X")["error"]["code"] == "errBadTraffic"
    assert ctl.set_paused(sid, "10.66.0.250", True)["error"]["code"] == "errNoKey"


def test_old_api_has_no_pause(tmp_path):
    """
    test_old_api_has_no_pause(tmp_path)
    Usage: pytest -k old_api_has_no_pause    # a server without the features list: pause/limit refused locally
    """
    from tests.core_paths import make
    ctl = make(tmp_path)
    ctl.servers["x"] = type("S", (), {"server": {}})()
    assert ctl.set_paused("x", "10.66.0.2", True)["error"]["code"] == "errOldApi"
    assert ctl.create_key("x", "a", "20G")["error"]["code"] == "errOldApi"


def test_config_commands_are_pinned():
    """
    test_config_commands_are_pinned()
    Usage: pytest -k pinned     # the commands the app shows run one tagged file after checking its SHA-256
    """
    from mwg_core import config
    assert "sha256sum -c" in config.INSTALL_COMMAND and config.SERVER_SCRIPT_SHA256 in config.UPDATE_API_COMMAND
    assert config.SERVER_SCRIPT_SHA256 != "0" * 64 and config.SERVER_SCRIPT_REF in config.UPDATE_API_COMMAND
    assert json.dumps(config.UPDATE_API_COMMAND)


@pytest.mark.parametrize("text,value", [
    ("30d", "30d"), ("30 days", "30d"), ("1 month", "1m"), ("2 months", "2m"), ("1mo", "1m"), ("2w", "2w"),
    ("12h", "12h"), (30, "30d"), ("never", ""), ("", ""), (None, ""), ("0d", None), ("5 minutes", None), ("soon", None),
    ("99999d", None), ("1y", "12m"), ("2 years", "24m"), ("1 yr", "12m"), ("834y", None), ("6 hours", "6h"),
])
def test_parse_duration(text, value):
    """
    test_parse_duration(text, value)
    Usage: pytest -k parse_duration     # same rules as the server's parseDuration
    """
    from mwg_core.limits import parse_duration
    assert parse_duration(text) == value


def test_expiry_state():
    """
    test_expiry_state()
    Usage: pytest -k expiry_state
    """
    from mwg_core.limits import expiry_state
    now = 1_790_000_000
    assert expiry_state({}, now) is None
    assert expiry_state({"expiresAfter": "1m"}, now) == ("pending", "1m")
    assert expiry_state({"expiresAt": "2027-01-15T08:00:00.000Z"}, now)[0] == "ends"
    assert expiry_state({"expiresAt": "2020-01-01T00:00:00.000Z"}, now)[0] == "expired"
    assert expiry_state({"expired": True, "expiresAt": "2099-01-01T00:00:00Z"}, now)[0] == "expired"


def test_time_limits_on_real_api(real_api, tmp_path):
    """
    test_time_limits_on_real_api(real_api, tmp_path)
    Usage: pytest -k time_limits    # create with a time limit, change it, remove it; bad values refused locally
    """
    from tests.core_paths import make
    ctl = make(tmp_path)
    sid = ctl.add_server(real_api, "Real")["sid"]
    assert "expiry" in ctl.features(sid)
    r = ctl.create_key(sid, "Phone", "", ("first", "1 month"))
    assert r["ok"], r
    ip = r["result"]["ip"]
    k = next(k for k in ctl.servers[sid].keys if k["ip"] == ip)
    assert k["expiresAfter"] == "1m" and not k["expiresAt"] and not k["expired"]
    assert ctl.edit_key(sid, ip, "Phone", "", ("now", "30d"))["ok"]
    k = next(k for k in ctl.servers[sid].keys if k["ip"] == ip)
    assert k["expiresAt"] and not k["expiresAfter"]
    assert ctl.edit_key(sid, ip, "Phone", "", None)["ok"]                 # keep
    assert next(k for k in ctl.servers[sid].keys if k["ip"] == ip)["expiresAt"] == k["expiresAt"]
    assert ctl.edit_key(sid, ip, "Phone", "", ("none",))["ok"]
    assert not next(k for k in ctl.servers[sid].keys if k["ip"] == ip)["expiresAt"]
    assert ctl.edit_key(sid, ip, "Phone", "", ("now", "soon"))["error"]["code"] == "errBadDuration"
    # the sample data has an expired key (10.66.0.3) and one waiting for its first connection (10.66.0.4)
    keys = {k["ip"]: k for k in ctl.servers[sid].keys}
    assert keys["10.66.0.3"]["expired"] and keys["10.66.0.4"]["expiresAfter"] == "1m"
    assert ctl.state()["server"]["paused"] >= 2


def test_end_on_parsing():
    """
    test_end_on_parsing()
    Usage: pytest -k end_on_parsing     # "End on" dates: real dates only, a date alone = end of that day
    """
    from mwg_core.limits import expiry_body, parse_end_on, parse_utc_offset, server_now
    assert parse_end_on("2026-12-31 18:00") == "2026-12-31 18:00"
    assert parse_end_on("2026-12-31T08:05") == "2026-12-31 08:05"
    assert parse_end_on("2026-12-31 8:05") == "2026-12-31 08:05"
    assert parse_end_on("2026-12-31") == "2026-12-31 23:59"
    for bad in ("2026-02-30 10:00", "2026-13-01 10:00", "2026-12-31 24:00", "2026-12-31 10:60", "soon", "", None, "31-12-2026"):
        assert parse_end_on(bad) is None, bad
    assert expiry_body("on", "2026-12-31 18:00") == {"expiresOn": "2026-12-31 18:00"}
    assert parse_utc_offset("-07:00") == -420 and parse_utc_offset("+03:30") == 210 and parse_utc_offset("x") is None
    import datetime
    assert server_now(-420, 0) == datetime.datetime(1969, 12, 31, 17, 0)


def test_end_on_on_real_api(real_api, tmp_path):
    """
    test_end_on_on_real_api(real_api, tmp_path)
    Usage: pytest -k end_on_on_real    # create / change / remove an "End on" time limit; bad and past dates are refused
    """
    import datetime
    from tests.core_paths import make
    ctl = make(tmp_path)
    sid = ctl.add_server(real_api, "Real")["sid"]
    assert "expiryOn" in ctl.features(sid)
    soon = (datetime.datetime.now() + datetime.timedelta(days=3)).strftime("%Y-%m-%d %H:%M")
    r = ctl.create_key(sid, "Phone", "", ("on", soon))
    assert r["ok"], r
    ip = r["result"]["ip"]
    k = next(k for k in ctl.servers[sid].keys if k["ip"] == ip)
    assert k["expiresAt"] and k["expiresAtServer"] == soon and not k["expired"]
    later = (datetime.datetime.now() + datetime.timedelta(days=9)).strftime("%Y-%m-%d") + " 18:00"
    assert ctl.edit_key(sid, ip, "Phone", "", ("on", later))["ok"]
    assert next(k for k in ctl.servers[sid].keys if k["ip"] == ip)["expiresAtServer"] == later
    assert ctl.edit_key(sid, ip, "Phone", "", ("on", "2020-01-01 10:00"))["ok"] is False      # past: the server refuses
    assert next(k for k in ctl.servers[sid].keys if k["ip"] == ip)["expiresAtServer"] == later   # unchanged
    assert ctl.edit_key(sid, ip, "Phone", "", ("on", "2030-02-30 10:00"))["error"]["code"] == "errBadEndOn"
    assert ctl.edit_key(sid, ip, "Phone", "", ("none",))["ok"]
    assert not next(k for k in ctl.servers[sid].keys if k["ip"] == ip)["expiresAt"]
    srv = ctl.state()["server"]
    assert isinstance(srv["serverOffset"], int) and srv["serverZone"]


def test_end_on_needs_new_api(tmp_path):
    """
    test_end_on_needs_new_api(tmp_path)
    Usage: pytest -k end_on_needs_new     # a 2.2 server (no "expiryOn" feature) gets the update hint, not a request
    """
    from mwg_core.controller import ServerState
    from tests.core_paths import make
    ctl = make(tmp_path)
    st = ServerState("x", "T", "")
    st.status, st.server = "ok", {"apiVersion": "2.2", "features": ["names", "pause", "limit", "createAt", "expiry"]}
    ctl.servers = {"x": st}
    body, err = ctl._expiry("x", ("on", "2030-01-01 10:00"))
    assert body is None and err == {"code": "errOldApi"}
    st.server["features"].append("expiryOn")
    body, err = ctl._expiry("x", ("on", "2030-01-01 10:00"))
    assert body == {"expiresOn": "2030-01-01 10:00"} and err is None


def test_cache_forgets_keys_removed_elsewhere(tmp_path):
    """
    test_cache_forgets_keys_removed_elsewhere(tmp_path)
    Usage: pytest -k removed_elsewhere   # a key gone from the server loses its remembered config on the next pull
    """
    from mwg_core.wgclient import WgClient
    from tests.core_paths import make
    ctl = make(tmp_path)
    from mwg_core.controller import ServerState
    st = ServerState("x", "T", "")
    ctl.servers["x"] = st
    ctl.cache.put("x", "10.66.0.5", "old", "[Interface]\nPrivateKey = OLD\nAddress = 10.66.0.5/32\n")
    ctl.cache._data["x"]["10.66.0.5"]["t"] = 1                     # remembered long ago
    ctl.cache.put("x", "10.66.0.6", "kept", "[Interface]\nPrivateKey = KEEP\nAddress = 10.66.0.6/32\n")
    keys = [{"ip": "10.66.0.6", "config": "", "up": 0, "down": 0, "total": 0}]
    client = WgClient.__new__(WgClient)
    client.verified, client.presented_fp = True, ""
    ctl._apply(st, {"keys": keys, "fetched": 1.0}, client)
    assert set(ctl.cache.get("x")) == {"10.66.0.6"}
    assert any("10.66.0.5 is no longer on" in r["tx"] for r in ctl.log.rows())


@pytest.mark.parametrize("version,missing", [
    ("2.3", []), ("2.4", []), ("2.10", []), ("2.2", ["end on a date and time"]),
    ("2.1", ["time limits", "end on a date and time"]),
    ("2.0", ["pause, traffic limits", "time limits", "end on a date and time"]),
    ("", ["pause, traffic limits", "time limits", "end on a date and time"]),
    (None, ["pause, traffic limits", "time limits", "end on a date and time"]),
])
def test_api_behind(version, missing):
    """
    test_api_behind(version, missing)
    Usage: pytest -k api_behind     # the update banner: what an older server API misses
    """
    from mwg_core.controller import api_behind
    assert api_behind(version) == missing


def test_banner_for_older_api(tmp_path):
    """
    test_banner_for_older_api(tmp_path)
    Usage: pytest -k banner_for_older     # state() carries apiBehind for a 2.1 / 2.2 server, nothing for 2.3
    """
    from mwg_core.controller import ServerState
    from tests.core_paths import make
    ctl = make(tmp_path)
    for v, want in (("2.1", ["time limits", "end on a date and time"]), ("2.2", ["end on a date and time"]), ("2.3", [])):
        st = ServerState("x", "T", "")
        st.status, st.server = "ok", {"apiVersion": v}
        ctl.servers = {"x": st}
        ctl.order, ctl.selected = ["x"], "x"
        assert ctl.state()["server"]["apiBehind"] == want


def test_duration_words():
    """
    test_duration_words()
    Usage: pytest -k duration_words     # how durations read in the Time limit column and dialog
    """
    from mwg_gui.strings import tr
    assert tr("en", "durText", 12, "m") == "1 year" and tr("en", "durText", 24, "m") == "2 years"
    assert tr("en", "durText", 1, "m") == "1 month" and tr("en", "durText", 6, "h") == "6 hours"
    assert tr("fa", "durText", 12, "m") == "1 سال"
