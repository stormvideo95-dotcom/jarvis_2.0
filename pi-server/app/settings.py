"""User settings changed from the Jarvis page (stored in /data/settings.json)."""
import json
import os
import threading

from . import config

WAKE_WORDS = {
    "hey_jarvis": "Hey Jarvis",
    "alexa": "Alexa",
    "hey_mycroft": "Hey Mycroft",
    "hey_rhasspy": "Hey Rhasspy",
}
DEFAULTS = {"mode": "button", "wake_word": "hey_jarvis", "sensitivity": 0.5}

_FILE = os.path.join(os.path.dirname(config.SPEAKER_FILE), "settings.json")
_lock = threading.Lock()


def get() -> dict:
    try:
        with open(_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    return {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS}}


def update(changes: dict) -> dict:
    with _lock:
        cur = get()
        if changes.get("mode") in ("button", "wake"):
            cur["mode"] = changes["mode"]
        if changes.get("wake_word") in WAKE_WORDS:
            cur["wake_word"] = changes["wake_word"]
        if "sensitivity" in changes:
            try:
                cur["sensitivity"] = max(0.2, min(0.9, float(changes["sensitivity"])))
            except (TypeError, ValueError):
                pass
        os.makedirs(os.path.dirname(_FILE), exist_ok=True)
        with open(_FILE, "w", encoding="utf-8") as f:
            json.dump(cur, f, indent=2)
        return cur
