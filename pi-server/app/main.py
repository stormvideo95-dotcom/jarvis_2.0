"""Jarvis server for the Umbrel Pi 5.

Board (hold BOOT, talk) --WAV--> POST /api/talk --> NVIDIA Whisper (speech->text)
--> NVIDIA LLM (answer + action) --> Piper (text->speech) --> cast to Nest Mini.
"""
import logging
import os
import re
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

from . import brain, config, guard, ha, music, musicsync, school, settings, storm_study, study, stt, tts
from .wake import WakeListener
from .nest import Nest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("jarvis")

AUDIO = Path(config.AUDIO_DIR)
AUDIO.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Jarvis 2.0")
app.mount("/audio", StaticFiles(directory=AUDIO), name="audio")
os.makedirs(music.CACHE, exist_ok=True)
app.mount("/media", StaticFiles(directory=music.CACHE), name="media")   # songs for the Nest
app.mount("/school", StaticFiles(directory=Path(__file__).parent / "school_web", html=True), name="school")   # Jarvis School web chat
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
    nest.speak(f"{config.PUBLIC_URL}/audio/{name}", seconds, then=then, text=text)
    _cleanup_audio()


def _play_query(query: str):
    track = music.search(query)
    if track:
        nest.play_track(track)
    else:
        say("Ik vond daar geen muziek voor.")


# ---- study mode -----------------------------------------------------------
study_wait = threading.Event()   # set when Jarvis finished asking and waits for your answer


def listen_say(text: str):
    """Say something and then listen for the answer (no wake word / button needed)."""
    study_wait.clear()
    say(text, then=study_wait.set)


def study_say(text: str):
    """Say something in study mode; afterwards listen for the answer by itself."""
    study_wait.clear()
    if study.session.active:
        say(text, then=study_wait.set)
    else:
        say(text)


def _after_study():
    """School quiz finished: put the score and the mistakes in the app chat."""
    s = study.session
    if not s.active and s.material and not getattr(s, "_reported", False):
        s._reported = True
        school.quiz_done(s.missed, s.correct, s.answered)


def _study_silence():
    if study.session.active:
        study_say(study.session.silence())
        _after_study()
    elif guard.pending:
        guard.pending.clear()
    elif school.pending:
        school.pending.clear()


def _study_stopped_by_voice():
    nest.stop_speaking()
    if study.session.active:
        study_wait.clear()
        time.sleep(0.6)
        say(study.session.stop())
        _after_study()


def _play_tracks(tracks: list, start_ms: int = 0):
    track = music.set_queue(tracks)
    if track:
        nest.play_track(track, start_ms / 1000.0)
    else:
        say("Dat nummer kon ik niet afspelen.")


def _music_command(cmd: dict):
    """'Play on Jarvis (Nest)' from the Music AI app."""
    action = cmd.get("action")
    if action == "play":
        tracks = ([cmd["track"]] if cmd.get("track") else []) + (cmd.get("queue") or [])
        if tracks:
            log.info("Music AI: play from %s", cmd.get("from"))
            _play_tracks(tracks, int(cmd.get("positionMs") or 0))
    elif action == "pause":
        try:
            nest.pause()
        except Exception:
            pass


def _music_state() -> dict:
    cur = music.current()
    try:
        state, pos = nest.music_status() if cur else (None, 0.0)
    except Exception:
        state, pos = None, 0.0
    return {"track": cur if state else None, "positionMs": int(pos * 1000),
            "playing": state in ("PLAYING", "BUFFERING"),
            "queue": music.upcoming() if state else [], "updatedAt": int(time.time() * 1000)}


def _autoplay_loop():
    """When Jarvis' song finishes on the Nest, play the next one in the queue."""
    while True:
        time.sleep(3)
        try:
            state, _ = nest.music_status()
            if state == "FINISHED":
                nxt = music.next_track()
                if nxt:
                    nest.play_track(nxt)
                else:
                    nest.music = None
        except Exception:
            pass


@app.on_event("startup")
def _start_music():
    musicsync.start(_music_command, _music_state)
    threading.Thread(target=_autoplay_loop, daemon=True).start()


def _skip():
    track = music.next_track()
    if track:
        nest.play_track(track)
    else:
        say("Geen volgend nummer meer.")


_STUDY_WORDS = r"(study|studie|studi|studeer|stadie|stuudie|city|sturie|stoerie|studio|3|drie)"
_MODE_WORDS = r"(mode|modus|mood|moed|modes|mot)"


def quick_intent(text: str):
    """Catch study-mode commands even when speech recognition mangles them."""
    t = study._plain(text)
    if re.search(_STUDY_WORDS + r"\s*" + _MODE_WORDS, t) or re.search(r"\bstudiemodus\b|\bstudeermodus\b", t) \
            or (re.search(r"\bweek\s+\w+", t) and re.search(r"\b(studeer|studeren|leren|oefen|oefenen|quiz)\b", t)):
        if re.search(r"\b(update|updaten|vernieuw|vernieuwen|ophalen|nieuwe leerstof)\b", t):
            return "study_update"
        if re.search(r"\b(stop|uit|stoppen)\b", t) and not re.search(r"\b(start|aan|begin|activeer|activate)\b", t):
            return None
        return "study_start"
    return None


def _entry(text, said, action):
    e = {"time": time.strftime("%H:%M:%S"), "heard": text, "said": study.clean(said), "action": action}
    history.appendleft(e)
    return e


def _guard_reply(answer: str, wait: bool, text: str, action: str) -> dict:
    (listen_say if wait else say)(answer)
    return _entry(text, answer, action)


_UNLOCK_WORDS = r"\b(unlock|ontgrendel|ontgrendelen|open|openen|vrijgeven|mag ik|kan ik|scrollen|scroll|deblokkeer)\b"


def _start_school_quiz(text: str, quiz: dict) -> dict:
    if not quiz.get("material"):
        answer = "Ik vond geen succescriteria op de projectsite. Zeg start study mode om met Storm Study te oefenen."
        say(answer)
        return _entry(text, answer, "school")
    answer = study.session.start_school(quiz["label"], quiz["material"], 10, quiz.get("french", False))
    study_say(answer)
    _after_study()
    return _entry(text, answer, "school_quiz")


def handle_text(text: str) -> dict:
    if school.pending and not study.session.active:
        res = school.answer_pending(text)
        if res:
            if res["quiz"]:
                return _start_school_quiz(text, res["quiz"])
            say(res["say"])
            return _entry(text, res["say"], "school")
    if guard.pending and not study.session.active:
        res = guard.answer_pending(text)
        if res:
            return _guard_reply(res[0], res[1], text, "guard")
    if not study.session.active and re.search(_UNLOCK_WORDS, study._plain(text)) and guard.find_app(text):
        answer, wait = guard.voice_unlock(guard.find_app(text), guard.parse_minutes(text))
        return _guard_reply(answer, wait, text, "guard_unlock")
    intent = None if study.session.active else quick_intent(text)
    if intent == "study_start":
        answer = study.session.start(text)
        study_say(answer)
        entry = {"time": time.strftime("%H:%M:%S"), "heard": text, "said": study.clean(answer), "action": "study_start"}
        history.appendleft(entry)
        return entry
    if intent == "study_update":
        say("Even kijken op Storm Study.")
        answer = storm_study.update()
        say(answer)
        entry = {"time": time.strftime("%H:%M:%S"), "heard": text, "said": answer, "action": "study_update"}
        history.appendleft(entry)
        return entry
    if study.session.active:
        answer = study.session.handle(text)
        study_say(answer)
        _after_study()
        entry = {"time": time.strftime("%H:%M:%S"), "heard": text, "said": study.clean(answer), "action": "study"}
        history.appendleft(entry)
        return entry
    reply = brain.ask(text, ha.prompt_block() + musicsync.prompt_block() + guard.prompt_block())
    action = reply["action"] or {}
    kind = action.get("type")
    log.info("heard=%r say=%r action=%r", text, reply["say"], action)

    if kind in SILENT_ACTIONS:
        {"pause": nest.pause, "resume": nest.resume, "stop": nest.stop, "skip": _skip,
         "volume": lambda: nest.volume(action.get("level", 50))}[kind]()
    elif kind == "home":
        problem = ha.run(action) if ha.enabled() else "Home Assistant is nog niet gekoppeld."
        say(problem or reply["say"])
    elif kind == "guard_unlock":
        app = action.get("app") if action.get("app") in list(guard.APPS) + ["all"] else guard.find_app(text)
        minutes = action.get("minutes") if isinstance(action.get("minutes"), (int, float)) else guard.parse_minutes(text)
        reply["say"], wait = guard.voice_unlock(app, minutes)
        (listen_say if wait else say)(reply["say"])
    elif kind == "guard_lock":
        app = action.get("app") if action.get("app") in list(guard.APPS) + ["all"] else (guard.find_app(text) or "all")
        guard.lock(app)
        reply["say"] = "Alles staat weer op slot." if app == "all" else f"{guard.APPS[app][0]} staat weer op slot."
        say(reply["say"])
    elif kind == "guard_status":
        reply["say"] = guard.voice_status()
        say(reply["say"])
    elif kind == "study_start":
        reply["say"] = study.session.start(text)
        study_say(reply["say"])
    elif kind == "school":
        res = school.ask(text, voice=True)
        if res.get("quiz"):
            say(res["text"], then=lambda: _start_school_quiz(text, school.quiz_for(res["quiz"])))
        else:
            say(res["text"])
        reply["say"] = res["text"]
    elif kind == "study_update":
        say("Even kijken op Storm Study.")
        reply["say"] = storm_study.update()
        say(reply["say"])
    elif kind == "music_from":
        tracks, start_ms, dev = musicsync.take_from(action.get("device", ""))
        if not dev:
            say("Ik vond dat toestel niet in Music AI.")
        elif not tracks:
            say(f"Er speelt niets op {dev['name']}.")
        else:
            say(reply["say"], then=lambda: _play_tracks(tracks, start_ms))
    elif kind == "music_to":
        cur = music.current()
        state, pos = nest.music_status() if cur else (None, 0.0)
        if not cur or state is None:
            say("Er speelt hier nu geen muziek om door te geven.")
        else:
            dev = musicsync.send_to(action.get("device", ""), cur, int(pos * 1000), music.upcoming())
            if dev:
                nest.stop()
                say(reply["say"] or f"Het speelt nu verder op {dev['name']}.")
            else:
                say("Ik vond dat toestel niet in Music AI.")
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

    entry = {"time": time.strftime("%H:%M:%S"), "heard": text, "said": study.clean(reply["say"]), "action": kind}
    history.appendleft(entry)
    return entry


def handle_audio(body: bytes) -> dict:
    pcm, rate = stt.wav_to_pcm(body)
    if len(pcm) < rate * 2 * 0.3:  # under 0.3 s: button tap, ignore
        return {"heard": "", "said": "", "action": None}
    text = stt.transcribe(pcm, rate)
    if study.session.active and not study.session.understands(text):
        # short answers ("mix", "B") are often misheard in Dutch: try English too
        try:
            alt = stt.transcribe(pcm, rate, language="en")
            if alt and study.session.understands(alt):
                log.info("study: used English transcription %r instead of %r", alt, text)
                text = alt
        except Exception:
            pass
    if not text and study.session.active:
        study_say("Ik verstond je niet. Zeg het nog eens?")
        return {"heard": "", "said": "Ik verstond je niet.", "action": "study"}
    if not text:
        say("Sorry, ik verstond je niet.")
        return {"heard": "", "said": "Sorry, ik verstond je niet.", "action": None}
    return handle_text(text)


# ---- wake word mode ----------------------------------------------------------
def _make_ding() -> str:
    """Short two-tone 'ding' the Nest plays when the wake word is heard."""
    import math
    import wave as _w
    path = AUDIO / "ding.wav"
    if not path.exists():
        frames = bytearray()
        for f, dur in ((880, 0.09), (1320, 0.14)):
            for i in range(int(16000 * dur)):
                env = min(1.0, i / 160) * (1 - i / (16000 * dur))
                v = int(9000 * env * math.sin(2 * math.pi * f * i / 16000))
                frames += v.to_bytes(2, "little", signed=True)
        with _w.open(str(path), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(bytes(frames))
    return f"{config.PUBLIC_URL}/audio/ding.wav"


def _on_wake():
    try:
        nest.speak(_make_ding(), 0.25)
    except Exception:
        log.exception("ding failed")


def _on_wake_command(wav: bytes):
    _talk_background(wav)


wake = WakeListener(_on_wake_command, on_wake=_on_wake,
                    on_event=lambda msg: board["log"].appendleft(msg),
                    talking=lambda: nest.talking(), on_stop=_study_stopped_by_voice,
                    transcribe=lambda pcm, rate: stt.transcribe(pcm, rate),
                    expect=study_wait, on_silence=_study_silence)


@app.on_event("startup")
def _start_school():
    school.start_reminders(say, listen_say)


@app.on_event("startup")
def _start_wake():
    try:
        wake.start(config.UDP_PORT)
    except Exception:
        log.exception("could not start wake word listener")


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
    cfg = settings.get()
    mode = "wake" if (cfg["mode"] == "wake" or study.session.active) else "button"
    return {"ok": True, "mode": mode, "udp": config.UDP_PORT}


@app.get("/api/board")
def board_status():
    return {**{k: v for k, v in board.items() if k != "log"}, "log": list(board["log"]),
            "wake": wake.status()}


# ---- TimeGuard (phone + Mac apps) ---------------------------------------------
@app.get("/api/guard/status")
def guard_status(device: str = "", x_jarvis_key: str = Header(default="")):
    _check_key(x_jarvis_key)
    return guard.status(device or None)


@app.post("/api/guard/usage")
async def guard_usage(request: Request, x_jarvis_key: str = Header(default="")):
    _check_key(x_jarvis_key)
    body = await request.json()
    return guard.report(str(body.get("device") or "?")[:30], body.get("items") or [])


@app.post("/api/guard/settings")
async def guard_settings(request: Request, x_jarvis_key: str = Header(default="")):
    _check_key(x_jarvis_key)
    body = await request.json()
    return guard.settings(body.get("enabled"), body.get("limit_min"))


@app.post("/api/guard/lock")
def guard_lock_all(x_jarvis_key: str = Header(default="")):
    _check_key(x_jarvis_key)
    guard.lock("all")
    return guard.status()


@app.get("/api/guard/public")
def guard_public():
    st = guard.status()
    return {"remaining_min": st["remaining_min"], "limit_min": st["limit_min"], "open": list(st["grants"])}


@app.get("/guard/blocked", response_class=HTMLResponse)
def guard_blocked(app_name: str = ""):
    return (Path(__file__).parent / "blocked.html").read_text(encoding="utf-8")


class TextIn(BaseModel):
    text: str


# ---- Jarvis School app ----------------------------------------------------------
@app.get("/api/school/state")
def school_state(x_jarvis_key: str = Header(default="")):
    _check_key(x_jarvis_key)
    return school.state()


@app.get("/api/school/chat")
def school_chat_history(after: str = "", x_jarvis_key: str = Header(default="")):
    _check_key(x_jarvis_key)
    return school.chat_history(after)


@app.post("/api/school/chat")
async def school_chat(msg: TextIn, x_jarvis_key: str = Header(default="")):
    _check_key(x_jarvis_key)
    text = msg.text.strip()[:2000]
    if not text:
        raise HTTPException(status_code=400, detail="empty")
    return await run_in_threadpool(school.ask, text)


class UploadIn(BaseModel):
    kind: str
    week: int | None = None
    pdf: str
    pages: list[str] = []


@app.post("/api/school/upload")
async def school_upload(body: UploadIn, x_jarvis_key: str = Header(default="")):
    _check_key(x_jarvis_key)
    try:
        return await run_in_threadpool(school.upload, body.kind, body.week, body.pdf, body.pages)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/school/file")
def school_file(week: int, name: str, key: str = ""):
    _check_key(key)
    from fastapi.responses import FileResponse
    path = school.file_path(week, name)
    if not path:
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path, media_type="application/pdf", filename=os.path.basename(path))


@app.get("/api/settings")
def get_settings():
    return {**settings.get(), "wake_words": settings.WAKE_WORDS}


@app.post("/api/settings")
async def set_settings(request: Request, x_jarvis_key: str = Header(default="")):
    _check_key(x_jarvis_key)
    cfg = settings.update(await request.json())
    board["log"].appendleft(f"{time.strftime('%H:%M:%S')} settings: {cfg['mode']}, {cfg['wake_word']}")
    return {**cfg, "wake_words": settings.WAKE_WORDS}


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
            "home_assistant": ("verbonden" if ha.ping() else "fout") if ha.enabled() else "niet gekoppeld",
            "music_ai": musicsync.status(),
            "study": ({"subject": study.session.label(), "game": study.session.game, "n": study.session.n,
                       "answered": study.session.answered, "correct": study.session.correct}
                      if study.session.active else None),
            "storm_study": storm_study.status(),
            "school": school.status(),
            "guard": {k: v for k, v in guard.status().items() if k != "apps"},
            "nest": (lambda s: s["name"] or s["ip"] or "auto")(nest.chosen())}


@app.get("/api/history")
def get_history():
    return list(history)


@app.get("/", response_class=HTMLResponse)
def home():
    return (Path(__file__).parent / "status.html").read_text(encoding="utf-8")
