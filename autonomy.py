import os
import signal
import time as _time
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import timezone
import db_helpers
from outbox import send_telegram_message, is_repeat
import spotify_sync
from config import (
    LOG_DIR,
    APP_LOG_MAX_BYTES, APP_LOG_BACKUPS,
    HEARTBEAT_INTERVAL_MIN, PRESENCE_INTERVAL_MIN,
    QUIET_HOURS_START, QUIET_HOURS_END,
    RECENT_ACTIVE_COOLDOWN_MIN,
    SPOTIFY_POLL_INTERVAL_MIN, SPOTIFY_TRACKS_KEEP_DAYS,
    ENGAGEMENT_WINDOW, ENGAGEMENT_DEAD_WINDOW,
    BACKOFF_IGNORED_MAX_PER_DAY, BACKOFF_DEAD_MAX_PER_DAY,
    PROACTIVE_REPEAT_OVERLAP, PROACTIVE_REPEAT_DAYS,
)
from triggers import ALL_TRIGGERS, home_arrival_trigger
from llm import chat_with_retry
from persona import PERSONA, get_vibe
import riot_client
import config as _config

_handler = RotatingFileHandler(
    os.path.join(str(LOG_DIR), 'autonomy.log'),
    maxBytes=APP_LOG_MAX_BYTES, backupCount=APP_LOG_BACKUPS,
)
_handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
logging.basicConfig(level=logging.INFO, handlers=[_handler])

_PHRASING_OPTIONS = {"temperature": 0.4, "num_predict": 40}

# Triggers still allowed when the user has stopped responding. Everything else
# (free_reasoning, weather_flip, session, pattern_surface) is smalltalk-grade
# and goes quiet until the user replies to something again.
HIGH_VALUE_TRIGGERS = {'class_soon', 'home_arrival', 'post_game', 'late_night'}
CORE_TRIGGERS = {'home_arrival', 'post_game'}


def engagement_level():
    """'engaged' | 'ignored' | 'dead', from replies to recent proactive sends.
    A single user reply anywhere in the recent window restores 'engaged'."""
    responded, total = db_helpers.proactive_engagement(ENGAGEMENT_DEAD_WINDOW)
    if total < ENGAGEMENT_WINDOW or responded > 0:
        recent_responded, recent_total = db_helpers.proactive_engagement(ENGAGEMENT_WINDOW)
        if recent_total >= ENGAGEMENT_WINDOW and recent_responded == 0:
            return 'ignored'
        return 'engaged'
    return 'dead' if total >= ENGAGEMENT_DEAD_WINDOW else 'ignored'


def proactive_allowed(trigger_type, level=None):
    """Engagement-aware gate: throttle trigger set and daily volume when the
    user isn't replying. user_responded was tracked for months and never read
    — 336 sends / 15 replies happened because nothing consumed it."""
    level = level or engagement_level()
    if level == 'engaged':
        return True
    if level == 'ignored':
        return (trigger_type in HIGH_VALUE_TRIGGERS
                and db_helpers.proactive_sent_count(hours=24) < BACKOFF_IGNORED_MAX_PER_DAY)
    return (trigger_type in CORE_TRIGGERS
            and db_helpers.proactive_sent_count(hours=24) < BACKOFF_DEAD_MAX_PER_DAY)


def _last_sent_label(last_sent):
    if not last_sent:
        return "(none)"
    try:
        ts = datetime.strptime(last_sent['timestamp'], "%Y-%m-%d %H:%M:%S")
        ts = ts.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
        mins = int((datetime.now() - ts).total_seconds() / 60)
        if mins < 60:
            age = f"{mins}min ago"
        elif mins < 1440:
            age = f"{mins // 60}h ago"
        else:
            age = f"{mins // 1440}d ago"
        return f"{last_sent['text']} ({age})"
    except Exception:
        return last_sent['text']


def retry_undelivered():
    """Retry sending any proactive_log rows still flagged delivered=0.
    Cap attempts to 5 then give up."""
    pending = db_helpers.get_undelivered_proactive(limit=10)
    for row in pending:
        if row["attempts"] >= 5:
            db_helpers.update_proactive_delivered(row["id"], delivered=-1, attempts=row["attempts"])
            logging.warning(f"giving up on proactive id={row['id']} after 5 attempts")
            continue
        ok = send_telegram_message(row["message_sent"])
        attempts = row["attempts"] + 1
        db_helpers.update_proactive_delivered(
            row["id"], delivered=1 if ok else 0, attempts=attempts
        )
        if ok:
            logging.info(f"retry_undelivered: sent id={row['id']} after {attempts} attempts")


def deliver_reminders():
    """Fire any due reminders via Telegram and mark them delivered."""
    due = db_helpers.get_due_reminders()
    for row in due[:10]:
        sent = send_telegram_message(f"reminder: {row['text']}")
        if sent:
            db_helpers.mark_reminder_delivered(row['id'])
            logging.info(f"deliver_reminders: sent id={row['id']}")
        else:
            logging.warning(f"deliver_reminders: send failed id={row['id']}")


def _handle_trigger_send(trigger_type, fired_context, fired_dedup_key, success_callback=None):
    """Phrases the trigger context and sends. Returns True if the user got a message."""
    current_time = datetime.now().strftime("%a %d %b, %H:%M")
    vibe = get_vibe()
    last_sent = db_helpers.get_last_ai_message()
    last_sent_text = _last_sent_label(last_sent)

    phrasing_messages = [
        {"role": "system", "content": (
            f"{PERSONA}\n\n"
            f"Current time: {current_time} | Vibe: {vibe}\n"
            f"Last message you sent: {last_sent_text}\n\n"
            "You will be given a brief idea for a message Lache sends TO the user. "
            "Write Lache's outgoing text — Lache is texting first, not replying. "
            "Output ONE casual lowercase sentence, max 20 words. No emojis, "
            "no metaphors, no compliments, no follow-up explanation. "
            "Don't repeat or closely paraphrase your last message. "
            "If the idea is empty or nothing natural fits, reply with the literal word SILENCE."
        )},
        {"role": "user", "content": fired_context},
    ]
    try:
        message, ok = chat_with_retry(phrasing_messages, _PHRASING_OPTIONS, timeout=60)
    except Exception as e:
        logging.error(f"LLM phrasing failed for trigger {trigger_type}: {e}")
        return False

    if not ok or not message or message.strip().upper() == "SILENCE":
        logging.info(f"tick: trigger={trigger_type} returned silence")
        db_helpers.mark_proactive_attempted(trigger_type, fired_dedup_key)
        return False

    if is_repeat(message):
        logging.info(f"tick: trigger={trigger_type} suppressed repeat: {message[:60]}")
        db_helpers.mark_proactive_attempted(trigger_type, fired_dedup_key)
        return False

    db_helpers.log_message('ai', message)
    db_helpers.mark_proactive_attempted(trigger_type, fired_dedup_key)
    sent = send_telegram_message(message)
    db_helpers.log_proactive(trigger_type, fired_dedup_key, message, delivered=1 if sent else 0)
    if sent and success_callback:
        try:
            success_callback()
        except Exception as e:
            logging.error(f"success_callback failed for {trigger_type}: {e}")
    return sent


def heartbeat():
    t0 = _time.time()
    hour = datetime.now().hour
    if QUIET_HOURS_START <= hour < QUIET_HOURS_END:
        logging.info("tick: quiet hours, skipped")
        return
    if db_helpers.was_recently_active(minutes=RECENT_ACTIVE_COOLDOWN_MIN):
        logging.info("tick: recently active, skipped")
        return

    if riot_client.is_in_game(_config.RIOT_PUUID):
        logging.info("tick: user in LoL game, skipped")
        return

    level = engagement_level()

    fired_type = None
    fired_context = None
    fired_dedup_key = None
    fired_extra = None
    for trigger_type, trigger_fn in ALL_TRIGGERS:
        if not proactive_allowed(trigger_type, level):
            continue
        try:
            result = trigger_fn()
            should_speak = result[0]
            context_str = result[1]
            if should_speak:
                fired_type = trigger_type
                fired_context = context_str
                fired_dedup_key = result[2] if len(result) > 2 else context_str[:100]
                fired_extra = result[3] if len(result) > 3 else None
                break
        except Exception as e:
            logging.error(f"trigger {trigger_type} error: {e}")

    if not fired_type:
        latency = int((_time.time() - t0) * 1000)
        logging.info(f"tick: no trigger fired latency_ms={latency} engagement={level}")
        return

    _handle_trigger_send(fired_type, fired_context, fired_dedup_key)
    latency = int((_time.time() - t0) * 1000)
    logging.info(f"tick: handled trigger={fired_type} latency_ms={latency}")


def presence_check():
    t0 = _time.time()
    try:
        result = home_arrival_trigger()
        should_speak = result[0]
        context_str = result[1]
        dedup_key = result[2] if len(result) > 2 else context_str[:100]
    except Exception as e:
        logging.error(f"presence_check trigger error: {e}")
        return

    if not should_speak:
        return

    # The trigger fn must always run (it maintains presence_log), but the
    # send still respects the engagement-aware daily cap.
    if not proactive_allowed('home_arrival'):
        logging.info("presence_check: send suppressed by engagement backoff")
        db_helpers.mark_proactive_attempted('home_arrival', dedup_key)
        return

    _handle_trigger_send('home_arrival', context_str, dedup_key)
    latency = int((_time.time() - t0) * 1000)
    logging.info(f"presence_check: handled latency_ms={latency}")


def spotify_poll():
    """Poll Spotify API for recent tracks and log new ones to DB."""
    try:
        tracks = spotify_sync.get_recent_tracks_raw()
    except Exception as e:
        logging.error(f"spotify_poll fetch failed: {e}")
        return
    new_count = 0
    for t in tracks:
        try:
            if db_helpers.log_spotify_track(t['artist'], t['title'], t['played_at']):
                new_count += 1
        except Exception:
            pass
    if new_count:
        logging.info(f"spotify_poll: logged {new_count} new tracks")


def spotify_prune():
    """Trim old spotify tracks."""
    try:
        db_helpers.prune_spotify_tracks(days=SPOTIFY_TRACKS_KEEP_DAYS)
    except Exception as e:
        logging.error(f"spotify_prune failed: {e}")


_scheduler = None


def _shutdown(signum, frame):
    logging.info(f"received signal {signum}, shutting down")
    if _scheduler:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass
    raise SystemExit(0)


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(heartbeat, 'interval', minutes=HEARTBEAT_INTERVAL_MIN)
    _scheduler.add_job(presence_check, 'interval', minutes=PRESENCE_INTERVAL_MIN)
    _scheduler.add_job(retry_undelivered, 'interval', minutes=5)
    _scheduler.add_job(deliver_reminders, 'interval', minutes=1)
    _scheduler.add_job(spotify_poll, 'interval', minutes=SPOTIFY_POLL_INTERVAL_MIN)
    _scheduler.add_job(spotify_prune, 'cron', hour=4, minute=37)
    _scheduler.start()
    try:
        while True:
            _time.sleep(2)
    except (KeyboardInterrupt, SystemExit):
        _scheduler.shutdown()
