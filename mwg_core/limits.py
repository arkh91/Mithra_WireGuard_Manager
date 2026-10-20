# File: core/limits.py
# Traffic limits typed by the user ("20G", "500 MB", "unlimited"), parsed the same way the server's API parses them.
# Edit with: vi core/limits.py
"""
Units are decimal, like the app shows sizes: K M G T = 10^3 .. 10^12 bytes; KiB MiB GiB TiB = 1024^n.
A plain number is bytes. Empty, "0", "unlimited", "none", "off", "no" mean unlimited (0).
"""
import datetime
import re

MAX_BYTES = 10 ** 18
_RE = re.compile(r"^(\d+(?:[.,]\d+)?)\s*([kmgt]?)(i?)b?$", re.I)
_POW = {"": 0, "k": 1, "m": 2, "g": 3, "t": 4}
_UNLIMITED = {"", "0", "unlimited", "none", "off", "no", "∞", "نامحدود"}


def parse_traffic(text) -> int | None:
    """
    parse_traffic(text) -> int or None
    Usage: parse_traffic("20G")        # 20000000000
           parse_traffic("unlimited")  # 0
           parse_traffic("lots")       # None (not valid)
    """
    if text is None:
        return 0
    if isinstance(text, int):
        return text if 0 <= text <= MAX_BYTES else None
    t = str(text).strip()
    if t.lower() in _UNLIMITED:
        return 0
    m = _RE.match(t)
    if not m:
        return None
    n = round(float(m.group(1).replace(",", ".")) * (1024 if m.group(3) else 1000) ** _POW[m.group(2).lower()])
    return n if 0 <= n <= MAX_BYTES else None


def limit_text(n: int) -> str:
    """
    limit_text(n) -> str
    Usage: edit.setText(limit_text(key["limit"]))    # 20000000000 -> "20G", 1500000000000 -> "1.5T", 0 -> ""
    The short form shown in the edit field; parse_traffic() reads it back to the same number.
    """
    if not n:
        return ""
    for unit, power in (("T", 4), ("G", 3), ("M", 2), ("K", 1)):
        v = n / 1000 ** power
        if v >= 1 and abs(round(v, 3) * 1000 ** power - n) < 1:
            return f"{round(v, 3):.3f}".rstrip("0").rstrip(".") + unit
    return str(n)


_DUR = re.compile(r"^(\d{1,4})\s*(h|hours?|d|days?|w|weeks?|m|mo|mon|months?|y|yrs?|years?)$", re.I)


def parse_duration(text) -> str | None:
    """
    parse_duration(text) -> str, "" or None
    Usage: parse_duration("30 days")   # "30d"
           parse_duration("1 month")   # "1m"   (m = calendar months, as on the server)
           parse_duration("never")     # ""     (no time limit)
           parse_duration("soon")      # None   (not valid)
    The same rules as the server's API: h hours, d days, w weeks, m months, 1..9999 of them; y years = 12 months
    ("1 year" -> "12m").
    """
    if text is None:
        return ""
    if isinstance(text, int):
        return f"{text}d" if 0 < text < 10000 else None
    t = str(text).strip().lower()
    if t in _UNLIMITED or t == "never":
        return ""
    m = _DUR.match(t)
    if not m or int(m.group(1)) < 1:
        return None
    if m.group(2)[0].lower() == "y":               # years are sent as months: every server with API 2.2 takes them
        n = int(m.group(1)) * 12
        return f"{n}m" if n < 10000 else None
    return f"{int(m.group(1))}{m.group(2)[0].lower()}"


_END_ON = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{1,2}):(\d{2}))?$")


def parse_end_on(text) -> str | None:
    """
    parse_end_on(text) -> "YYYY-MM-DD HH:MM" or None
    Usage: parse_end_on("2026-12-31 18:00")   # "2026-12-31 18:00"
           parse_end_on("2026-12-31")         # "2026-12-31 23:59"  (a date alone: the end of that day)
           parse_end_on("2026-02-30 10:00")   # None (no such day)
    A date and time on the SERVER's clock, as the "End on" choice sends it; None when it is not a real date and time.
    """
    m = _END_ON.match(str(text or "").strip())
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    h, mi = (int(m.group(4)), int(m.group(5))) if m.group(4) is not None else (23, 59)
    try:
        datetime.datetime(y, mo, d, h, mi)
    except ValueError:
        return None
    return f"{y:04d}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}"


def server_now(offset_minutes: int, now: float | None = None) -> datetime.datetime:
    """
    server_now(offset_minutes, now=None) -> naive datetime
    Usage: server_now(-420)      # the server's wall clock when it is UTC-07:00
    """
    import time as _t
    base = datetime.datetime.fromtimestamp(_t.time() if now is None else now, datetime.timezone.utc)
    return (base + datetime.timedelta(minutes=offset_minutes)).replace(tzinfo=None)


def parse_utc_offset(text) -> int | None:
    """
    parse_utc_offset(text) -> minutes or None
    Usage: parse_utc_offset("-07:00")    # -420;  "+03:30" -> 210
    """
    m = re.match(r"^([+-])(\d{2}):(\d{2})$", str(text or ""))
    return None if not m else (-1 if m.group(1) == "-" else 1) * (int(m.group(2)) * 60 + int(m.group(3)))


def expiry_body(mode: str, duration: str = "") -> dict | None:
    """
    expiry_body(mode, duration="") -> dict or None
    Usage: expiry_body("on", "2026-12-31 18:00")   # {"expiresOn": "2026-12-31 18:00"}  (the server's clock)
           expiry_body("now", "30d")     # {"expires": "30d"}
           expiry_body("first", "1m")    # {"expiresAfterFirstConnection": "1m"}
           expiry_body("none")           # {"expires": "never"}
           expiry_body("keep")           # None  (leave the time limit as it is)
    The JSON the API takes for a key's time limit (PUT /keys/<ip>/expiry, or inside POST /create).
    """
    if mode == "on":
        return {"expiresOn": duration}
    if mode == "now":
        return {"expires": duration}
    if mode == "first":
        return {"expiresAfterFirstConnection": duration}
    if mode == "none":
        return {"expires": "never"}
    return None


def expiry_state(k: dict, now: float) -> tuple | None:
    """
    expiry_state(key, now) -> ("expired", end) | ("ends", end) | ("pending", "30d") | None
    Usage: st = expiry_state(key, time.time())     # end is an epoch; None = no time limit
    "pending": a time limit that starts at the key's first connection, which has not happened yet.
    """
    end = 0.0
    if k.get("expiresAt"):
        try:
            end = datetime.datetime.fromisoformat(str(k["expiresAt"]).replace("Z", "+00:00")).timestamp()
        except ValueError:
            end = 0.0
    if k.get("expired") or (end and now >= end):
        return ("expired", end)
    if end:
        return ("ends", end)
    if k.get("expiresAfter"):
        return ("pending", k["expiresAfter"])
    return None
