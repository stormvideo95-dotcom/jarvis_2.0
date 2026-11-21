"""Wake word mode: the board streams its mic over UDP, the Pi listens for the word.

Packet from the board: 16 bytes Jarvis key (zero padded) + 16-bit mono PCM at 16 kHz.
When the wake word is heard, Jarvis plays a short ding and records until you stop
talking (or 8 s), then handles it exactly like a BOOT-button recording.
"""
import io
import logging
import math
import socket
import struct
import threading
import time
import wave

from . import config, settings

log = logging.getLogger("jarvis.wake")

RATE = 16000
FRAME = 1280                 # 80 ms, what openWakeWord wants
SILENCE_RMS = 500            # below this counts as silence
END_SILENCE_S = 0.9          # stop recording after this much silence
MAX_RECORD_S = 8.0
NO_SPEECH_GIVE_UP_S = 4.0    # heard the word but nothing after it
COOLDOWN_S = 2.5
ANSWER_GIVE_UP_S = 9.0       # study mode: how long to wait for your answer


def _rms(pcm: bytes) -> float:
    n = len(pcm) // 2
    if n == 0:
        return 0.0
    samples = struct.unpack(f"<{n}h", pcm[: n * 2])
    return math.sqrt(sum(s * s for s in samples) / n)


def to_wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return buf.getvalue()


STOP_WORDS = ("stop", "zwijg", "hou op", "houd op", "genoeg", "shut up", "be quiet")
STOP_WINDOW_S = 1.6          # audio checked for "stop" while Jarvis talks
STOP_EVERY_S = 1.0


class WakeListener:
    def __init__(self, on_command, on_wake=None, on_event=None,
                 talking=None, on_stop=None, transcribe=None, expect=None, on_silence=None):
        self.on_command = on_command   # called with WAV bytes after the wake word
        self.on_wake = on_wake          # called right when the word is heard (ding)
        self.on_event = on_event or (lambda msg: None)
        self._model = None
        self._model_word = None
        self._buf = b""
        self._state = "idle"            # idle | recording | busy
        self._rec = b""
        self._rec_start = 0.0
        self._last_voice = 0.0
        self._heard_voice = False
        self._cooldown_until = 0.0
        self.last_packet = 0.0
        self.last_score = 0.0
        self.key = config.JARVIS_KEY.encode()[:16].ljust(16, b"\0")
        self.talking = talking          # () -> text Jarvis is saying, or None
        self.on_stop = on_stop
        self.transcribe = transcribe
        self._sbuf = b""
        self._last_stop_check = 0.0
        self._stop_busy = False
        self.expect = expect            # threading.Event: Jarvis asked something, record the answer
        self.on_silence = on_silence    # called when no answer came
        self._answer_mode = False

    # ---- model ------------------------------------------------------------
    def _ensure_model(self, word: str):
        if self._model is not None and self._model_word == word:
            return
        from openwakeword.model import Model

        self._model = Model(wakeword_models=[word], inference_framework="onnx")
        self._model_word = word
        log.info("wake word model loaded: %s", word)

    # ---- audio in ---------------------------------------------------------
    def feed(self, pcm: bytes):
        """Feed raw 16 kHz PCM (any length)."""
        self.last_packet = time.time()
        said = self.talking() if self.talking else None
        if said is not None and self._state != "recording":
            self._watch_for_stop(pcm, said)
            return
        self._sbuf = b""
        if self._state == "recording":
            self._record(pcm)
            return
        if self._state == "idle" and self.expect is not None and self.expect.is_set():
            self.expect.clear()
            self._start_answer()
            self._record(pcm)
            return
        cfg = settings.get()
        if cfg["mode"] != "wake":
            return
        if self._state == "busy" or time.time() < self._cooldown_until:
            return
        self._buf += pcm
        import numpy as np

        self._ensure_model(cfg["wake_word"])
        while len(self._buf) >= FRAME * 2:
            frame, self._buf = self._buf[: FRAME * 2], self._buf[FRAME * 2:]
            scores = self._model.predict(np.frombuffer(frame, dtype=np.int16))
            score = max(scores.values()) if scores else 0.0
            self.last_score = max(self.last_score * 0.9, score)
            if score >= cfg["sensitivity"]:
                self._start_recording(score)
                break

    # ---- "stop" while Jarvis talks --------------------------------------------
    def _watch_for_stop(self, pcm: bytes, said: str):
        self._sbuf = (self._sbuf + pcm)[-int(STOP_WINDOW_S * RATE * 2):]
        now = time.time()
        if (self._stop_busy or not self.transcribe or now - self._last_stop_check < STOP_EVERY_S
                or len(self._sbuf) < RATE or _rms(self._sbuf) < SILENCE_RMS):
            return
        self._last_stop_check = now
        self._stop_busy = True
        window = self._sbuf
        said_low = (said or "").lower()

        def check():
            try:
                heard = (self.transcribe(window, RATE) or "").lower()
                hit = next((w for w in STOP_WORDS if w in heard and w not in said_low), None)
                if hit:
                    log.info("stop heard: %r", heard)
                    self.on_event(f"{time.strftime('%H:%M:%S')} STOP heard ('{heard[:40]}')")
                    self._sbuf = b""
                    if self.on_stop:
                        self.on_stop()
            except Exception:
                log.debug("stop check failed", exc_info=True)
            finally:
                self._stop_busy = False
        self.expect = expect            # threading.Event: Jarvis asked something, record the answer
        self.on_silence = on_silence    # called when no answer came
        self._answer_mode = False
        threading.Thread(target=check, daemon=True).start()

    def _start_answer(self):
        """Jarvis asked a question (study mode): record the reply without a wake word."""
        self.on_event(f"{time.strftime('%H:%M:%S')} listening for your answer")
        self._state = "recording"
        self._answer_mode = True
        self._rec = b""
        self._buf = b""
        self._rec_start = self._last_voice = time.time()
        self._heard_voice = False

    def _start_recording(self, score: float):
        log.info("wake word heard (score %.2f)", score)
        self.on_event(f"{time.strftime('%H:%M:%S')} wake word heard ({score:.2f})")
        self._state = "recording"
        self._rec = self._buf      # whatever came right after the word
        self._buf = b""
        self._rec_start = self._last_voice = time.time()
        self._heard_voice = False
        self._answer_mode = False
        try:
            self._model.reset()
        except Exception:
            pass
        if self.on_wake:
            threading.Thread(target=self.on_wake, daemon=True).start()

    def _record(self, pcm: bytes):
        self._rec += pcm
        now = time.time()
        if _rms(pcm) > SILENCE_RMS:
            self._last_voice = now
            self._heard_voice = True
        took = now - self._rec_start
        done = (self._heard_voice and now - self._last_voice > END_SILENCE_S) or took > MAX_RECORD_S
        give_up = ANSWER_GIVE_UP_S if self._answer_mode else NO_SPEECH_GIVE_UP_S
        if not self._heard_voice and took > give_up:
            was_answer = self._answer_mode
            self.on_event(f"{time.strftime('%H:%M:%S')} " + ("no answer heard" if was_answer else "no question after the wake word"))
            self._finish()
            if was_answer and self.on_silence:
                threading.Thread(target=self.on_silence, daemon=True).start()
            return
        if done:
            audio = self._rec
            self._state = "busy"
            self.on_event(f"{time.strftime('%H:%M:%S')} recorded {len(audio) / (RATE * 2):.1f}s after wake word")

            def work():
                try:
                    self.on_command(to_wav(audio))
                finally:
                    self._finish()
            threading.Thread(target=work, daemon=True).start()

    def _finish(self):
        self._answer_mode = False
        self._rec = b""
        self._buf = b""
        self._state = "idle"
        self._cooldown_until = time.time() + COOLDOWN_S

    # ---- network ----------------------------------------------------------
    def serve(self, port: int):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", port))
        log.info("listening for board audio on UDP %s", port)
        while True:
            data, _ = sock.recvfrom(4096)
            if len(data) <= 16 or data[:16] != self.key:
                continue
            try:
                self.feed(data[16:])
            except Exception:
                log.exception("wake word processing failed")
                time.sleep(1)

    def start(self, port: int):
        threading.Thread(target=self.serve, args=(port,), daemon=True).start()

    def status(self) -> dict:
        return {"streaming": time.time() - self.last_packet < 3, "state": self._state,
                "score": round(self.last_score, 2)}
