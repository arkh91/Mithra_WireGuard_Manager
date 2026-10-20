# File: core/applog.py
# The app log: kept in memory for the Logs tab and appended to %LOCALAPPDATA%\MithraWireGuard\logs\app.log.
# Secrets (tokens, secret API paths, private keys) are never written: callers log hosts and IPs only.
# Edit with: vi core/applog.py
import collections
import threading
import time

from mwg_core import config

_LEVELS = ("DEBUG", "INFO", "WARN", "ERROR")


class AppLog:
    """
    AppLog()
    Usage: log = AppLog(); log.info("api", "pulled 12 keys"); log.rows(500, "ERROR"); log.text()
    """

    def __init__(self, to_file: bool = True):
        """
        __init__(to_file=True)
        Usage: AppLog()
        """
        self._rows = collections.deque(maxlen=config.LOG_MAX)
        self._lock = threading.Lock()
        self._file = None
        if to_file:
            try:
                path = config.log_dir() / "app.log"
                if path.exists() and path.stat().st_size > 2_000_000:
                    path.replace(path.with_suffix(".log.1"))
                self._file = open(path, "a", encoding="utf-8", buffering=1)
            except OSError:
                self._file = None

    def add(self, level: str, comp: str, text: str) -> None:
        """
        add(level, comp, text)
        Usage: log.add("WARN", "api", "certificate mismatch")
        """
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        row = {"ts": ts, "lv": level if level in _LEVELS else "INFO", "cp": comp, "tx": str(text)}
        with self._lock:
            self._rows.append(row)
            if self._file:
                try:
                    self._file.write(f"{ts} {row['lv']:<5} {comp:<10} {row['tx']}\n")
                except OSError:
                    pass

    def info(self, comp: str, text: str) -> None:
        """
        info(comp, text)
        Usage: log.info("app", "started")
        """
        self.add("INFO", comp, text)

    def warn(self, comp: str, text: str) -> None:
        """
        warn(comp, text)
        Usage: log.warn("api", "slow reply")
        """
        self.add("WARN", comp, text)

    def error(self, comp: str, text: str) -> None:
        """
        error(comp, text)
        Usage: log.error("api", "401")
        """
        self.add("ERROR", comp, text)

    def rows(self, limit: int = 1000, level: str = "") -> list:
        """
        rows(limit=1000, level="") -> list
        Usage: log.rows(500, "WARN")    # newest first; level filters WARN = WARN and ERROR
        """
        with self._lock:
            items = list(self._rows)
        if level in _LEVELS:
            floor = _LEVELS.index(level)
            items = [r for r in items if _LEVELS.index(r["lv"]) >= floor]
        return list(reversed(items))[:max(1, limit)]

    def text(self) -> str:
        """
        text() -> str
        Usage: clipboard(log.text())
        """
        with self._lock:
            return "\n".join(f"{r['ts']} {r['lv']:<5} {r['cp']:<10} {r['tx']}" for r in self._rows)

    def clear(self) -> None:
        """
        clear()
        Usage: log.clear()
        """
        with self._lock:
            self._rows.clear()
