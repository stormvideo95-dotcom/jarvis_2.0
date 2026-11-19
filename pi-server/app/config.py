"""All Jarvis settings come from environment variables (see .env.example)."""
import os


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


NVIDIA_API_KEY = _env("NVIDIA_API_KEY")
NVIDIA_BASE_URL = _env("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
NVIDIA_MODEL = _env("NVIDIA_MODEL", "meta/llama-4-maverick-17b-128e-instruct")

# Whisper large v3 on build.nvidia.com (Riva gRPC)
STT_SERVER = _env("STT_SERVER", "grpc.nvcf.nvidia.com:443")
STT_FUNCTION_ID = _env("STT_FUNCTION_ID", "b702f636-f60c-4a3d-a6f4-f3568c13bd7d")
LANGUAGE = _env("LANGUAGE", "nl")  # "nl", "en" or "multi" (auto detect)

NEST_NAME = _env("NEST_NAME", "")  # friendly name in Google Home, e.g. "Kamer van Storm"
NEST_IP = _env("NEST_IP", "")      # optional, faster + more reliable than discovery

PUBLIC_URL = _env("PUBLIC_URL", "http://192.168.1.10:8790").rstrip("/")
PORT = int(_env("PORT", "8790"))
JARVIS_KEY = _env("JARVIS_KEY", "")  # shared secret the board sends

PIPER_VOICE = _env("PIPER_VOICE", "/voices/nl_BE-nathalie-medium.onnx")
AUDIO_DIR = _env("AUDIO_DIR", "/tmp/jarvis-audio")
# Written by `python -m app.pick_speaker`; overrides NEST_NAME / NEST_IP when present
SPEAKER_FILE = _env("SPEAKER_FILE", "/data/speaker.json")
