"""Jarvis as a device in Music AI (the taste server on the Pi, port 8765).

- Pairs once like the phone/Mac do: the Jarvis page shows a 6-digit code that you
  enter in the Music AI app (Taste AI -> Add a device).
- Publishes what plays on the Nest, so the app's "Play on" list shows "Jarvis (Nest)".
- Handles "play"/"pause" commands sent from the app.
- Lets Jarvis take over the song from another device, or send it there.
"""
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request

from . import config

log = logging.getLogger("jarvis.musicai")
NAME = "Jarvis (Nest)"
_FILE = os.path.join(os.path.dirname(config.SPEAKER_FILE), "musicai.json")

state = {"token": None, "code": None, "pair_id": None, "error": None, "paired": False}


class Unpaired(Exception):
    pass


def _load():
    try:
        with open(_FILE, encoding="utf-8") as f:
            state["token"] = json.load(f).get("token")
            state["paired"] = bool(state["token"])
    except (OSError, ValueError):
        pass


def _save(token):
    os.makedirs(os.path.dirname(_FILE), exist_ok=True)
    with open(_FILE, "w", encoding="utf-8") as f:
        json.dump({"token": token}, f)
    state.update(token=token, paired=True, code=None, pair_id=None)


def _call(method, path, body=None, auth=True, timeout=8.0):
    headers = {"Content-Type": "application/json"}
    if auth:
        headers["X-Device-Token"] = state["token"] or ""
    req = urllib.request.Request(config.MUSIC_AI_URL.rstrip("/") + path, method=method, headers=headers,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        if e.code == 401 and auth:
            raise Unpaired()
        raise


# ---- info for the AI / page -------------------------------------------------
def devices() -> list[dict]:
    if not state["paired"]:
        return []
    return [d for d in _call("GET", "/sync/devices").get("devices", []) if not d.get("me")]


def find(name: str) -> dict | None:
    name = (name or "").lower().strip()
    devs = devices()
    for d in devs:
        if d["name"].lower() == name or d["id"] == name:
            return d
    words = {"gsm": "phone", "telefoon": "phone", "phone": "phone", "mac": "mac", "laptop": "mac", "computer": "mac"}
    want_type = next((t for w, t in words.items() if w in name), None)
    hits = [d for d in devs if (want_type and d.get("type") == want_type) or (name and name in d["name"].lower())]
    hits.sort(key=lambda d: (not d.get("online"), -(d.get("state") or {}).get("updatedAt", 0)))
    return hits[0] if hits else None


def prompt_block() -> str:
    if not state["paired"]:
        return ""
    try:
        devs = devices()
    except Exception:
        return ""
    if not devs:
        return ""
    lines = []
    for d in devs:
        s = d.get("state") or {}
        t = s.get("track") or {}
        what = f"speelt '{t.get('title')}'" if t and s.get("playing") else (f"gepauzeerd: '{t.get('title')}'" if t else "niets")
        lines.append(f"- {d['name']} ({d.get('type')}, {'online' if d.get('online') else 'offline'}): {what}")
    return (
        "\nMUZIEK OP ANDERE TOESTELLEN (Music AI):\n" + "\n".join(lines) +
        "\nActies: {\"type\": \"music_from\", \"device\": \"<naam>\"} = speel wat op dat toestel speelt hier op de Nest verder. "
        "{\"type\": \"music_to\", \"device\": \"<naam>\"} = zet de muziek die nu hier speelt verder op dat toestel.\n"
        "Voorbeeld: \"speel mijn gsm hier verder\" -> {\"say\": \"Ik neem het over van je gsm.\", "
        "\"action\": {\"type\": \"music_from\", \"device\": \"<naam van de gsm>\"}}\n"
    )


def status() -> dict:
    return {"paired": state["paired"], "code": state["code"], "error": state["error"], "url": config.MUSIC_AI_URL}


# ---- actions ----------------------------------------------------------------
def take_from(name: str):
    """Returns (tracks, start_ms, device) of what plays on that device, and pauses it there."""
    d = find(name)
    if not d:
        return None, 0, None
    s = d.get("state") or {}
    tracks = ([s["track"]] if s.get("track") else []) + (s.get("queue") or [])
    if not tracks:
        return None, 0, d
    start = int(s.get("positionMs") or 0)
    if s.get("playing") and s.get("updatedAt"):
        start += max(0, int(time.time() * 1000) - int(s["updatedAt"]))
    if s.get("playing"):
        try:
            _call("POST", "/sync/command", {"target": d["id"], "command": {"action": "pause"}})
        except Exception:
            log.exception("could not pause %s", d["name"])
    return tracks, start, d


def send_to(name: str, track: dict, position_ms: int, queue: list[dict]) -> dict | None:
    d = find(name)
    if not d:
        return None
    _call("POST", "/sync/command", {"target": d["id"], "command": {
        "action": "play", "track": track, "positionMs": int(position_ms), "queue": queue}})
    return d


# ---- background loops -------------------------------------------------------
def _pair_loop():
    while not state["paired"]:
        try:
            res = _call("POST", "/pair/start", {"name": NAME, "type": "speaker"}, auth=False)
            if res.get("approved") and res.get("token"):
                _save(res["token"])
                break
            state.update(code=res.get("code"), pair_id=res.get("pairId"), error=None)
            log.info("Music AI pairing code: %s", state["code"])
            deadline = time.time() + int(res.get("expiresIn") or 600) - 5
            while time.time() < deadline and not state["paired"]:
                time.sleep(3)
                st = _call("GET", f"/pair/status?pairId={state['pair_id']}", auth=False)
                if st.get("approved") and st.get("token"):
                    _save(st["token"])
                    log.info("paired with Music AI")
                elif st.get("expired"):
                    break
        except Exception as e:
            state["error"] = f"Music AI niet bereikbaar op {config.MUSIC_AI_URL}"
            log.debug("music ai pairing: %s", e)
            time.sleep(20)


def _command_loop(on_command):
    while True:
        if not state["paired"]:
            time.sleep(5)
            continue
        try:
            for cmd in _call("GET", "/sync/commands?wait=20", timeout=30).get("commands", []):
                on_command(cmd)
            state["error"] = None
        except Unpaired:
            log.warning("Music AI forgot Jarvis, pairing again")
            state.update(token=None, paired=False)
            threading.Thread(target=_pair_loop, daemon=True).start()
        except Exception:
            state["error"] = f"Music AI niet bereikbaar op {config.MUSIC_AI_URL}"
            time.sleep(10)


def _state_loop(get_state):
    while True:
        time.sleep(10)
        if not state["paired"]:
            continue
        try:
            _call("POST", "/sync/state", {"state": get_state()})
        except Unpaired:
            pass
        except Exception:
            pass


def start(on_command, get_state):
    _load()
    if not state["paired"]:
        threading.Thread(target=_pair_loop, daemon=True).start()
    threading.Thread(target=_command_loop, args=(on_command,), daemon=True).start()
    threading.Thread(target=_state_loop, args=(get_state,), daemon=True).start()
