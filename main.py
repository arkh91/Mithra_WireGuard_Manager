# File: main.py
# Entry point of Mithra WireGuard Manager for Windows: single instance, crash log, then the window.
# Edit with: vi main.py
"""
Run (development):  python main.py
Command-line check without the window (writes the result as JSON, handy for support and for build tests):
    MithraWireGuard.exe --pull "<access config json or path to access.json>" --out result.json
No administrator rights are needed: the app only talks HTTPS to your servers.
"""
import ctypes
import faulthandler
import json
import os
import sys
from pathlib import Path

from mwg_core import config

ERROR_ALREADY_EXISTS = 183
_mutex = None


def enable_crash_log() -> None:
    """
    enable_crash_log()
    Usage: called first in main()
    A hard crash (inside native code) leaves a trace in %LOCALAPPDATA%\\MithraWireGuard\\crash.log.
    """
    try:
        handle = open(config.user_dir() / "crash.log", "a", buffering=1, encoding="utf-8", errors="replace")
        faulthandler.enable(file=handle, all_threads=True)
        sys.modules[__name__]._crash_handle = handle
    except OSError:
        pass


def single_instance() -> bool:
    """
    single_instance() -> bool
    Usage: if not single_instance(): sys.exit(0)
    A named Windows mutex: False when the app already runs for this user. Always True off Windows.
    """
    global _mutex
    if os.name != "nt":
        return True
    _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\MithraWireGuard_App")   # type: ignore[attr-defined]
    return ctypes.windll.kernel32.GetLastError() != ERROR_ALREADY_EXISTS                     # type: ignore[attr-defined]


def message_box(text: str) -> None:
    """
    message_box(text)
    Usage: message_box("Already running.")
    """
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(None, text, config.APP_NAME, 0x40)     # type: ignore[attr-defined]
    else:
        print(text)


def cli_pull(argv: list) -> int:
    """
    cli_pull(argv) -> int
    Usage: python main.py --pull '{"apiUrl": ...}' --out keys.json
    Pulls every key with one access config and writes {ok, route, count, keys} (or {ok: false, error}) as JSON.
    Exit code 0 on success, 2 on certificate mismatch, 3 on any other error.
    """
    from mwg_core.access import AccessError, parse_access
    from mwg_core.wgclient import ApiError, WgClient
    src = argv[argv.index("--pull") + 1] if len(argv) > argv.index("--pull") + 1 else ""
    out = argv[argv.index("--out") + 1] if "--out" in argv and len(argv) > argv.index("--out") + 1 else ""
    if src and os.path.isfile(src):
        src = Path(src).read_text(encoding="utf-8")
    code, result = 0, {}
    try:
        client = WgClient(parse_access(src))
        data = client.list_keys()
        result = {"ok": True, "route": data["route"], "legacy": data["legacy"], "verified": client.verified,
                  "certSha256": client.presented_fp, "count": len(data["keys"]), "server": data["server"],
                  "keys": data["keys"]}
    except AccessError as exc:
        code, result = 3, {"ok": False, "error": str(exc)}
    except ApiError as exc:
        code = 2 if exc.code == "errCertMismatch" else 3
        result = {"ok": False, "error": exc.code, "detail": exc.detail, "presented": exc.got}
    text = json.dumps(result, indent=2)
    if out:
        Path(out).write_text(text, encoding="utf-8")
    else:
        print(text)
    return code


def main() -> None:
    """
    main()
    Usage: python main.py
    """
    if "--pull" in sys.argv:
        sys.exit(cli_pull(sys.argv))
    enable_crash_log()
    if not single_instance():
        message_box(f"{config.APP_NAME} is already running.")
        return

    from mwg_core.controller import Controller
    try:
        from mwg_gui.window import run
    except ImportError as exc:                       # Qt could not be loaded: say so instead of closing silently
        message_box(f"{config.APP_NAME} could not start its window:\n\n{exc}\n\nDetails: {config.user_dir() / 'crash.log'}")
        raise

    ctl = Controller()
    ctl.start()
    code = run(ctl)
    ctl.shutdown()
    os._exit(code)


if __name__ == "__main__":
    main()
