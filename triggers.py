import random
from collections import deque
from datetime import datetime, timezone
import db_helpers
import schedule as uni_schedule
import spotify_sync
import weather_sync
from network_radar import phone_is_home
from config import (
    AWAY_THRESHOLD_MIN, AWAY_DEBOUNCE_SCANS,
    PATTERN_TRIGGER_PROBABILITY,
)


def _utc_to_local(ts_str):
    """SQLite CURRENT_TIMESTAMP is UTC. Convert to naive local datetime."""
    return (
        datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        .replace(tzinfo=timezone.utc)
        .astimezone()
        .replace(tzinfo=None)
    )


_recent_scans = deque(maxlen=AWAY_DEBOUNCE_SCANS)


def has_class_soon_trigger():
    cls = uni_schedule.has_class_soon(within_hours=1)
    if not cls:
        return False, ""
    trigger_key = f"class_soon_{datetime.now().strftime('%Y-%m-%d')}_{cls}"
    if db_helpers.was_proactive_attempted_today('class_soon', trigger_key):
        return False, ""
    return True, f"yo, {cls}", trigger_key


def new_artist_trigger():
    try:
        current_raw = spotify_sync.get_recent_tracks()
        if not current_raw or "unavailable" in current_raw.lower():
            return False, ""
        last_artist = db_helpers.get_proactive_state('last_artist')
        if not last_artist:
            return False, ""
        if db_helpers.was_proactive_attempted_today('new_artist', last_artist):
            return False, ""
        with db_helpers.get_conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM proactive_log "
                "WHERE trigger_type='new_artist' AND trigger_key=? "
                "AND timestamp > datetime('now', '-7 days')",
                (last_artist,)
            ).fetchone()[0]
        if count > 0:
            return False, ""
        trigger_context = f"noticed {last_artist} in the user's recent tracks — first time in over a week, bring it up"
        return True, trigger_context, last_artist
    except Exception:
        return False, ""


def weather_flip_trigger():
    try:
        change = weather_sync.get_weather_change()
        if not change:
            return False, ""
        trigger_key = f"weather_{datetime.now().strftime('%Y-%m-%d')}"
        if db_helpers.was_proactive_attempted_today('weather_flip', trigger_key):
            return False, ""
        return True, change["summary"], trigger_key
    except Exception:
        return False, ""


def late_night_trigger():
    now = datetime.now()
    hour, minute = now.hour, now.minute
    if not ((hour == 0 and minute >= 30) or (hour == 1 and minute <= 45)):
        return False, ""
    with db_helpers.get_conn() as conn:
        recent = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE timestamp > datetime('now', '-3 hours')"
        ).fetchone()[0]
        today_user = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE sender='user' AND timestamp >= date('now')"
        ).fetchone()[0]
    if recent > 0 or today_user == 0:
        return False, ""
    trigger_key = f"late_night_{now.strftime('%Y-%m-%d')}"
    if db_helpers.was_proactive_attempted_today('late_night', trigger_key):
        return False, ""
    return True, "still up?", trigger_key


def pattern_surface_trigger():
    if random.random() > PATTERN_TRIGGER_PROBABILITY:
        return False, ""
    trigger_key = f"pattern_{datetime.now().strftime('%Y-%m-%d')}"
    if db_helpers.was_proactive_attempted_today('pattern_surface', trigger_key):
        return False, ""
    # Bias toward recent patterns: pull last 10, weight by recency.
    with db_helpers.get_conn() as conn:
        rows = conn.execute(
            "SELECT pattern_description FROM pattern_log ORDER BY id DESC LIMIT 10"
        ).fetchall()
    if not rows:
        return False, ""
    weights = [10 - i for i in range(len(rows))]
    pick = random.choices([r[0] for r in rows], weights=weights, k=1)[0]
    return True, f"been noticing: {pick}", trigger_key


def open_thread_trigger():
    """Returns 4-tuple: (True, context, dedup_key, thread_id) so the caller
    can defer `update_thread_referenced` until after a successful send."""
    with db_helpers.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, description FROM open_threads "
            "WHERE status='open' AND (last_referenced IS NULL OR last_referenced < datetime('now', '-3 days')) "
            "ORDER BY RANDOM() LIMIT 1"
        ).fetchall()
    if not rows:
        return False, ""
    thread_id, description = rows[0]
    return True, f"yo, did you ever {description}?", f"thread_{thread_id}", thread_id


GAME_KEYWORDS = {'league', 'valorant', 'cs2', 'cyberpunk', 'fortnite', 'minecraft', 'overwatch'}


def session_trigger():
    snapshot = db_helpers.get_latest_session_snapshot()
    if not snapshot:
        return False, ""

    game = next(
        (app["name"] for app in snapshot
         if any(kw in app["name"].lower() for kw in GAME_KEYWORDS)),
        None
    )
    if not game:
        return False, ""

    trigger_key = f"gaming_session_{datetime.now().strftime('%Y-%m-%d')}"
    if db_helpers.was_proactive_attempted_today('session', trigger_key):
        return False, ""

    others = [app["name"] for app in snapshot if app["name"] != game]
    others_str = ", ".join(others[:3]) if others else "nothing else notable"
    return True, f"user just started a gaming session, {game} is running alongside {others_str}", trigger_key


def home_arrival_trigger():
    is_home = phone_is_home()
    if is_home is None:
        return False, ""

    _recent_scans.append(is_home)

    last = db_helpers.get_last_presence_event()
    now = datetime.now()

    if is_home:
        if last is None or last["event"] == "away":
            if last is not None:
                away_since = _utc_to_local(last["timestamp"])
                minutes_away = int((now - away_since).total_seconds() / 60)
            else:
                minutes_away = 0

            db_helpers.log_presence_event("home")

            if minutes_away < AWAY_THRESHOLD_MIN:
                return False, ""

            # Key is per-trip (tied to the away event's timestamp) so multiple
            # trips in the same day each get exactly one message.
            trip_key = f"home_arrival_{last['timestamp']}" if last else 'home_arrival_first'
            if db_helpers.was_proactive_attempted_today('home_arrival', trip_key):
                return False, ""

            hours = minutes_away // 60
            mins = minutes_away % 60
            duration_str = f"{hours}h {mins}min" if hours > 0 else f"{mins}min"
            arrival_time = now.strftime("%H:%M")
            context = f"user just got home at {arrival_time}, was out for {duration_str}"
            return True, context, trip_key
        return False, ""
    else:
        if len(_recent_scans) < AWAY_DEBOUNCE_SCANS or any(_recent_scans):
            return False, ""
        if last is None or last["event"] == "home":
            db_helpers.log_presence_event("away")
        return False, ""


ALL_TRIGGERS = [
    ('class_soon',      has_class_soon_trigger),
    ('new_artist',      new_artist_trigger),
    ('session',         session_trigger),
    ('weather_flip',    weather_flip_trigger),
    ('late_night',      late_night_trigger),
    ('pattern_surface', pattern_surface_trigger),
    ('open_thread',     open_thread_trigger),
]
