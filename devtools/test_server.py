# File: devtools/test_server.py
# Runs the REAL wg-api (server.js taken from server/install-wg-full.sh) on this machine behind HTTPS with a
# self-signed certificate, with fake `wg`, `sudo` and wg-api-helper, so the app can be tested without a VPS.
# Edit with: vi devtools/test_server.py
"""
Usage (Linux/macOS with node, npm and openssl):
    python3 devtools/test_server.py [--port 9443] [--keys 5] [--dir /tmp/wgtest]
It prints both access configs (token format and Outline format) and keeps running until Ctrl+C.
The fake helper keeps its peers in <dir>/db.json and makes up traffic so usage changes on every pull.
"""
import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "t" * 64
SECRET = "TestSecretPath_0123456789"

FAKE_WG = r'''#!/usr/bin/env python3
# fake wg: genkey / pubkey only (test use)
import base64, hashlib, os, sys
if sys.argv[1:2] == ["genkey"]:
    print(base64.b64encode(os.urandom(32)).decode())
elif sys.argv[1:2] == ["pubkey"]:
    print(base64.b64encode(hashlib.sha256(sys.stdin.read().strip().encode()).digest()).decode())
'''

FAKE_SUDO = '#!/bin/sh\n# fake sudo: drop -n and run the command (test use)\n[ "$1" = "-n" ] && shift\nexec "$@"\n'

FAKE_HELPER = r'''#!/usr/bin/env python3
# fake wg-api-helper with the same commands and output format as the real one (test use)
import json, os, random, sys, time, base64, hashlib
DB = os.environ["WG_FAKE_DB"]
def load():
    try: return json.load(open(DB))
    except Exception: return {"peers": []}
def save(d): json.dump(d, open(DB, "w"))
def fail(m): sys.stderr.write("ERROR: " + m + "\n"); sys.exit(1)
UNIT = {"h": 3600, "d": 86400, "w": 604800, "m": 30 * 86400}     # months ~30 days in this fake
def dur_ok(x): return len(x) >= 2 and x[:-1].isdigit() and 0 < int(x[:-1]) < 10000 and x[-1] in UNIT
def set_exp(p, spec):
    if spec == "0": p.update(exp=0, dur=""); return
    kind, _, v = spec.partition(":")
    if kind == "at" and v.isdigit() and len(v) >= 9: p.update(exp=int(v), dur="")
    elif kind == "on" and len(v) >= 16:
        try: e = int(time.mktime(time.strptime(v.replace("T", " ")[:16], "%Y-%m-%d %H:%M")))
        except ValueError: fail("invalid expiry")
        if e <= now: fail("end time is in the past")
        p.update(exp=e, dur="")
    elif kind == "in" and dur_ok(v): p.update(exp=now + int(v[:-1]) * UNIT[v[-1]], dur="")
    elif kind == "after" and dur_ok(v): p.update(exp=0, dur=v)
    else: fail("invalid expiry")
def tick_exp(p):
    if p["hs"] and not p.get("first"):          # first connection, recorded for every key (like the real helper)
        p["first"] = p["hs"]
    if p.get("dur") and p.get("first") and not p.get("exp"):
        p["exp"] = p["first"] + int(p["dur"][:-1]) * UNIT[p["dur"][-1]]
d = load(); a = sys.argv[1:]; now = int(time.time())
for p in d["peers"]:                       # traffic grows a little on every call (not while blocked)
    blocked = p.get("paused") or (p.get("limit") and p["rx"] + p["tx"] >= p["limit"]) or (p.get("exp") and now >= p["exp"])
    if p.get("active") and not blocked:
        p["rx"] += random.randint(20000, 400000); p["tx"] += random.randint(100000, 3000000); p["hs"] = now - random.randint(1, 90)
cmd = a[0] if a else ""
if cmd == "used-ips":
    print("\n".join(p["ip"] for p in d["peers"]))
elif cmd == "add-auto":
    pub = a[1]; name = a[2] if len(a) > 2 else ""; want = a[3] if len(a) > 3 else ""; limit = a[4] if len(a) > 4 else ""
    exp = a[5] if len(a) > 5 else ""
    priv = sys.stdin.readline().strip()
    used = {p["ip"] for p in d["peers"]}
    if limit and not limit.isdigit(): fail("invalid limit")
    if want:
        if not want.startswith("10.66.0.") or want in ("10.66.0.0", "10.66.0.1", "10.66.0.255"): fail("invalid ip")
        if want in used: fail("ip already allocated: " + want)
        ip = want
    else:
        ip = next(("10.66.0.%d" % i for i in range(2, 255) if "10.66.0.%d" % i not in used), None)
    if not ip: fail("IP pool exhausted")
    d["peers"].append({"ip": ip, "pub": pub, "priv": priv or "-", "created": now, "rx": 0, "tx": 0, "hs": 0, "name": name,
                       "active": False, "paused": 0, "limit": int(limit or 0)})
    if exp: set_exp(d["peers"][-1], exp)
    print(ip)
elif cmd == "expiry":
    p = next((p for p in d["peers"] if p["ip"] == a[1]), None)
    if not p: fail("no peer found with AllowedIPs %s/32" % a[1])
    set_exp(p, a[2]); print("OK")
elif cmd in ("pause", "resume", "limit"):
    p = next((p for p in d["peers"] if p["ip"] == a[1]), None)
    if not p: fail("no peer found with AllowedIPs %s/32" % a[1])
    if cmd == "limit":
        if not a[2].isdigit(): fail("invalid limit")
        p["limit"] = int(a[2])
    else:
        p["paused"] = 1 if cmd == "pause" else 0
    print("OK")
elif cmd == "keys":
    want = a[1] if len(a) > 1 else ""
    for p in d["peers"]:
        if want and p["ip"] != want: continue
        lim = p.get("limit", 0); over = 1 if lim and p["rx"] + p["tx"] >= lim else 0
        tick_exp(p); expd = 1 if p.get("exp") and now >= p["exp"] else 0
        print("\t".join(str(x) for x in (p["ip"], p["pub"], p["priv"], p["created"], p["rx"], p["tx"], p["hs"], p["name"],
                                          p.get("paused", 0), lim, over, p.get("exp", 0), p.get("dur") or "-",
                                          p.get("first", 0), expd)))
elif cmd == "usage":
    want = a[1] if len(a) > 1 else ""
    for p in d["peers"]:
        if want and p["ip"] != want: continue
        print("%s\t%d\t%d\t%d" % (p["ip"], p["rx"], p["tx"], p["hs"]))
elif cmd == "remove":
    n = len(d["peers"]); d["peers"] = [p for p in d["peers"] if p["ip"] != a[1]]
    if len(d["peers"]) == n: fail("no peer found with AllowedIPs %s/32" % a[1])
    print("OK")
elif cmd == "rename":
    for p in d["peers"]:
        if p["ip"] == a[1]: p["name"] = a[2]; break
    else: fail("no peer found with AllowedIPs %s/32" % a[1])
    print("OK")
else:
    fail("command not permitted")
save(d)
'''

FRONT_JS = r'''// TLS front like Caddy: https://127.0.0.1:PORT -> http://127.0.0.1:INTERNAL (test use)
const https = require('https'), http = require('http'), fs = require('fs');
const [cert, key, port, internal] = process.argv.slice(2);
https.createServer({ cert: fs.readFileSync(cert), key: fs.readFileSync(key) }, (req, res) => {
  const up = http.request({ host: '127.0.0.1', port: +internal, path: req.url, method: req.method, headers: req.headers }, (r) => {
    res.writeHead(r.statusCode, r.headers); r.pipe(res);
  });
  up.on('error', () => { res.writeHead(502); res.end(); });
  req.pipe(up);
}).listen(+port, '127.0.0.1', () => console.log('front on', port));
'''

NAMES = ["Ali phone", "Office laptop", "Sara iPad", "", "Router", "Mom", "Guest", "", "Tablet", "TV box"]


def extract_server_js() -> str:
    """
    extract_server_js() -> str
    Usage: js = extract_server_js()    # the server.js heredoc from server/install-wg-full.sh
    """
    text = (ROOT / "server" / "install-wg-full.sh").read_text(encoding="utf-8")
    m = re.search(r"cat > \"\$\{API_DIR\}/server\.js\" <<'SERVER_JS_EOF'\n(.*?)\nSERVER_JS_EOF\n", text, re.S)
    if not m:
        sys.exit("server.js block not found in install-wg-full.sh")
    return m.group(1)


def main() -> None:
    """
    main()
    Usage: python3 devtools/test_server.py --port 9443 --keys 6
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9443)
    ap.add_argument("--internal", type=int, default=14242)
    ap.add_argument("--keys", type=int, default=6)
    ap.add_argument("--dir", default="/tmp/wgtest")
    ap.add_argument("--host", default="localhost", help="name in the certificate and in apiUrl")
    ap.add_argument("--helper", default="", help="use this wg-api-helper instead of the fake one (e.g. the real one)")
    args = ap.parse_args()

    d = Path(args.dir)
    d.mkdir(parents=True, exist_ok=True)
    (d / "bin").mkdir(exist_ok=True)
    for name, body in (("wg", FAKE_WG), ("sudo", FAKE_SUDO), ("wg-api-helper", FAKE_HELPER)):
        (d / "bin" / name).write_text(body)
        os.chmod(d / "bin" / name, 0o755)
    (d / "front.js").write_text(FRONT_JS)

    js = extract_server_js()
    js = (js.replace("__SERVER_PUB__", "SrvPubKeyTest000000000000000000000000000000=")
            .replace("__ENDPOINT__", "vpn.example.com").replace("__WG_PORT__", "51820")
            .replace("__DNS__", "1.1.1.1").replace("__API_PORT__", str(args.internal)))
    (d / "server.js").write_text(js)
    if not (d / "node_modules" / "express").exists():
        subprocess.run(["npm", "init", "-y"], cwd=d, check=True, stdout=subprocess.DEVNULL)
        pkgs = re.search(r"NPM_PACKAGES=\(([^)]*)\)", (ROOT / "server" / "install-wg-full.sh").read_text()).group(1).split()
        subprocess.run(["npm", "install", "--no-audit", "--no-fund", "--ignore-scripts", *pkgs],
                       cwd=d, check=True, stdout=subprocess.DEVNULL)

    cert, key = d / "cert.pem", d / "key.pem"
    if not cert.exists():
        subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes",
                        "-sha256", "-days", "30", "-keyout", str(key), "-out", str(cert), "-subj", f"/CN={args.host}",
                        "-addext", f"subjectAltName=DNS:{args.host}"], check=True, stderr=subprocess.DEVNULL)
    fp = subprocess.run(["openssl", "x509", "-in", str(cert), "-noout", "-fingerprint", "-sha256"], capture_output=True,
                        text=True, check=True).stdout.split("=", 1)[1].strip().replace(":", "")

    db = d / "db.json"
    if not db.exists():
        now = int(time.time())
        peers = []
        for i in range(args.keys):
            priv = "cHJpdmF0ZWtleS0lMDJkLXRlc3QtMDAwMDAwMDAwMDA9".replace("JTAy", "%02d" % i)[:43] + "="
            peers.append({"ip": f"10.66.0.{i + 2}", "pub": f"PubKey{i:02d}" + "A" * 35 + "=", "priv": priv if i % 5 != 4 else "-",
                          "created": now - 86400 * (i + 1), "rx": (i + 1) * 3_100_000, "tx": (i + 1) * 41_000_000,
                          "hs": now - 30 if i % 3 != 2 else 0, "name": NAMES[i % len(NAMES)], "active": i % 3 != 2,
                          "paused": 1 if i == 3 else 0, "limit": 50_000_000_000 if i % 2 == 0 else 0,
                          "exp": {0: now + 29 * 86400, 1: now - 3600, 4: now + 5 * 3600}.get(i, 0),
                          "dur": "1m" if i == 2 else "", "first": 0})
        db.write_text(json.dumps({"peers": peers}))

    env = dict(os.environ, PATH=f"{d / 'bin'}:{os.environ['PATH']}", WG_FAKE_DB=str(db), API_TOKEN=TOKEN,
               API_PATH=SECRET, WG_API_HELPER=args.helper or str(d / "bin" / "wg-api-helper"))
    api = subprocess.Popen(["node", "server.js"], cwd=d, env=env)
    front = subprocess.Popen(["node", "front.js", str(cert), str(key), str(args.port), str(args.internal)], cwd=d)
    base = f"https://{args.host}:{args.port}"
    token_cfg = json.dumps({"apiUrl": base, "apiToken": TOKEN, "certSha256": fp}, separators=(",", ":"))
    outline_cfg = json.dumps({"apiUrl": f"{base}/{SECRET}", "certSha256": fp}, separators=(",", ":"))
    (d / "access.json").write_text(token_cfg)
    (d / "access-outline.json").write_text(outline_cfg)
    print("TOKEN  ", token_cfg)
    print("OUTLINE", outline_cfg, flush=True)

    def stop(*_):
        """
        stop()
        Usage: signal handler - stops both node processes
        """
        api.terminate()
        front.terminate()
        sys.exit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while api.poll() is None and front.poll() is None:
        time.sleep(0.5)
    stop()


if __name__ == "__main__":
    if not shutil.which("node"):
        sys.exit("node is needed")
    main()
