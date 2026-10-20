# File: mwg_gui/util.py
# Formatting helpers (bytes, speeds, ages) and a tiny background-work helper so the window never freezes.
# Edit with: vi mwg_gui/util.py
import sys
import threading

from PySide6.QtCore import QObject, Signal


def fmt_bytes(n) -> str:
    """
    fmt_bytes(n) -> str
    Usage: fmt_bytes(123456789)    # "123 MB"
    """
    n = float(n or 0)
    units = ["B", "kB", "MB", "GB", "TB", "PB"]
    i = 0
    while n >= 1000 and i < len(units) - 1:
        n /= 1000
        i += 1
    if i == 0:
        return f"{int(n)} B"
    return f"{n:.0f}" + f" {units[i]}" if n >= 100 else (f"{n:.1f}" if n >= 10 else f"{n:.2f}") + f" {units[i]}"


def fmt_rate(bps) -> str:
    """
    fmt_rate(bps) -> str
    Usage: fmt_rate(250000)    # "250 kB/s"
    """
    return fmt_bytes(bps) + "/s"


def wrap_hard(text: str, n: int = 28) -> str:
    """
    wrap_hard(text, n=28) -> str
    Usage: label.setText(wrap_hard(public_key))      # lets a long key without spaces wrap inside a narrow label
    """
    return "\u200b".join(text[i:i + n] for i in range(0, len(text), n)) if len(text) > n else text


def ip_num(ip: str) -> int:
    """
    ip_num(ip) -> int
    Usage: sorted(keys, key=lambda k: ip_num(k["ip"]))
    """
    try:
        a, b, c, d = (int(x) for x in str(ip).split("."))
        return ((a * 256 + b) * 256 + c) * 256 + d
    except ValueError:
        return 0


class _Bridge(QObject):
    """
    _Bridge
    Usage: internal; carries a worker's result back to the window thread.
    """
    done = Signal(object, object)


_bridge = None


def run_async(fn, callback) -> None:
    """
    run_async(fn, callback)
    Usage: run_async(lambda: ctl.create_key(sid, "x"), lambda result: self.after_create(result))
    Runs fn in a background thread; callback(result) runs afterwards in the window thread.
    """
    global _bridge
    if _bridge is None:
        _bridge = _Bridge()
        _bridge.done.connect(lambda cb, res: cb(res))

    def work():
        """
        work()
        Usage: internal thread body
        """
        try:
            res = fn()
        except Exception as exc:                      # never let a worker die silently
            res = {"ok": False, "error": {"code": "errGeneric", "detail": repr(exc)}}
        _bridge.done.emit(callback, res)

    threading.Thread(target=work, daemon=True).start()


def _rgb(hex_color: str) -> int:
    """
    _rgb(hex_color) -> int
    Usage: _rgb("#090c12")      # the 0x00BBGGRR number Windows wants for a colour
    """
    h = hex_color.lstrip("#")
    return int(h[4:6], 16) << 16 | int(h[2:4], 16) << 8 | int(h[0:2], 16)


def paint_titlebar(widget, pal: dict, dark: bool) -> None:
    """
    paint_titlebar(widget, pal, dark)
    Usage: paint_titlebar(window, DARK, True)      # call from showEvent; the title bar takes the app background colour
    Windows 11 gets the exact colours (caption, text, border); Windows 10 only switches the bar between dark and light.
    Does nothing on other systems or when Windows refuses; the normal title bar stays.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes
        hwnd = wintypes.HWND(int(widget.winId()))
        dwm = ctypes.windll.dwmapi

        def put(attr: int, value: int) -> None:
            """
            put(attr, value)
            Usage: put(35, 0x00112233)      # DwmSetWindowAttribute with one 32-bit value
            """
            v = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(hwnd, ctypes.c_uint(attr), ctypes.byref(v), ctypes.sizeof(v))

        put(20, 1 if dark else 0)           # DWMWA_USE_IMMERSIVE_DARK_MODE (Windows 10 build 18985+ and 11)
        put(19, 1 if dark else 0)           # same switch on older Windows 10 builds
        put(35, _rgb(pal["bg"]))            # DWMWA_CAPTION_COLOR (Windows 11)
        put(36, _rgb(pal["text"]))          # DWMWA_TEXT_COLOR
        put(34, _rgb(pal["bg"]))            # DWMWA_BORDER_COLOR
    except Exception:
        pass
