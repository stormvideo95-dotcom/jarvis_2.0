"""Speech to text with NVIDIA's hosted Whisper large v3 (Riva gRPC)."""
import io
import wave

from . import config


def wav_to_pcm(data: bytes) -> tuple[bytes, int]:
    """Return (raw 16-bit mono PCM, sample rate). Accepts WAV or raw 16 kHz PCM."""
    if data[:4] == b"RIFF":
        with wave.open(io.BytesIO(data), "rb") as w:
            return w.readframes(w.getnframes()), w.getframerate()
    return data, 16000


_asr = None


def _service():
    global _asr
    if _asr is None:
        import riva.client

        auth = riva.client.Auth(
            uri=config.STT_SERVER,
            use_ssl=True,
            metadata_args=[
                ["function-id", config.STT_FUNCTION_ID],
                ["authorization", f"Bearer {config.NVIDIA_API_KEY}"],
            ],
        )
        _asr = riva.client.ASRService(auth)
    return _asr


def transcribe(pcm: bytes, rate: int = 16000) -> str:
    import riva.client

    cfg = riva.client.RecognitionConfig(
        encoding=riva.client.AudioEncoding.LINEAR_PCM,
        sample_rate_hertz=rate,
        language_code=config.LANGUAGE,
        max_alternatives=1,
        enable_automatic_punctuation=True,
        audio_channel_count=1,
    )
    resp = _service().offline_recognize(pcm, cfg)
    parts = [r.alternatives[0].transcript for r in resp.results if r.alternatives]
    return " ".join(p.strip() for p in parts).strip()
