# File: devtools/release.py
# Writes the SHA-256 of server/install-wg-full.sh into mwg_core/config.py (SERVER_SCRIPT_SHA256), so the install and
# update commands the app shows only run that exact file. Run it after every change to the server script.
# Edit with: vi devtools/release.py
"""
Usage: python3 devtools/release.py
Then commit server/install-wg-full.sh to the repo as install-wg-full.sh (at config.SERVER_SCRIPT_REF, main by default)
and build the app: its install/update commands only run that exact file.
"""
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    """
    main()
    Usage: python3 devtools/release.py     # prints the tag and hash it wrote
    """
    digest = hashlib.sha256((ROOT / "server" / "install-wg-full.sh").read_bytes()).hexdigest()
    cfg = ROOT / "mwg_core" / "config.py"
    text = cfg.read_text(encoding="utf-8")
    text, n = re.subn(r'^SERVER_SCRIPT_SHA256 = "[0-9a-f]{64}"$', f'SERVER_SCRIPT_SHA256 = "{digest}"', text, flags=re.M)
    if n != 1:
        raise SystemExit("SERVER_SCRIPT_SHA256 line not found in mwg_core/config.py")
    cfg.write_text(text, encoding="utf-8")
    ref = re.search(r'^SERVER_SCRIPT_REF = "([^"]+)"$', text, re.M).group(1)
    print(f"ref {ref}\nsha256 {digest}  install-wg-full.sh")


if __name__ == "__main__":
    main()
