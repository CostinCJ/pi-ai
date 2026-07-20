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
GROQ_WHISPER_MODEL = _opt("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")
VOICE_MAX_SECONDS = int(_opt("VOICE_MAX_SECONDS", "60"))
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
DESKTOP_PUSH_URL = _opt("DESKTOP_PUSH_URL", "")  # e.g. http://100.x.x.x:8767/notify

# --- League of Legends (Riot API) ---
RIOT_API_KEY = _opt("RIOT_API_KEY", "")
RIOT_PUUID = _opt("RIOT_PUUID", "")
RIOT_REGION = _opt("RIOT_REGION", "europe")
RIOT_PLATFORM = _opt("RIOT_PLATFORM", "eun1")

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
SPOTIFY_POLL_INTERVAL_MIN = int(_opt("SPOTIFY_POLL_INTERVAL_MIN", "3"))
SPOTIFY_TRACKS_KEEP_DAYS = int(_opt("SPOTIFY_TRACKS_KEEP_DAYS", "30"))
SPOTIFY_CONTEXT_LIMIT = int(_opt("SPOTIFY_CONTEXT_LIMIT", "10"))

# --- Semester calendar ---
# Comma-separated date ranges (start:end, inclusive) when classes actually run.
# Outside these ranges class_soon never fires and /today reports break.
# Update each semester. Defaults: sem 2 spring 2026, sem 1 autumn 2026 (adjust
# start date when the official calendar is out).
SEMESTER_RANGES = _opt("SEMESTER_RANGES", "2026-02-23:2026-06-07,2026-09-28:2026-12-20")

# --- Engagement-aware proactive backoff ---
# If the last ENGAGEMENT_WINDOW delivered proactive messages got zero replies,
# Lache is being ignored: only high-value triggers, max BACKOFF_IGNORED_MAX_PER_DAY
# sends/day. Zero replies over ENGAGEMENT_DEAD_WINDOW: core triggers only,
# max BACKOFF_DEAD_MAX_PER_DAY/day. Any user reply resets to normal.
ENGAGEMENT_WINDOW = int(_opt("ENGAGEMENT_WINDOW", "10"))
ENGAGEMENT_DEAD_WINDOW = int(_opt("ENGAGEMENT_DEAD_WINDOW", "25"))
BACKOFF_IGNORED_MAX_PER_DAY = int(_opt("BACKOFF_IGNORED_MAX_PER_DAY", "2"))
BACKOFF_DEAD_MAX_PER_DAY = int(_opt("BACKOFF_DEAD_MAX_PER_DAY", "1"))

# --- Proactive repeat suppression ---
PROACTIVE_REPEAT_OVERLAP = float(_opt("PROACTIVE_REPEAT_OVERLAP", "0.6"))
PROACTIVE_REPEAT_DAYS = int(_opt("PROACTIVE_REPEAT_DAYS", "14"))

# --- Open thread expiry ---
THREAD_MAX_AGE_DAYS = int(_opt("THREAD_MAX_AGE_DAYS", "30"))

# --- Daily briefing ---
# BRIEFING_WINDOW_START/END and QUIET_HOURS_START/END are independently
# tunable — this window must stay outside quiet hours (defaults: quiet ends
# at QUIET_HOURS_END=9, window starts at BRIEFING_WINDOW_START=9) or the
# briefing tick will never get a chance to fire.
BRIEFING_WINDOW_START = int(_opt("BRIEFING_WINDOW_START", "9"))
BRIEFING_WINDOW_END = int(_opt("BRIEFING_WINDOW_END", "13"))  # send regardless at this hour
BRIEFING_SPOTIFY_ACTIVE_MIN = int(_opt("BRIEFING_SPOTIFY_ACTIVE_MIN", "20"))
