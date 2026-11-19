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


def _pick_model(failed: str) -> str | None:
    """Ask NVIDIA which models exist and pick the best available one."""
    try:
        ids = {m.id for m in _llm().models.list().data}
    except Exception:
        return None
    for m in PREFERRED_MODELS:
        if m in ids and m != failed:
            return m
    chat = sorted(i for i in ids if ("instruct" in i or i.endswith("-it")) and not any(s in i for s in _SKIP) and i != failed)
    return chat[0] if chat else None


def _chat(messages: list) -> str:
    global _model
    from openai import APIStatusError, NotFoundError

    for _ in range(3):
        model = current_model()
        try:
            resp = _llm().chat.completions.create(
                model=model, messages=messages, temperature=0.4, max_tokens=400)
            return resp.choices[0].message.content or ""
        except (NotFoundError, APIStatusError) as e:
            if getattr(e, "status_code", None) not in (404, 410):
                raise
            nxt = _pick_model(model)
            if not nxt:
                raise
            print(f"[jarvis] model {model} is gone ({e.status_code}), switching to {nxt}", flush=True)
            _model = nxt
    raise RuntimeError("no working NVIDIA model found")


def ask(text: str) -> dict:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *_history,
                {"role": "user", "content": text}]
    raw = _chat(messages)
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.S)  # reasoning models
    reply = parse_reply(raw)
    _history.append({"role": "user", "content": text})
    _history.append({"role": "assistant", "content": json.dumps(reply, ensure_ascii=False)})
    return reply
