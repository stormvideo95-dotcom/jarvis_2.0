"""Text to speech with Piper (runs locally on the Pi).

Flemish voice for everything, except text wrapped in [[fr:...]], which gets a
French voice (so "la cheville" sounds French). Falls back to the Flemish voice
when no French voice is installed.
"""
import io
import os
import re
import wave

from . import config

_voices = {}


def _voice(lang: str):
    path = config.PIPER_VOICE_FR if lang == "fr" else config.PIPER_VOICE
    if lang == "fr" and not os.path.exists(path):
        path = config.PIPER_VOICE
    if path not in _voices:
        from piper import PiperVoice

        _voices[path] = PiperVoice.load(path)
    return _voices[path]


def _synth(text: str, lang: str):
    """Return (pcm bytes, sample rate) for one piece of text."""
    buf = io.BytesIO()
    voice = _voice(lang)
    with wave.open(buf, "wb") as w:
        if hasattr(voice, "synthesize_wav"):  # piper-tts >= 1.3
            voice.synthesize_wav(text, w)
        else:                                  # older piper-tts
            voice.synthesize(text, w)
    buf.seek(0)
    with wave.open(buf, "rb") as r:
        return r.readframes(r.getnframes()), r.getframerate()


def _resample(pcm: bytes, src: int, dst: int) -> bytes:
    if src == dst or not pcm:
        return pcm
    import numpy as np

    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    n = int(len(x) * dst / src)
    y = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)
    return y.astype(np.int16).tobytes()


def segments(text: str) -> list[tuple[str, str]]:
    """'Het is [[fr:la cheville]].' -> [('Het is ', 'nl'), ('la cheville', 'fr'), ('.', 'nl')]"""
    out, pos = [], 0
    for m in re.finditer(r"\[\[fr:(.*?)\]\]", text):
        if m.start() > pos:
            out.append((text[pos:m.start()], "nl"))
        out.append((m.group(1), "fr"))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], "nl"))
    return [(t, l) for t, l in out if re.search(r"\w", t)]


def to_wav(text: str, path: str) -> float:
    """Write speech to a WAV file and return its length in seconds."""
    parts = segments(text) or [(text, "nl")]
    rate, pcm = None, b""
    for chunk, lang in parts:
        data, r = _synth(chunk.strip(), lang)
        if rate is None:
            rate = r
        pcm += _resample(data, r, rate) + b"\0\0" * int(rate * 0.08)   # tiny pause between voices
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return len(pcm) / 2 / rate
