#!/bin/bash
# =============================================================================
# wg-pull-keys.sh - pull every key from a WireGuard server using ONLY its
# access config, the same way Outline Manager uses Outline's access config.
#
# The access config is what install-wg-full.sh prints and saves in
# /etc/wg-api/access.json on the server:
#   {"apiUrl":"https://vpn.example.com:2053","apiToken":"...","certSha256":"9D13..."}
# or, in exactly Outline's format (the secret is the last part of apiUrl, no token):
#   {"apiUrl":"https://vpn.example.com:2053/Xy7secretPath","certSha256":"9D13..."}
#
# The script:
#   1. connects to apiUrl and checks the server certificate's SHA-256 against
#      certSha256 (stops if it does not match: wrong server or interception)
#   2. GETs apiUrl (with "Authorization: Bearer <apiToken>" when the config has a token)
#   3. prints every key: PrivateKey, PublicKey, DNS, Endpoint, AllowedIPs,
#      PersistentKeepalive, config, created date and usage
#
# Usage:
#   ./wg-pull-keys.sh '<access config json>'            all keys as JSON
#   ./wg-pull-keys.sh access.json                        same, config read from a file
#   echo '<json>' | ./wg-pull-keys.sh                    same, config read from stdin
#   ./wg-pull-keys.sh access.json --table                one line per key (ip, usage, last handshake)
#   ./wg-pull-keys.sh access.json --ip=10.66.0.2         one key only
#   ./wg-pull-keys.sh access.json --configs=DIR          also write each key's config to DIR/<ip>.conf
#
# Needs: bash, curl, openssl, jq.   Edit with: vi wg-pull-keys.sh
# Exit codes: 0 ok, 1 usage/config error, 2 certificate mismatch, 3 API error
# =============================================================================

set -euo pipefail

ACCESS=""
MODE="json"
ONE_IP=""
CONFIG_DIR=""

# Usage: die <code> "message"   -> prints the message to stderr and exits with <code>
die() { local c="$1"; shift; echo "ERROR: $*" >&2; exit "$c"; }

# Usage: show_help              -> prints the header of this file as help
show_help() { sed -n '2,/^# =====/p' "$0" | sed '$d; s/^# \{0,1\}//'; }

# Usage: parse_args "$@"        -> fills ACCESS, MODE, ONE_IP, CONFIG_DIR
parse_args() {
    local a
    for a in "$@"; do
        case "$a" in
            --table)      MODE="table" ;;
            --ip=*)       ONE_IP="${a#*=}" ;;
            --configs=*)  CONFIG_DIR="${a#*=}" ;;
            -h|--help)    show_help; exit 0 ;;
            -*)           die 1 "unknown option: $a (see --help)" ;;
            *)            [ -z "$ACCESS" ] || die 1 "give the access config only once"; ACCESS="$a" ;;
        esac
    done
    if [ -z "$ACCESS" ]; then
        [ -t 0 ] && die 1 "give the access config as an argument, a file or on stdin (see --help)"
        ACCESS="$(cat)"
    elif [ -f "$ACCESS" ]; then
        ACCESS="$(cat "$ACCESS")"
    fi
}

# Usage: need_tools             -> exits when curl, openssl or jq is missing
need_tools() {
    local t
    for t in curl openssl jq; do command -v "$t" >/dev/null 2>&1 || die 1 "$t is not installed"; done
}

# Usage: read_access            -> fills API_URL, API_TOKEN, CERT_SHA256, HOST, PORT from the access config
read_access() {
    echo "$ACCESS" | jq -e . >/dev/null 2>&1 || die 1 "the access config is not valid JSON"
    API_URL="$(echo "$ACCESS" | jq -r '.apiUrl // empty')"
    API_TOKEN="$(echo "$ACCESS" | jq -r '.apiToken // empty')"
    CERT_SHA256="$(echo "$ACCESS" | jq -r '.certSha256 // empty' | tr -d ':' | tr 'a-f' 'A-F')"
    [ -n "$API_URL" ]   || die 1 "apiUrl is missing in the access config"
    API_URL="${API_URL%/}"
    local hp="${API_URL#https://}"
    [ "$hp" != "$API_URL" ] || die 1 "apiUrl must start with https://"
    # Outline format: no token, the secret is the path of apiUrl
    [ -n "$API_TOKEN" ] || [[ "$hp" == */?* ]] || die 1 "the access config has neither apiToken nor a secret path in apiUrl"
    hp="${hp%%/*}"
    HOST="${hp%%:*}"
    PORT="443"
    [ "$hp" = "$HOST" ] || PORT="${hp##*:}"
}

# Usage: pin_certificate        -> checks the server certificate against certSha256 and sets CURL_TLS
#                                  (no certSha256, e.g. behind Cloudflare: normal CA verification)
pin_certificate() {
    CURL_TLS=()
    [ -n "$CERT_SHA256" ] || return 0
    local pem got
    pem="$(openssl s_client -connect "${HOST}:${PORT}" -servername "$HOST" </dev/null 2>/dev/null \
           | sed -n '/-----BEGIN CERTIFICATE-----/,/-----END CERTIFICATE-----/p' || true)"
    [ -n "$pem" ] || die 3 "could not connect to ${HOST}:${PORT} (wrong port, server down or firewall)"
    got="$(echo "$pem" | openssl x509 -noout -fingerprint -sha256 | sed 's/.*=//; s/://g')"
    [ "$got" = "$CERT_SHA256" ] || die 2 "certificate mismatch for ${HOST}:${PORT}
  expected certSha256 ${CERT_SHA256}
  server presented    ${got}
  (wrong server, a reinstall made a new certificate, or the connection is intercepted)"
    # the request below must use the very key that was just verified
    CURL_TLS=(--insecure --pinnedpubkey "sha256//$(echo "$pem" | openssl x509 -noout -pubkey \
              | openssl pkey -pubin -outform der | openssl dgst -sha256 -binary | openssl base64)")
}

# Usage: fetch_keys             -> prints the API's JSON answer: all keys, or one key with --ip
fetch_keys() {
    local url="${API_URL}/" out code
    [ -z "$ONE_IP" ] || url="${API_URL}/keys/${ONE_IP}"
    local auth=()
    [ -z "$API_TOKEN" ] || auth=(-H "Authorization: Bearer ${API_TOKEN}")
    out="$(curl -sS -m 30 "${CURL_TLS[@]}" "${auth[@]}" -w '\n%{http_code}' "$url")" \
        || die 3 "request to ${url} failed"
    code="${out##*$'\n'}"
    out="${out%$'\n'*}"
    case "$code" in
        200) ;;
        401) die 3 "the server refused the access config (401): wrong or changed token / secret URL" ;;
        404) die 3 "not found (404): no such key, or the server runs an older API (run --update-api on it)" ;;
        *)   die 3 "the server answered HTTP ${code}: ${out}" ;;
    esac
    echo "$out"
}

# Usage: write_configs <json>   -> writes DIR/<ip>.conf (mode 600) for every key whose config the server has
write_configs() {
    local json="$1" ip n=0
    mkdir -p "$CONFIG_DIR"
    while IFS= read -r ip; do
        ( umask 077; echo "$json" | jq -r --arg ip "$ip" '(.keys // [.])[] | select(.ipAddress == $ip) | .config' \
              > "${CONFIG_DIR}/${ip}.conf" )
        n=$((n + 1))
    done < <(echo "$json" | jq -r '(.keys // [.])[] | select(.config != null) | .ipAddress')
    echo "wrote ${n} config file(s) to ${CONFIG_DIR}" >&2
}

# Usage: print_table <json>     -> one line per key: ip, MB down/up, last handshake, whether the config is known
print_table() {
    echo "$1" | jq -r '
        def mb: (. / 1048576 * 10 | floor) / 10;
        (.keys // [.]) as $k
        | (if .count then "keys: \(.count)   total: \(.totals.totalBytes | mb) MB\n" else "" end),
          (["IP", "DOWN_MB", "UP_MB", "LAST_HANDSHAKE", "CONFIG"] | @tsv),
          ($k[] | [.ipAddress, (.downloadBytes | mb), (.uploadBytes | mb),
                   (.lastHandshake // "never"), (if .config then "yes" else "no" end)] | @tsv)
    ' | if command -v column >/dev/null 2>&1; then column -t -s $'\t'; else cat; fi
}

# Usage: main "$@"
main() {
    parse_args "$@"
    need_tools
    read_access
    pin_certificate
    local json
    json="$(fetch_keys)"
    [ -z "$CONFIG_DIR" ] || write_configs "$json"
    if [ "$MODE" = "table" ]; then print_table "$json"; else echo "$json" | jq .; fi
}

main "$@"