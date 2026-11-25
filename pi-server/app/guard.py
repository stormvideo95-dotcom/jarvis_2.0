"""TimeGuard: Jarvis keeps Storm's daily social-media budget.

- Guarded apps are locked on the phone and Mac unless Jarvis unlocks them.
- "Unlock WhatsApp for 15 minutes"            -> unlocked at once (if budget left)
- "Can I scroll Instagram?"                     -> "Je hebt nog 62 minuten. Hoe lang?" -> "15 minuten"
- Time spent in an unlocked app counts against the daily limit (default 120 min).
  Long YouTube videos count half, Shorts count full.
- When the budget is gone, every unlock ends. Resets at midnight (Europe/Brussels).
State lives in /data/guard.json. Devices talk to /api/guard/*.
"""
import json
import os
import re
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from . import config

TZ = ZoneInfo(os.environ.get("TZ_NAME", "Europe/Brussels"))
FILE = os.path.join(os.path.dirname(config.SPEAKER_FILE), "guard.json")
_lock = threading.RLock()

# id: (spoken name, words, android packages, websites, "scroll" = ask before unlocking)
APPS = {
    "whatsapp": ("WhatsApp", ("whatsapp", "whats app", "wasap", "watsapp", "berichten", "messages"),
                 ["com.whatsapp", "com.whatsapp.w4b"], ["web.whatsapp.com"], False),
    "instagram": ("Instagram", ("instagram", "insta", "reels"),
                  ["com.instagram.android", "com.instagram.barcelona"], ["instagram.com", "threads.net"], True),
    # only Instagram's messages (Direct): the feed and Reels stay locked
    "instagram_dm": ("je Instagram-berichten", ("instagram berichten", "insta berichten", "dm", "dms", "directs", "direct messages"),
                     [], ["instagram.com/direct"], False),
    "tiktok": ("TikTok", ("tiktok", "tik tok", "tiktak"),
               ["com.zhiliaoapp.musically", "com.ss.android.ugc.trill"], ["tiktok.com"], True),
    "snapchat": ("Snapchat", ("snapchat", "snap"), ["com.snapchat.android"], ["snapchat.com"], True),
    "youtube": ("YouTube", ("youtube", "you tube", "shorts", "yt"),
                ["com.google.android.youtube", "app.revanced.android.youtube"], ["youtube.com", "youtu.be"], True),
    "reddit": ("Reddit", ("reddit",), ["com.reddit.frontpage"], ["reddit.com"], True),
    "x": ("X", ("twitter", "x app", " x "), ["com.twitter.android"], ["x.com", "twitter.com"], True),
    "facebook": ("Facebook", ("facebook", "fb"), ["com.facebook.katana"], ["facebook.com"], True),
}
YOUTUBE_LONG_WEIGHT = 0.5      # long videos count half
DM_WEIGHT = 0.5                # Instagram messages-only counts half
DEFAULTS = {"enabled": True, "limit_min": 120}


def _today():
    return datetime.now(TZ).strftime("%Y-%m-%d")


def _load():
    try:
        with open(FILE, encoding="utf-8") as f:
            s = json.load(f)
    except (OSError, ValueError):
        s = {}
    s = {**DEFAULTS, "date": _today(), "used": {}, "grants": {}, "devices": {}, **s}
    if s["date"] != _today():                       # new day: fresh budget, everything locked
        s.update(date=_today(), used={}, grants={})
    return s


def _save(s):
    os.makedirs(os.path.dirname(FILE), exist_ok=True)
    tmp = FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f)
    os.replace(tmp, FILE)


def _used_sec(s) -> float:
    return sum(s["used"].values())


def _remaining_sec(s) -> float:
    return max(0.0, s["limit_min"] * 60 - _used_sec(s))


def _active_grants(s) -> dict:
    now = time.time()
    left = _remaining_sec(s)
    if left <= 0:
        return {}
    return {app: until for app, until in s["grants"].items() if until > now}


# ---- device API -----------------------------------------------------------------
def status(device: str | None = None) -> dict:
    with _lock:
        s = _load()
        if device:
            s["devices"][device] = time.time()
            _save(s)
        grants = _active_grants(s) if s["enabled"] else {a: 4102444800 for a in APPS}   # disabled = all open
        return {
            "enabled": s["enabled"], "limit_min": s["limit_min"],
            "used_min": round(_used_sec(s) / 60, 1), "remaining_min": round(_remaining_sec(s) / 60, 1),
            "grants": grants, "now": time.time(),
            "apps": {a: {"name": v[0], "android": v[2], "sites": v[3]} for a, v in APPS.items()},
            "devices": {d: round(time.time() - t) for d, t in s["devices"].items()},
        }


def report(device: str, items: list) -> dict:
    """Devices report seconds spent in unlocked apps: [{"app": "youtube", "seconds": 30, "shorts": false}]."""
    with _lock:
        s = _load()
        for it in items or []:
            app = it.get("app")
            sec = float(it.get("seconds") or 0)
            if app not in APPS or not (0 < sec <= 600):
                continue
            if app == "youtube" and not it.get("shorts"):
                sec *= YOUTUBE_LONG_WEIGHT
            if app == "instagram_dm":
                sec *= DM_WEIGHT
            s["used"][app] = s["used"].get(app, 0) + sec
        s["devices"][device] = time.time()
        _save(s)
    return status()


def grant(app: str, minutes: float) -> dict:
    with _lock:
        s = _load()
        minutes = max(1, min(int(minutes), int(_remaining_sec(s) // 60) or 0))
        apps = [a for a in APPS if a != "instagram_dm"] if app == "all" else [app]
        until = time.time() + minutes * 60
        for a in apps:
            s["grants"][a] = max(s["grants"].get(a, 0), until)
        _save(s)
        return {"minutes": minutes, "until": until}


def lock(app: str = "all"):
    with _lock:
        s = _load()
        if app == "all":
            s["grants"] = {}
        else:
            s["grants"].pop(app, None)
        _save(s)


def settings(enabled=None, limit_min=None) -> dict:
    with _lock:
        s = _load()
        if enabled is not None:
            s["enabled"] = bool(enabled)
        if limit_min is not None:
            s["limit_min"] = max(0, min(600, int(limit_min)))
        _save(s)
    return status()


# ---- voice ---------------------------------------------------------------------
NUM_WORDS = {"een": 1, "één": 1, "twee": 2, "drie": 3, "vier": 4, "vijf": 5, "tien": 10, "vijftien": 15,
             "twintig": 20, "dertig": 30, "half uur": 30, "halfuur": 30, "kwartier": 15, "uur": 60, "vijfenveertig": 45}


def find_app(text: str):
    t = " " + re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()) + " "
    if re.search(r"\b(alles|alle apps|mijn gsm|mijn telefoon|mijn phone|social media|sociale media|everything)\b", t):
        return "all"
    if re.search(r"\b(insta|instagram)\b", t) and re.search(r"\b(bericht|berichten|messages|message|dm|dms|chat|chats|direct|directs)\b", t):
        return "instagram_dm"
    for app, (_, words, *_rest) in APPS.items():
        if any(w.strip() and re.search(rf"\b{re.escape(w.strip())}\b", t) for w in words):
            return app
    return None


def parse_minutes(text: str, bare: bool = True):
    """Minutes in a sentence. bare=False: only numbers with a unit ("5 min", "een kwartier"),
    so "100% zeker" is not read as 100 minutes."""
    t = re.sub(r"\d+\s*(%|procent|percent)", " ", (text or "").lower())
    m = re.search(r"(\d{1,3})\s*(min|minuten|minuut|m\b)", t)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d{1,2})\s*(uur|u\b|hour)", t)
    if m:
        return int(m.group(1)) * 60
    if "half uur" in t or "halfuur" in t:
        return 30
    if "kwartier" in t:
        return 15
    for w, v in sorted(NUM_WORDS.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{w}\s+(min|minuten|minuut|minutes|uur)\b", t):
            return v * 60 if t.split(w, 1)[1].strip().startswith("uur") and w not in ("half uur", "halfuur") else v
    if not bare:
        return None
    m = re.search(r"\b(\d{1,3})\b", t)
    if m:
        return int(m.group(1))
    for w, v in sorted(NUM_WORDS.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{w}\b", t):
            return v
    return None


def _fmt(minutes: float) -> str:
    m = int(round(minutes))
    if m >= 60:
        h, r = divmod(m, 60)
        return f"{h} uur" + (f" en {r} minuten" if r else "")
    return f"{m} {'minuut' if m == 1 else 'minuten'}"


pending = {}   # {"app": ..., "asked": time}


def voice_unlock(app: str | None, minutes, confirmed: bool = False) -> tuple[str, bool]:
    """Returns (what Jarvis says, whether Jarvis now waits for an answer)."""
    st = status()
    if not st["enabled"]:
        return "TimeGuard staat uit, alles is al open.", False
    if not app:
        pending.clear()
        pending.update(app=None, asked=time.time())
        return "Welke app wil je openen?", True
    name = "al je apps" if app == "all" else APPS[app][0]
    left = st["remaining_min"]
    if left < 1:
        pending.clear()
        return f"Sorry, je {_fmt(st['limit_min'])} van vandaag zijn op. Morgen kan het weer.", False
    scroll = app == "all" or APPS[app][4]
    if minutes is None or (scroll and not confirmed):
        pending.clear()
        pending.update(app=app, minutes=minutes, asked=time.time())
        if minutes:
            return f"Je hebt nog {_fmt(left)} van je {_fmt(st['limit_min'])}. Zeker dat je {name} {_fmt(minutes)} wil openen?", True
        return f"Je hebt nog {_fmt(left)} van je {_fmt(st['limit_min'])} over. Hoe lang wil je {name}?", True
    pending.clear()
    g = grant(app, minutes)
    extra = f" Meer kon niet, je had nog maar {_fmt(left)}." if g["minutes"] < minutes else ""
    verb = "zijn" if app in ("all", "instagram_dm") else "is"
    return f"Oké, {name} {verb} open voor {_fmt(g['minutes'])}.{extra}", False


def answer_pending(text: str) -> tuple[str, bool] | None:
    """Answer to "how long?" / "are you sure?". None when there is no open question."""
    if not pending or time.time() - pending.get("asked", 0) > 90:
        pending.clear()
        return None
    t = (text or "").lower()
    if re.search(r"\b(op slot|lock|vergrendel|sluit|dicht|blokkeer)\b", t):
        pending.clear()          # a new command ("zet alles op slot"), not an answer
        return None
    if re.search(r"\b(nee|laat maar|toch niet|stop|no|niet)\b", t) and parse_minutes(t) is None:
        pending.clear()
        return "Oké, alles blijft op slot. Goed bezig!", False
    named = find_app(t)
    app = named if named and named != "all" else (pending.get("app") or named)
    # "Zeker dat je ... 5 minuten?" -> "ja" / "100% zeker" keeps the 5 minutes.
    # Only a number WITH a unit ("nee, 10 minuten") changes it then.
    asked_minutes = pending.get("minutes")
    minutes = (parse_minutes(t, bare=False) or asked_minutes) if asked_minutes else parse_minutes(t)
    if not app:
        return "Welke app bedoel je? Bijvoorbeeld WhatsApp of Instagram.", True
    if minutes is None:
        if re.search(r"\b(ja|yes|zeker|oke|ok|goed)\b", t):
            return "Hoe lang? Bijvoorbeeld 15 minuten.", True
        return f"Hoe lang wil je {('al je apps' if app == 'all' else APPS[app][0])}? Zeg bijvoorbeeld 15 minuten.", True
    return voice_unlock(app, minutes, confirmed=True)


def voice_status() -> str:
    st = status()
    if not st["enabled"]:
        return "TimeGuard staat uit."
    open_now = [f"{'alles' if a == 'all' else APPS[a][0]} nog {_fmt((u - time.time()) / 60)}"
                for a, u in st["grants"].items()]
    msg = f"Je hebt vandaag {_fmt(st['used_min'])} gebruikt en nog {_fmt(st['remaining_min'])} over."
    if open_now:
        msg += " Open: " + ", ".join(open_now) + "."
    return msg


def prompt_block() -> str:
    st = status()
    return (
        f"\nTIMEGUARD (social media slot): limiet {st['limit_min']} min/dag, nog {st['remaining_min']} min over, "
        f"open: {', '.join(st['grants']) or 'niets'}. Apps: {', '.join(APPS)}.\n"
        'Acties: {"type": "guard_unlock", "app": "<app-id of all>", "minutes": <getal of null>} '
        '(bij "unlock WhatsApp 15 min", "mag ik Instagram", "ontgrendel mijn gsm"); '
        '{"type": "guard_lock", "app": "<app-id of all>"}; {"type": "guard_status"} '
        '("hoeveel social media tijd heb ik nog").\n'
    )
