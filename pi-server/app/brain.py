"""The thinking part: NVIDIA cloud LLM that answers and picks an action."""
import json
import re
import time
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

        _client = OpenAI(base_url=config.NVIDIA_BASE_URL, api_key=config.NVIDIA_API_KEY,
                         timeout=15.0, max_retries=0)
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


# Tried in this order when the configured model is gone (NVIDIA removes old models).
PREFERRED_MODELS = [
    "google/gemma-4-31b-it",
    "mistralai/mistral-large-4-1t-a52b",
    "z-ai/glm-5.3-flash",
    "minimaxai/minimax-m3.1-flash",
    "nvidia/nemotron-3.5-lightning-30b-a3b",
    "moonshotai/kimi-k3.1-pro",
    "google/gemma-3-12b-it",
    "meta/llama-4-maverick-17b-128e-instruct",
    "nvidia/llama-3.3-nemotron-super-49b-v1.5",
]
_SKIP = ("translate", "detector", "pii", "calibration", "omni", "embed", "rerank", "guard", "safety", "vision", "-vl", "coder", "reward", "parse", "retriev", "clip")
_model = None  # model actually in use


def current_model() -> str:
    return _model or config.NVIDIA_MODEL


_available: list[str] | None = None


def _candidates() -> list[str]:
    """Configured model first, then the preferred models NVIDIA actually offers."""
    global _available
    if _available is None:
        try:
            ids = {m.id for m in _llm().models.list().data}
            extra = sorted(i for i in ids if ("instruct" in i or i.endswith("-it"))
                           and not any(s in i for s in _SKIP))
            _available = list(dict.fromkeys([m for m in PREFERRED_MODELS if m in ids] + extra))
        except Exception:
            _available = list(PREFERRED_MODELS)
    order = [current_model()] + [m for m in _available if m != current_model()]
    return order[:5]


def _chat(messages: list) -> str:
    """Try models until one answers within 15 s; remember the one that worked."""
    global _model
    last = None
    for model in _candidates():
        t = time.time()
        try:
            resp = _llm().chat.completions.create(
                model=model, messages=messages, temperature=0.4, max_tokens=400)
            if model != current_model():
                print(f"[jarvis] now using model {model}", flush=True)
                _model = model
            print(f"[jarvis] {model} answered in {time.time() - t:.1f}s", flush=True)
            return resp.choices[0].message.content or ""
        except Exception as e:  # timeout, gone, overloaded... try the next one
            print(f"[jarvis] {model} failed after {time.time() - t:.1f}s: {type(e).__name__} {e}"[:300], flush=True)
            last = e
    raise RuntimeError(f"no NVIDIA model answered: {last}")


def ask(text: str) -> dict:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *_history,
                {"role": "user", "content": text}]
    raw = _chat(messages)
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.S)  # reasoning models
    reply = parse_reply(raw)
    _history.append({"role": "user", "content": text})
    _history.append({"role": "assistant", "content": json.dumps(reply, ensure_ascii=False)})
    return reply
