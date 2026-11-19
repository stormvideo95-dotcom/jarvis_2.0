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


# ---- announce Jarvis on the network so the board can find it (mDNS) --------
_zc = None


@app.on_event("startup")
def _announce_in_background():
    # zeroconf's blocking API must not run inside the server's event loop
    threading.Thread(target=announce, daemon=True).start()


def announce():
    global _zc
    try:
        import socket
        from urllib.parse import urlparse
        from zeroconf import ServiceInfo, Zeroconf

        host = urlparse(config.PUBLIC_URL).hostname
        info = ServiceInfo(
            "_jarvis._tcp.local.", "Jarvis._jarvis._tcp.local.",
            addresses=[socket.inet_aton(host)], port=config.PORT,
            properties={"v": "1"}, server="jarvis-pi.local.")
        _zc = Zeroconf()
        _zc.register_service(info, allow_name_change=True)
        log.info("announced Jarvis on the network at %s:%s", host, config.PORT)
    except Exception:
        log.exception("could not announce Jarvis via mDNS (board must use a fixed address)")


@app.on_event("shutdown")
def _unannounce_in_background():
    t = threading.Thread(target=unannounce, daemon=True)
    t.start()
    t.join(timeout=3)


def unannounce():
    if _zc:
        _zc.unregister_all_services()
        _zc.close()


# ---- API ------------------------------------------------------------------
board = {"last_seen": None, "ip": None, "fw": None, "rssi": None, "log": deque(maxlen=30)}


def _board_seen(request: Request, fw: str, rssi: str, events: str):
    board["last_seen"] = time.strftime("%H:%M:%S")
    board["ip"] = request.client.host if request.client else None
    board["fw"] = fw or board["fw"]
    board["rssi"] = rssi or board["rssi"]
    for ev in filter(None, (events or "").split("|")):
        board["log"].appendleft(ev[:120])


def _talk_background(body: bytes):
    try:
        handle_audio(body)
    except Exception as e:
        log.exception("talk failed")
        history.appendleft({"time": time.strftime("%H:%M:%S"), "heard": "",
                            "said": f"Fout: {type(e).__name__}: {e}"[:200], "action": "error"})


@app.post("/api/talk")
async def talk(request: Request, x_jarvis_key: str = Header(default=""),
               x_board_fw: str = Header(default=""), x_board_rssi: str = Header(default=""),
               x_board_log: str = Header(default="")):
    """Board sends audio; we answer at once and do the slow work in the background."""
    _check_key(x_jarvis_key)
    body = await request.body()
    _board_seen(request, x_board_fw, x_board_rssi, x_board_log)
    board["log"].appendleft(f"{time.strftime('%H:%M:%S')} audio {len(body)} bytes")
    threading.Thread(target=_talk_background, args=(body,), daemon=True).start()
    return {"ok": True}


@app.get("/api/board-ping")
def board_ping(request: Request, x_jarvis_key: str = Header(default=""),
               x_board_fw: str = Header(default=""), x_board_rssi: str = Header(default=""),
               x_board_log: str = Header(default="")):
    _check_key(x_jarvis_key)
    _board_seen(request, x_board_fw, x_board_rssi, x_board_log)
    return {"ok": True}


@app.get("/api/board")
def board_status():
    return {**{k: v for k, v in board.items() if k != "log"}, "log": list(board["log"])}


class TextIn(BaseModel):
    text: str


@app.post("/api/text")
async def text(msg: TextIn, x_jarvis_key: str = Header(default="")):
    """Type to Jarvis without the board (handy for testing)."""
    _check_key(x_jarvis_key)
    try:
        return await run_in_threadpool(handle_text, msg.text)
    except Exception as e:
        log.exception("text failed")
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


@app.get("/api/health")
def health():
    return {"ok": True, "nvidia_key": bool(config.NVIDIA_API_KEY), "model": brain.current_model(),
            "language": config.LANGUAGE,
            "nest": (lambda s: s["name"] or s["ip"] or "auto")(nest.chosen())}


@app.get("/api/history")
def get_history():
    return list(history)


@app.get("/", response_class=HTMLResponse)
def home():
    return (Path(__file__).parent / "status.html").read_text(encoding="utf-8")
