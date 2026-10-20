# File: core/config.py
# Constants, paths and the app version of Mithra WireGuard Manager for Windows.
# Edit with: vi core/config.py
"""
Every fixed setting lives here, so nothing is hard-coded elsewhere.

Environment variables (optional, for development and tests):
    MITHRA_WG_USER_DIR    override %LOCALAPPDATA%\\MithraWireGuard
"""
import os
import sys
from pathlib import Path

APP_NAME = "Mithra WireGuard Manager"
APP_ID = "MithraWireGuard"

# Links the app may open. The UI asks for them by NAME only (see Controller.open_link).
LINKS = {
    "about": "https://mithracorp.com",
    "support": "https://mithracorp.com",
    "installer": "https://github.com/arkh91/Arkh91_WireGuard",
}

# The server script the app points to, checked against its SHA-256 before it runs as root: if the file at
# SERVER_SCRIPT_REF is not exactly the reviewed one (main moved on, or it was tampered with), sha256sum -c refuses it.
# devtools/release.py writes the hash from server/install-wg-full.sh. A release tag ("v2.2.1") works too, once it exists.
SERVER_SCRIPT_REF = "refs/heads/main"
SERVER_SCRIPT_SHA256 = "71ecfb389a70b6c98535096c09f0dcf5f920bd054a3ee9f136a88234e1fb7625"
_SCRIPT_URL = f"https://raw.githubusercontent.com/arkh91/Arkh91_WireGuard/{SERVER_SCRIPT_REF}/install-wg-full.sh"
_FETCH = (f"curl -fsSLo install-wg-full.sh {_SCRIPT_URL} && "
          f"echo '{SERVER_SCRIPT_SHA256}  install-wg-full.sh' | sha256sum -c - && sudo bash install-wg-full.sh")

# The newest server API this app knows (server.js API_VERSION). A server reporting an older one gets the update banner,
# with what it is missing. Raise it together with the server script.
SERVER_API_LATEST = "2.3"
# what each API version added, for the banner (oldest first)
SERVER_API_ADDS = (("2.1", "pause, traffic limits"), ("2.2", "time limits"), ("2.3", "end on a date and time"))

# The server install command shown on the Add server screen.
INSTALL_COMMAND = _FETCH

# Shown when a server runs an older API: updates it in place (keys and peers stay).
UPDATE_API_COMMAND = _FETCH + " --update-api"

# Network.
HTTP_TIMEOUT = 20            # seconds for one API request
REFRESH_CHOICES = (0, 15, 30, 60, 300)   # auto refresh of the open server, seconds (0 = off)
REFRESH_DEFAULT = 30
ONLINE_WINDOW = 180          # a key whose last handshake is newer than this many seconds counts as online
SPARK_POINTS = 60            # throughput history points kept per server

# Logs.
LOG_MAX = 2000


def resource_dir() -> Path:
    """
    resource_dir() -> Path
    Usage: html = resource_dir() / "ui" / "index.html"
    Folder of the bundled files: PyInstaller's unpack folder when frozen, else the project root.
    """
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else Path(__file__).resolve().parent.parent


def app_version() -> str:
    """
    app_version() -> str
    Usage: label = "v" + app_version()
    Reads the VERSION file (one line). Falls back to 1.0.0.
    """
    try:
        return (resource_dir() / "VERSION").read_text(encoding="utf-8").strip() or "1.0.0"
    except OSError:
        return "1.0.0"


def user_dir() -> Path:
    """
    user_dir() -> Path
    Usage: path = user_dir() / "servers.json"
    Per-user data folder (servers, settings, logs). Created if missing.
    """
    env = os.environ.get("MITHRA_WG_USER_DIR")
    if env:
        p = Path(env)
    elif os.environ.get("LOCALAPPDATA"):
        p = Path(os.environ["LOCALAPPDATA"]) / APP_ID
    else:
        p = Path.home() / ".local" / "share" / APP_ID
    p.mkdir(parents=True, exist_ok=True)
    return p


def log_dir() -> Path:
    """
    log_dir() -> Path
    Usage: os.startfile(log_dir())
    Folder of the text log. Created if missing.
    """
    p = user_dir() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p
