import random
from collections import deque
from datetime import datetime, timezone
import db_helpers
import schedule as uni_schedule
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


def free_reasoning_trigger():
    """LLM-driven proactive: survey the user's recent week and decide what to surface.
    Replaces pattern_surface + open_thread with a single context-aware judgment."""
    if random.random() > PATTERN_TRIGGER_PROBABILITY:
        return False, ""

    trigger_key = f"free_reasoning_{datetime.now().strftime('%Y-%m-%d')}"
    if db_helpers.was_proactive_attempted_today('free_reasoning', trigger_key):
        return False, ""

    signals = db_helpers.get_daily_signals(days=7)
    signal_text = "\n".join(
        f"{s['date']}: mood={s['mood'] or '?'} energy={s['energy'] or '?'} topics={s['main_topics'] or '?'}"
        for s in signals
    ) if signals else "(no daily signals yet)"

    patterns = db_helpers.get_recent_patterns(limit=3)

    threads = db_helpers.get_open_threads(status='open')
    thread_text = "\n".join(
        f"- {t['description']} (last ref: {t['last_referenced'] or 'never'})"
        for t in threads[:3]
    ) if threads else "(no open threads)"

    summary = db_helpers.get_rolling_summary() or "(no summary)"
    last = db_helpers.get_last_ai_message()
    last_text = f"{last['text']} ({last['timestamp']})" if last else "(none)"
    spotify = db_helpers.get_recent_spotify(limit=10)

    from llm import chat
    from persona import get_vibe

    messages = [
        {"role": "system", "content": (
            f"Time: {datetime.now().strftime('%a %d %b, %H:%M')} | Vibe: {get_vibe()}\n\n"
            f"Recent listening: {spotify or '(none)'}\n\n"
            f"Daily signals (last 7 days):\n{signal_text}\n\n"
            f"Recent patterns:\n{patterns}\n\n"
            f"Open threads:\n{thread_text}\n\n"
            f"Rolling summary: {summary[:300]}\n\n"
            f"Last message you sent: {last_text}\n\n"
            "You are Lache. Given the above context about the user's recent week, "
            "do you notice something specific and genuine worth bringing up right now? "
            "If yes, write a short context string (e.g. 'user mentioned wanting to "
            "learn guitar 3 days ago, hasn't brought it up since'). "
            "If there's nothing genuine to surface, reply with the single word SILENCE."
        )},
        {"role": "user", "content": "what do you notice?"},
    ]

    try:
        result = chat(messages, {"temperature": 0.7, "num_predict": 80}, timeout=60)
    except Exception:
        return False, ""

    if not result or result.strip().upper() == "SILENCE":
        return False, ""

    return True, result.strip(), trigger_key


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
    ('session',         session_trigger),
    ('weather_flip',    weather_flip_trigger),
    ('late_night',      late_night_trigger),
    ('free_reasoning',  free_reasoning_trigger),
]
