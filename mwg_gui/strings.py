# File: mwg_gui/strings.py
# All app texts (English and Persian, loaded from strings.json) and the few texts that take arguments.
# Edit with: vi mwg_gui/strings.py
import json
from pathlib import Path

_DATA = json.loads((Path(__file__).with_name("strings.json")).read_text(encoding="utf-8"))

_FN = {
    "en": {
        "serverSub": lambda host, n: f"{host} • {n} key{'' if n == 1 else 's'}",
        "agoS": lambda n: f"{n}s ago", "agoM": lambda n: f"{n} min ago", "agoH": lambda n: f"{n} h ago",
        "agoD": lambda n: f"{n} d ago", "updatedAgo": lambda s: f"Updated {s}",
        "showing": lambda a, b: f"Showing {a} of {b} keys. Search to narrow the list.",
        "removeKeyBody": lambda name: f"{name} stops working right away and its config cannot be recovered.",
        "added": lambda n: f"Server added: {n} key{'' if n == 1 else 's'} pulled.",
        "exported": lambda n: f"{n} config file{'' if n == 1 else 's'} saved.",
        "keyCreated": lambda ip: f"Key {ip} created.", "keyRemoved": lambda ip: f"Key {ip} removed.",
        "keyPaused": lambda ip: f"Key {ip} paused.", "keyResumed": lambda ip: f"Key {ip} resumed.",
        "updateApi": lambda have, new, what: (f"This server runs API {have}; API {new} adds: {what}. "
                                              "Update the server (keys and peers stay). On the server run:"),
        "leftD": lambda n: f"{n}d left", "leftH": lambda n: f"{n}h left",
        "afterFirst": lambda d: f"{d} from 1st use",
        "endsOn": lambda when, left: f"Ends {when} ({left}).",
        "endedOn": lambda when: f"Ended {when}.",
        "serverNow": lambda clock, off, zone: f"Server time now: {clock} (UTC{off}{', ' + zone if zone else ''}). The end is counted on the server's clock.",
        "durText": lambda n, u: (f"{n // 12} year" + ("" if n == 12 else "s")) if u == "m" and n % 12 == 0 else
                                f"{n} " + {"h": "hour", "d": "day", "w": "week", "m": "month"}[u] + ("" if n == 1 else "s"),
        "pendingFor": lambda d: f"Ends {d} after its first connection (not connected yet).",
        "everySec": lambda n: f"{n // 60} min" if n >= 60 else f"{n} s",
    },
    "fa": {
        "serverSub": lambda host, n: f"{host} • {n} کلید",
        "agoS": lambda n: f"{n} ثانیه پیش", "agoM": lambda n: f"{n} دقیقه پیش", "agoH": lambda n: f"{n} ساعت پیش",
        "agoD": lambda n: f"{n} روز پیش", "updatedAgo": lambda s: f"به‌روزرسانی {s}",
        "showing": lambda a, b: f"نمایش {a} از {b} کلید. برای محدود کردن جستجو کنید.",
        "removeKeyBody": lambda name: f"{name} فوراً از کار می‌افتد و پیکربندی آن قابل بازیابی نیست.",
        "added": lambda n: f"سرور اضافه شد: {n} کلید دریافت شد.",
        "exported": lambda n: f"{n} فایل پیکربندی ذخیره شد.",
        "keyCreated": lambda ip: f"کلید {ip} ساخته شد.", "keyRemoved": lambda ip: f"کلید {ip} حذف شد.",
        "keyPaused": lambda ip: f"کلید {ip} متوقف شد.", "keyResumed": lambda ip: f"کلید {ip} دوباره فعال شد.",
        "updateApi": lambda have, new, what: (f"این سرور API {have} دارد؛ API {new} این‌ها را اضافه می‌کند: {what}. "
                                              "سرور را به‌روز کنید (کلیدها و کاربران می‌مانند). روی سرور اجرا کنید:"),
        "leftD": lambda n: f"{n} روز مانده", "leftH": lambda n: f"{n} ساعت مانده",
        "afterFirst": lambda d: f"{d} از اولین اتصال",
        "endsOn": lambda when, left: f"پایان {when} ({left}).",
        "endedOn": lambda when: f"پایان یافته {when}.",
        "serverNow": lambda clock, off, zone: f"ساعت سرور اکنون: {clock} (UTC{off}{'، ' + zone if zone else ''}). پایان بر اساس ساعت سرور شمرده می‌شود.",
        "durText": lambda n, u: f"{n // 12} سال" if u == "m" and n % 12 == 0 else
                                f"{n} " + {"h": "ساعت", "d": "روز", "w": "هفته", "m": "ماه"}[u],
        "pendingFor": lambda d: f"پایان {d} پس از اولین اتصال (هنوز وصل نشده).",
        "everySec": lambda n: f"{n // 60} دقیقه" if n >= 60 else f"{n} ثانیه",
    },
}


def tr(lang: str, key: str, *args) -> str:
    """
    tr(lang, key, *args) -> str
    Usage: tr("en", "addKey")      tr("fa", "added", 7)
    Text of a key in the language (English when missing); keys with arguments are called with them.
    """
    fn = _FN.get(lang, {}).get(key) or _FN["en"].get(key)
    if fn:
        return fn(*args)
    return _DATA.get(lang, {}).get(key) or _DATA["en"].get(key) or key
