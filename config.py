"""Centralised configuration. All secrets come from environment / .env file."""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass


def _req(name):
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Add it to /home/pi/pi-ai/.env"
        )
    return val


def _opt(name, default=None):
    return os.environ.get(name, default)


# --- Paths ---
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = str(BASE_DIR / "memory.db")
LOG_DIR = BASE_DIR

# --- LLM ---
GROQ_API_KEY = _req("GROQ_API_KEY")
GROQ_MODEL = _opt("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_VISION_MODEL  = _opt("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
SEARCH_MAX_RESULTS = int(_opt("SEARCH_MAX_RESULTS", "3"))

# --- Telegram ---
TELEGRAM_TOKEN = _req("TELEGRAM_TOKEN")
CHAT_ID = _req("CHAT_ID")

# --- External APIs ---
OWM_API_KEY = _req("OWM_API_KEY")
SPOTIFY_CLIENT_ID = _req("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = _req("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = _opt("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")

# --- Network ---
LAPTOP_MAC = _opt("LAPTOP_MAC", "AA-BB-CC-DD-EE-FF")
LAPTOP_TAILSCALE_IP = _opt("LAPTOP_TAILSCALE_IP", "")
PHONE_MAC = _opt("PHONE_MAC", "aa:bb:cc:dd:ee:ff")
TAILSCALE_IP = _opt("TAILSCALE_IP", "100.64.0.1")
SESSION_SERVER_PORT = int(_opt("SESSION_SERVER_PORT", "8765"))
SHUTDOWN_PORT = int(_opt("SHUTDOWN_PORT", "8766"))
SESSION_SHARED_SECRET = _opt("SESSION_SHARED_SECRET", "")  # optional defense-in-depth

# --- Schedule anchor ---
# A known săpt-1 Monday: ISO Monday in săpt 1. Override with config if needed.
# Default uses 2026-04-27 (ISO week 18) as a săpt 1 Monday.
SAPT1_ANCHOR = _opt("SAPT1_ANCHOR", "2026-04-27")

# --- Tunables (magic numbers centralised) ---
HEARTBEAT_INTERVAL_MIN = int(_opt("HEARTBEAT_INTERVAL_MIN", "10"))
PRESENCE_INTERVAL_MIN = int(_opt("PRESENCE_INTERVAL_MIN", "2"))
QUIET_HOURS_START = int(_opt("QUIET_HOURS_START", "2"))
QUIET_HOURS_END = int(_opt("QUIET_HOURS_END", "9"))
RECENT_ACTIVE_COOLDOWN_MIN = int(_opt("RECENT_ACTIVE_COOLDOWN_MIN", "90"))
AWAY_THRESHOLD_MIN = int(_opt("AWAY_THRESHOLD_MIN", "25"))
AWAY_DEBOUNCE_SCANS = int(_opt("AWAY_DEBOUNCE_SCANS", "3"))
SESSION_STALE_SEC = int(_opt("SESSION_STALE_SEC", "300"))
SESSION_KEEP_ROWS = int(_opt("SESSION_KEEP_ROWS", "50"))
ECHO_OVERLAP_THRESHOLD = float(_opt("ECHO_OVERLAP_THRESHOLD", "0.6"))
ECHO_MIN_USER_WORDS = int(_opt("ECHO_MIN_USER_WORDS", "5"))
PATTERN_TRIGGER_PROBABILITY = float(_opt("PATTERN_TRIGGER_PROBABILITY", "0.30"))
IN_CHARACTER_MAX_CHARS = int(_opt("IN_CHARACTER_MAX_CHARS", "220"))
IN_CHARACTER_MAX_CHARS_LONG = int(_opt("IN_CHARACTER_MAX_CHARS_LONG", "500"))
LONG_USER_MESSAGE_THRESHOLD = int(_opt("LONG_USER_MESSAGE_THRESHOLD", "40"))
LLM_LOG_MAX_BYTES = int(_opt("LLM_LOG_MAX_BYTES", str(5 * 1024 * 1024)))
APP_LOG_MAX_BYTES = int(_opt("APP_LOG_MAX_BYTES", str(2 * 1024 * 1024)))
APP_LOG_BACKUPS = int(_opt("APP_LOG_BACKUPS", "3"))
PATTERN_LOG_MAX_ROWS = int(_opt("PATTERN_LOG_MAX_ROWS", "500"))
WEEKLY_PROFILE_MAX_ROWS = int(_opt("WEEKLY_PROFILE_MAX_ROWS", "26"))
FACT_DECAY_DAYS = int(_opt("FACT_DECAY_DAYS", "30"))
FACT_DECAY_FLOOR = float(_opt("FACT_DECAY_FLOOR", "0.2"))
