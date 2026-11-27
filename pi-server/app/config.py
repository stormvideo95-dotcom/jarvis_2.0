"""All Jarvis settings come from environment variables (see .env.example)."""
import os


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


NVIDIA_API_KEY = _env("NVIDIA_API_KEY")
NVIDIA_BASE_URL = _env("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
NVIDIA_MODEL = _env("NVIDIA_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b")

# Whisper large v3 on build.nvidia.com (Riva gRPC)
STT_SERVER = _env("STT_SERVER", "grpc.nvcf.nvidia.com:443")
STT_FUNCTION_ID = _env("STT_FUNCTION_ID", "b702f636-f60c-4a3d-a6f4-f3568c13bd7d")
LANGUAGE = _env("LANGUAGE", "nl")  # "nl", "en" or "multi" (auto detect)

NEST_NAME = _env("NEST_NAME", "")  # friendly name in Google Home, e.g. "Kamer van Storm"
NEST_IP = _env("NEST_IP", "")      # optional, faster + more reliable than discovery

PUBLIC_URL = _env("PUBLIC_URL", "http://192.168.1.10:8790").rstrip("/")
PORT = int(_env("PORT", "8790"))
UDP_PORT = int(_env("UDP_PORT", "8791"))  # board mic stream in wake word mode
JARVIS_KEY = _env("JARVIS_KEY", "")  # shared secret the board sends

PIPER_VOICE = _env("PIPER_VOICE", "/voices/nl_BE-nathalie-medium.onnx")
PIPER_VOICE_FR = _env("PIPER_VOICE_FR", "/voices/fr_FR-siwis-medium.onnx")  # for French words
AUDIO_DIR = _env("AUDIO_DIR", "/tmp/jarvis-audio")
# Written by `python -m app.pick_speaker`; overrides NEST_NAME / NEST_IP when present
SPEAKER_FILE = _env("SPEAKER_FILE", "/data/speaker.json")

# Home Assistant (on the same Umbrel by default)
HA_URL = _env("HA_URL", "http://127.0.0.1:8123")
HA_TOKEN = _env("HA_TOKEN", "")
# Device types Jarvis may control. Locks, alarms, garage doors are left out on purpose.
HA_DOMAINS = {d.strip() for d in _env("HA_DOMAINS", "light,switch,scene,fan,climate,input_boolean").split(",") if d.strip()}

# Music AI taste server (same Pi) so Jarvis can take over / hand off songs
MUSIC_AI_URL = _env("MUSIC_AI_URL", "http://127.0.0.1:8765")

# Storm Study (study.ictstorm.com): leerstof + your mistakes/points for study mode
STUDY_URL = _env("STUDY_URL", "https://study.ictstorm.com")
STUDY_JARVIS_TOKEN = _env("STUDY_JARVIS_TOKEN", "")   # starts with jv_, keep it only in .env

# School buddy (Jarvis School app + LAB project site)
SCHOOL_SITE = _env("SCHOOL_SITE", "https://sites.google.com/labonderwijs.be/humanbody/homepage")
SCHOOL_ROUTE = _env("SCHOOL_ROUTE", "z")              # NW route on the project site: g, b or z
SCHOOL_WEEK1 = _env("SCHOOL_WEEK1", "2026-11-09")     # Monday of project week 1
SCHOOL_REMIND = _env("SCHOOL_REMIND", "19:00")         # evening-before-a-test reminder
SCHOOL_PLANNER_REMIND = _env("SCHOOL_PLANNER_REMIND", "18:00")  # Monday: "scan your planner"
VISION_MODEL = _env("VISION_MODEL", "")               # NVIDIA model that reads the scans (auto when empty)
# Google Drive: the Apps Script web app on storm.video95@gmail.com (see school-drive/README.md)
DRIVE_SCRIPT_URL = _env("DRIVE_SCRIPT_URL", "")
DRIVE_SECRET = _env("DRIVE_SECRET", "")
