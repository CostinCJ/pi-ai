from collections import deque
from datetime import datetime, timezone
import db_helpers
import schedule as uni_schedule
from network_radar import phone_is_home
from config import (
    AWAY_THRESHOLD_MIN, AWAY_DEBOUNCE_SCANS,
    RIOT_PUUID,
)
import riot_client


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


def post_game_trigger():
    if not RIOT_PUUID:
        return False, ""
    ids = riot_client.get_recent_match_ids(RIOT_PUUID, count=1)
    if not ids:
        return False, ""
    match_id = ids[0]
    dedup_key = f"post_game_{match_id}"
    if db_helpers.was_proactive_attempted_today("post_game", dedup_key):
        return False, ""
    m = riot_client.get_match(match_id)
    if not m or "info" not in m:
        return False, ""
    me = next((p for p in m["info"]["participants"] if p["puuid"] == RIOT_PUUID), None)
    if not me:
        return False, ""
    with db_helpers.get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO riot_match_log "
            "(match_id, played_at, win, kills, deaths, assists, champion, queue_type) "
            "VALUES (?, datetime('now'), ?, ?, ?, ?, ?, ?)",
            (match_id, int(me["win"]), me["kills"], me["deaths"],
             me["assists"], me["championName"], str(m["info"]["queueId"])),
        )
    outcome = "win" if me["win"] else "loss"
    msg = f"{outcome} pe {me['championName']} — {me['kills']}/{me['deaths']}/{me['assists']}"
    return True, msg, dedup_key


ALL_TRIGGERS = [
    ('class_soon', has_class_soon_trigger),
    ('post_game',  post_game_trigger),
]
