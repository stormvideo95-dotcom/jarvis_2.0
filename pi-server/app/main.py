"""Jarvis server for the Umbrel Pi 5.

Board (hold BOOT, talk) --WAV--> POST /api/talk --> NVIDIA Whisper (speech->text)
--> NVIDIA LLM (answer + action) --> Piper (text->speech) --> cast to Nest Mini.
"""
import logging
import threading
import time
import uuid
from collections import deque
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import brain, config, music, stt, tts
from .nest import Nest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("jarvis")

AUDIO = Path(config.AUDIO_DIR)
AUDIO.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Jarvis 2.0")
app.mount("/audio", StaticFiles(directory=AUDIO), name="audio")
nest = Nest()
history: deque = deque(maxlen=20)

SILENT_ACTIONS = {"pause", "resume", "skip", "stop", "volume"}


def _check_key(key: str):
    if config.JARVIS_KEY and key != config.JARVIS_KEY:
        raise HTTPException(status_code=401, detail="wrong key")


def _cleanup_audio(keep: int = 20):
    files = sorted(AUDIO.glob("*.wav"), key=lambda p: p.stat().st_mtime)
    for old in files[:-keep]:
        old.unlink(missing_ok=True)


def say(text: str, then=None):
    if not text:
        if then:
            then()
        return
    name = f"{uuid.uuid4().hex}.wav"
    seconds = tts.to_wav(text, str(AUDIO / name))
    nest.speak(f"{config.PUBLIC_URL}/audio/{name}", seconds, then=then)
    _cleanup_audio()


def _play_query(query: str):
    track = music.search(query)
    if track:
        nest.play_track(track)
    else:
        say("Ik vond daar geen muziek voor.")


def _skip():
    track = music.next_track()
    if track:
        nest.play_track(track)
    else:
        say("Geen volgend nummer meer.")


def handle_text(text: str) -> dict:
    reply = brain.ask(text)
    action = reply["action"] or {}
    kind = action.get("type")
    log.info("heard=%r say=%r action=%r", text, reply["say"], action)

    if kind in SILENT_ACTIONS:
        {"pause": nest.pause, "resume": nest.resume, "stop": nest.stop, "skip": _skip,
         "volume": lambda: nest.volume(action.get("level", 50))}[kind]()
    elif kind == "play_music":
        query = action.get("query") or text
        say(reply["say"], then=lambda: _play_query(query))
    elif kind == "timer":
        seconds = max(1, int(action.get("seconds", 60)))
        label = action.get("label") or "je timer"
        threading.Timer(seconds, lambda: say(f"Hé Storm, {label} is voorbij.")).start()
        say(reply["say"])
    else:
        say(reply["say"])

    entry = {"time": time.strftime("%H:%M:%S"), "heard": text, "said": reply["say"], "action": kind}
    history.appendleft(entry)
    return entry


def handle_audio(body: bytes) -> dict:
    pcm, rate = stt.wav_to_pcm(body)
    if len(pcm) < rate * 2 * 0.3:  # under 0.3 s: button tap, ignore
        return {"heard": "", "said": "", "action": None}
    text = stt.transcribe(pcm, rate)
    if not text:
        say("Sorry, ik verstond je niet.")
        return {"heard": "", "said": "Sorry, ik verstond je niet.", "action": None}
    return handle_text(text)


# ---- API ------------------------------------------------------------------
@app.post("/api/talk")
async def talk(request: Request, x_jarvis_key: str = Header(default="")):
    _check_key(x_jarvis_key)
    body = await request.body()
    try:
        return await run_in_threadpool(handle_audio, body)
    except Exception as e:  # keep the board simple: always JSON back
        log.exception("talk failed")
        raise HTTPException(status_code=500, detail=str(e))


class TextIn(BaseModel):
    text: str


@app.post("/api/text")
async def text(msg: TextIn, x_jarvis_key: str = Header(default="")):
    """Type to Jarvis without the board (handy for testing)."""
    _check_key(x_jarvis_key)
    return await run_in_threadpool(handle_text, msg.text)


@app.get("/api/health")
def health():
    return {"ok": True, "nvidia_key": bool(config.NVIDIA_API_KEY), "model": config.NVIDIA_MODEL,
            "language": config.LANGUAGE,
            "nest": (lambda s: s["name"] or s["ip"] or "auto")(nest.chosen())}


@app.get("/api/history")
def get_history():
    return list(history)


@app.get("/", response_class=HTMLResponse)
def home():
    return (Path(__file__).parent / "status.html").read_text(encoding="utf-8")
