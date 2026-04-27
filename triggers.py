import random
from datetime import datetime, timedelta
import db_helpers
import schedule as uni_schedule
import spotify_sync
import weather_sync
from network_radar import phone_is_home


def has_class_soon_trigger():
    cls = uni_schedule.has_class_soon(within_hours=1)
    if not cls:
        return False, ""
    trigger_key = f"class_soon_{datetime.now().strftime('%Y-%m-%d')}_{cls}"
    if db_helpers.was_trigger_fired_today('class_soon', trigger_key):
        return False, ""
    return True, f"yo, {cls}"


def new_artist_trigger():
    try:
        current_raw = spotify_sync.get_recent_tracks()
        if not current_raw or "unavailable" in current_raw.lower():
            return False, ""
        last_artist = db_helpers.get_proactive_state('last_artist')
        if not last_artist:
            return False, ""
        trigger_context = f"first time hearing {last_artist} in a while, what made you put it on?"
        if db_helpers.was_proactive_attempted_today('new_artist', trigger_context[:100]):
            return False, ""
        # 7-day "have we already mentioned them recently" guard, kept from before.
        cutoff = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
        with db_helpers.get_conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM proactive_log WHERE trigger_type='new_artist' AND trigger_key=? AND timestamp > ?",
                (last_artist, cutoff)
            ).fetchone()[0]
        if count > 0:
            return False, ""
        return True, trigger_context
    except Exception:
        return False, ""


def weather_flip_trigger():
    try:
        change = weather_sync.get_weather_change()
        if not change:
            return False, ""
        trigger_key = f"weather_{datetime.now().strftime('%Y-%m-%d')}"
        if db_helpers.was_trigger_fired_today('weather_flip', trigger_key):
            return False, ""
        return True, change["summary"]
    except Exception:
        return False, ""


def late_night_trigger():
    now = datetime.now()
    hour, minute = now.hour, now.minute
    if not ((hour == 0 and minute >= 30) or (hour == 1 and minute <= 45)):
        return False, ""
    cutoff = (now - timedelta(hours=3)).strftime('%Y-%m-%d %H:%M:%S')
    with db_helpers.get_conn() as conn:
        recent = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE timestamp > ?",
            (cutoff,)
        ).fetchone()[0]
        today_user = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE sender='user' AND timestamp >= date('now')"
        ).fetchone()[0]
    if recent > 0 or today_user == 0:
        return False, ""
    trigger_key = f"late_night_{now.strftime('%Y-%m-%d')}"
    if db_helpers.was_trigger_fired_today('late_night', trigger_key):
        return False, ""
    return True, "still up?"


def pattern_surface_trigger():
    if random.random() > 0.30:
        return False, ""
    trigger_key = f"pattern_{datetime.now().strftime('%Y-%m-%d')}"
    if db_helpers.was_trigger_fired_today('pattern_surface', trigger_key):
        return False, ""
    with db_helpers.get_conn() as conn:
        row = conn.execute(
            "SELECT pattern_description FROM pattern_log ORDER BY RANDOM() LIMIT 1"
        ).fetchone()
    if not row:
        return False, ""
    return True, f"been noticing: {row[0]}"


def open_thread_trigger():
    cutoff = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d %H:%M:%S')
    with db_helpers.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, description FROM open_threads "
            "WHERE status='open' AND (last_referenced IS NULL OR last_referenced < ?) "
            "ORDER BY RANDOM() LIMIT 1",
            (cutoff,)
        ).fetchall()
    if not rows:
        return False, ""
    thread_id, description = rows[0]
    db_helpers.update_thread_referenced(thread_id)
    return True, f"yo, did you ever {description}?"


def home_arrival_trigger():
    is_home = phone_is_home()
    if is_home is None:
        return False, ""

    last = db_helpers.get_last_presence_event()
    now = datetime.now()

    if is_home:
        if last is None or last["event"] == "away":
            if last is not None:
                away_since = datetime.strptime(last["timestamp"], "%Y-%m-%d %H:%M:%S")
                minutes_away = int((now - away_since).total_seconds() / 60)
            else:
                minutes_away = 0

            db_helpers.log_presence_event("home")

            if minutes_away < 25:
                return False, ""

            hours = minutes_away // 60
            mins = minutes_away % 60
            duration_str = f"{hours}h {mins}min" if hours > 0 else f"{mins}min"
            arrival_time = now.strftime("%H:%M")
            context = f"user just got home at {arrival_time}, was out for {duration_str}"
            return True, context
        return False, ""
    else:
        if last is None or last["event"] == "home":
            db_helpers.log_presence_event("away")
        return False, ""


ALL_TRIGGERS = [
    ('class_soon', has_class_soon_trigger),
    ('new_artist', new_artist_trigger),
    ('weather_flip', weather_flip_trigger),
    ('late_night', late_night_trigger),
    ('pattern_surface', pattern_surface_trigger),
    ('open_thread', open_thread_trigger),
]
