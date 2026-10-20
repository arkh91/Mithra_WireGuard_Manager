<!-- File: README.md  -  Edit with: vi README.md -->
# Mithra WireGuard Manager

A Windows app for the WireGuard servers installed with `install-wg-full.sh`, made to work like Outline Manager:
paste a server's access config, press **Done**, and every key is listed with its usage, last handshake and config.
You can add, rename and remove keys, show a key's QR code for the WireGuard phone app, save a `.conf` file, or
export every config of a server at once.

## 1. Update the server (once per server)

The app already works with servers on the previous API (it reads `/access-keys` or `/keys`, and falls back to
`/usage` on very old ones). To get the Outline-style routes as well, update the API; keys and peers are untouched:

    curl -fsSLo install-wg-full.sh https://raw.githubusercontent.com/arkh91/Arkh91_WireGuard/refs/heads/main/install-wg-full.sh
    sha256sum install-wg-full.sh        # must match the release notes / the command the app shows
    sudo bash install-wg-full.sh --update-api

`--update-api` also moves the server to the new firewall (clients isolated from each other and from private and
cloud-metadata networks, suspensions always applied first) and sends IPv6 into the tunnel. Devices that imported a
key before the update should re-import its config once.

It prints both access configs. They are also saved on the server:

    sudo cat /etc/wg-api/access.json            {"apiUrl":"https://host:2053","apiToken":"...","certSha256":"..."}
    sudo cat /etc/wg-api/access-outline.json    {"apiUrl":"https://host:2053/<secret>","certSha256":"..."}

The second one is exactly Outline's format: the secret is the last part of `apiUrl`, and
`GET <apiUrl>/access-keys` returns every key with no header.

When a server runs an older API than this app knows (`SERVER_API_LATEST` in `mwg_core/config.py`, now 2.2), its page
shows a red banner with the server's API version, what the update adds, and this command with a **Copy** button.

## 2. Add the server in the app

Install `Mithra_WireGuard_Manager_Setup_1.3.5.exe`, open the app, choose **Add server**, paste either access config (extra
text around it is fine) and press **Done**. The app connects, checks the certificate and pulls the keys before it
saves anything.

## Certificate check (certSha256)

Like Outline Manager, the app hashes the certificate the server presents (SHA-256 of the DER bytes, what
`openssl x509 -fingerprint -sha256` prints) and compares it with `certSha256` before it sends the token. On a
mismatch it stops and shows both fingerprints. If a reinstall gave the server a new certificate, use
**Replace access config** on that server. Without `certSha256` (a Let's Encrypt certificate) the normal Windows
CA check is used.

## Pause and traffic limits (API 2.1)

Each key row has a **pause** button (a paused key stays configured but no traffic passes) and the pencil opens
**Edit key** with the name and a **traffic limit** such as `20G`, `500M` or `1.5T` (empty = unlimited). The limit
counts upload + download since the key was created; a key that reaches it is blocked (red **Limit reached**) until the
limit is raised or removed. The **Paused** filter lists paused and over-limit keys. Servers on API 2.0 show a banner
with the update command instead of these buttons.

## Time limits (API 2.2, End on: API 2.3)

**Add key** and **Edit key** have a **Time limit** with four choices: *No time limit*; *Ends on a date and time (server time)*;
*Ends after N hours / days / weeks / months / years from now*; or *Ends after … from the first connection* (the clock starts
when the key first connects). *Ends on* takes a date (`2026-12-31`) and a time (`18:00`) on the **server's clock**, in the
server's time zone; the dialog shows the server's current time. A date in the past is refused.
Months are calendar months (Jan 31 + 1 month = Feb 28). Each row shows the time left (gold in the last 3 days), the
pending duration ("1 month from 1st use"), or a red **Expired** badge. An expired key is blocked until it gets a new
time limit or none; **Edit key** shows the current end and starts on *Keep as it is*. Expired keys are listed under
**Paused**.

## API routes (server.js, API 2.3)

| Route | What it does |
|---|---|
| `GET /` and `GET /keys` | every key: `{server, count, totals, keys:[...]}` |
| `GET /access-keys` | the same list as `accessKeys` (Outline's name) |
| `GET /keys/<ip>` | one key |
| `POST /create?format=json` or `POST /access-keys` | new key, body `{"name": "..."}` (201 for `/access-keys`) |
| `POST /remove` `{"ipAddress": ip}` or `DELETE /access-keys/<ip>` | remove a key (204 for `DELETE`) |
| `PUT /access-keys/<ip>/name` | rename, body `{"name": "..."}` |
| `POST /create` with `{"ipAddress": "10.66.0.2", "traffic": "20G", "expires": "30d"}` | new key at a chosen address with a traffic and time limit (all optional) |
| `POST /keys/<ip>/pause`, `POST /keys/<ip>/resume` | pause / resume a key (also `PUT /keys/<ip>/paused {"paused": true}`) |
| `PUT /keys/<ip>/expiry {"expires": "30d"}`, `{"expiresOn": "2026-12-31 18:00"}` (server time) or `{"expiresAfterFirstConnection": "1m"}`, `DELETE /keys/<ip>/expiry` | time limit from now, on a date and time of the server's clock, or from the first connection; `"never"` removes it |
| `PUT /keys/<ip>/limit {"traffic": "20G"}`, `DELETE /keys/<ip>/limit` | set / remove the traffic limit (`"unlimited"` works too; Outline's `PUT /access-keys/<ip>/data-limit {"limit":{"bytes":N}}` as well) |
| `GET /server` | public server facts, `apiVersion`, key count |
| `GET /metrics/transfer` | `{bytesTransferredByUserId: {ip: bytes}}` |
| `GET /usage[/<ip>]` | upload, download, last handshake |
| `GET /health` | public, and also under the secret path |

Each key's first connection and last handshake are kept on the server for every key (across restarts) and shown in
the key window; removing a key deletes its usage and handshakes too.

Each key carries `privateKey, publicKey, address, dns, endpoint, allowedIPs, persistentKeepalive, createdAt,
uploadBytes, downloadBytes, totalBytes, lastHandshake, name, paused, dataLimitBytes, limitReached, expiresAt, expiresAfterFirstConnection, firstConnectedAt, expired, status`
and a ready `config` (null for keys whose private key
the server never saw).

## Where the app keeps things

`%LOCALAPPDATA%\MithraWireGuard\` - `servers.json` (access configs encrypted with DPAPI for your Windows account),
`settings.json`, `logs\app.log`. Tokens, secret paths and private keys are never written to the log.
