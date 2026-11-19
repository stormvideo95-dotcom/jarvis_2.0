"""The thinking part: NVIDIA cloud LLM that answers and picks an action."""
import json
import re
from collections import deque

from . import config

SYSTEM_PROMPT = """Je bent Jarvis, de slimme huisassistent van Storm in België.
Je praat via een speaker, dus antwoord KORT (maximaal 2 zinnen), natuurlijk en zonder opmaak,
emoji of lijstjes. Antwoord in dezelfde taal als de gebruiker (meestal Nederlands).

Geef ALTIJD alleen één JSON-object terug, niets anders:
{"say": "<wat je hardop zegt>", "action": <null of een actie>}

Mogelijke acties:
{"type": "play_music", "query": "<zoekterm voor YouTube, bv. 'phonk mix'>"}
{"type": "pause"}   {"type": "resume"}   {"type": "skip"}   {"type": "stop"}
{"type": "volume", "level": <0-100>}
{"type": "timer", "seconds": <aantal seconden>, "label": "<korte naam>"}

Voorbeelden:
"zet phonk op" -> {"say": "Phonk komt eraan.", "action": {"type": "play_music", "query": "phonk mix"}}
"volgende" -> {"say": "", "action": {"type": "skip"}}
"zet een timer van 5 minuten" -> {"say": "Timer van vijf minuten loopt.", "action": {"type": "timer", "seconds": 300, "label": "vijf minuten"}}
"hoe ver is de maan" -> {"say": "Gemiddeld zo'n 384.000 kilometer.", "action": null}
"""

ACTIONS = {"play_music", "pause", "resume", "skip", "stop", "volume", "timer"}

_history: deque = deque(maxlen=8)  # last 4 exchanges
_client = None


def _llm():
    global _client
    if _client is None:
        from openai import OpenAI

        _client = OpenAI(base_url=config.NVIDIA_BASE_URL, api_key=config.NVIDIA_API_KEY)
    return _client


def parse_reply(raw: str) -> dict:
    """Turn model output into {"say": str, "action": dict|None}. Never raises."""
    raw = (raw or "").strip()
    match = re.search(r"\{.*\}", raw, re.S)
    if match:
        try:
            data = json.loads(match.group(0))
            say = str(data.get("say") or "").strip()
            action = data.get("action")
            if not (isinstance(action, dict) and action.get("type") in ACTIONS):
                action = None
            return {"say": say, "action": action}
        except (json.JSONDecodeError, AttributeError):
            pass
    # Model ignored the format: speak the plain text.
    return {"say": raw[:400], "action": None}


def ask(text: str) -> dict:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *_history,
                {"role": "user", "content": text}]
    resp = _llm().chat.completions.create(
        model=config.NVIDIA_MODEL,
        messages=messages,
        temperature=0.4,
        max_tokens=250,
    )
    raw = resp.choices[0].message.content or ""
    reply = parse_reply(raw)
    _history.append({"role": "user", "content": text})
    _history.append({"role": "assistant", "content": json.dumps(reply, ensure_ascii=False)})
    return reply
