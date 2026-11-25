"""Link with Storm Study (study.ictstorm.com).

GET  /api/jarvis  (Bearer STUDY_JARVIS_TOKEN) -> topics, items, orders, mistakes, points
POST /api/jarvis  {"action": "answer" | "points", ...}

Everything is cached in /data/study_cache.json, so study mode keeps working when the
site is down. Answers that could not be sent wait in /data/study_queue.json and are
sent the next time the site answers.
"""
import json
import logging
import os
import threading
import urllib.error
import urllib.request

from . import config

log = logging.getLogger("jarvis.study")
_DIR = os.path.dirname(config.SPEAKER_FILE)
CACHE = os.path.join(_DIR, "study_cache.json")
QUEUE = os.path.join(_DIR, "study_queue.json")
_lock = threading.Lock()


class AuthError(Exception):
    pass


class Offline(Exception):
    pass


def enabled() -> bool:
    return bool(config.STUDY_JARVIS_TOKEN)


def _req(method: str, body: dict | None = None, timeout: float = 10.0):
    req = urllib.request.Request(
        config.STUDY_URL.rstrip("/") + "/api/jarvis", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {config.STUDY_JARVIS_TOKEN}",
                 "Content-Type": "application/json", "User-Agent": "Jarvis-2.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise AuthError() from e
        raise Offline(f"HTTP {e.code}") from e
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise Offline(str(e)) from e


# ---- cache --------------------------------------------------------------------
def _read(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def cached() -> dict:
    return _read(CACHE, {})


def topics() -> list[dict]:
    return cached().get("topics") or []


def mistakes() -> list[dict]:
    return cached().get("mistakes") or []


def points():
    return cached().get("points")


# ---- update ("Jarvis, update study mode") ----------------------------------------
def update() -> str:
    """Fetch the latest data and return a short spoken summary."""
    if not enabled():
        return "Storm Study is nog niet gekoppeld. Zet je Jarvis-code in de instellingen op de Pi."
    old = cached()
    try:
        new = _req("GET")
    except AuthError:
        return "Storm Study weigert mijn code. Maak een nieuwe Jarvis-code op de site en zet die op de Pi."
    except Offline:
        if old:
            return f"Storm Study is niet bereikbaar. Ik gebruik de leerstof van de vorige keer, {len(old.get('topics') or [])} onderwerpen."
        return "Storm Study is niet bereikbaar en ik heb nog geen leerstof opgeslagen."
    sent = flush_queue()
    _write(CACHE, new)
    old_ids = {t.get("id") for t in old.get("topics") or []}
    new_topics = [t for t in new.get("topics") or [] if t.get("id") not in old_ids]
    n_mis = len(new.get("mistakes") or [])
    parts = []
    if not old:
        parts.append(f"Ik heb {len(new.get('topics') or [])} onderwerpen geladen")
    elif new.get("version") == old.get("version"):
        parts.append("Er is geen nieuwe leerstof")
    elif new_topics:
        names = ", ".join(t.get("name", t.get("id")) for t in new_topics[:3])
        parts.append(f"Er {'is 1 nieuw onderwerp' if len(new_topics) == 1 else f'zijn {len(new_topics)} nieuwe onderwerpen'}: {names}")
    else:
        parts.append("De leerstof is bijgewerkt")
    parts.append(f"je hebt {n_mis} open {'fout' if n_mis == 1 else 'fouten'}" if n_mis else "je hebt geen open fouten")
    msg = " en ".join(parts) + "."
    if new.get("points") is not None:
        msg += f" Je staat op {new['points']} punten."
    if sent:
        msg += f" Ik heb ook {sent} {'bewaard antwoord' if sent == 1 else 'bewaarde antwoorden'} doorgestuurd."
    return msg


# ---- posting answers / points (with offline queue) -------------------------------
def post(body: dict):
    """Send to Storm Study; on failure keep it in the queue. Returns the response or None."""
    if not enabled():
        return None
    try:
        res = _req("POST", body)
        if isinstance(res, dict) and res.get("points") is not None:
            with _lock:
                c = cached()
                if c:
                    c["points"] = res["points"]
                    _write(CACHE, c)
        return res
    except AuthError:
        log.warning("Storm Study: Jarvis code refused (401)")
        return None
    except Offline as e:
        log.info("Storm Study offline (%s), answer queued", e)
        with _lock:
            q = _read(QUEUE, [])
            q.append(body)
            _write(QUEUE, q[-500:])
        return None


def post_async(body: dict, done=None):
    def run():
        res = post(body)
        if done:
            done(res)
    threading.Thread(target=run, daemon=True).start()


def flush_queue() -> int:
    with _lock:
        q = _read(QUEUE, [])
    if not q or not enabled():
        return 0
    sent = 0
    for body in q:
        try:
            _req("POST", body)
            sent += 1
        except AuthError:
            break
        except Offline:
            break
    with _lock:
        rest = _read(QUEUE, [])[sent:]
        _write(QUEUE, rest)
    return sent


def queued() -> int:
    return len(_read(QUEUE, []))


def status() -> dict:
    c = cached()
    return {"linked": enabled(), "topics": len(c.get("topics") or []), "mistakes": len(c.get("mistakes") or []),
            "points": c.get("points"), "version": c.get("version"), "queued": queued()}
