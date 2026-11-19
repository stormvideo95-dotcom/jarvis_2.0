"""Text to speech with Piper (runs locally on the Pi, fast, Flemish voice)."""
import wave

from . import config

_voice = None


def _load():
    global _voice
    if _voice is None:
        from piper import PiperVoice

        _voice = PiperVoice.load(config.PIPER_VOICE)
    return _voice


def to_wav(text: str, path: str) -> float:
    """Write speech to a WAV file and return its length in seconds."""
    voice = _load()
    with wave.open(path, "wb") as w:
        if hasattr(voice, "synthesize_wav"):  # piper-tts >= 1.3
            voice.synthesize_wav(text, w)
        else:                                  # older piper-tts
            voice.synthesize(text, w)
    with wave.open(path, "rb") as w:
        return w.getnframes() / float(w.getframerate())
