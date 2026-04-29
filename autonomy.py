import os
import signal
import time as _time
import logging
from logging.handlers import RotatingFileHandler
import requests
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
import db_helpers
import spotify_sync
from config import (
    TELEGRAM_TOKEN, CHAT_ID, LOG_DIR,
    APP_LOG_MAX_BYTES, APP_LOG_BACKUPS,
    HEARTBEAT_INTERVAL_MIN, PRESENCE_INTERVAL_MIN,
    QUIET_HOURS_START, QUIET_HOURS_END,
    RECENT_ACTIVE_COOLDOWN_MIN,
)
from triggers import ALL_TRIGGERS, home_arrival_trigger
from llm import chat_with_retry
from persona import PERSONA, get_vibe

_handler = RotatingFileHandler(
    os.path.join(str(LOG_DIR), 'autonomy.log'),
    maxBytes=APP_LOG_MAX_BYTES, backupCount=APP_LOG_BACKUPS,
)
_handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
logging.basicConfig(level=logging.INFO, handlers=[_handler])

_PHRASING_OPTIONS = {"temperature": 0.4, "num_predict": 40}


def send_telegram_message(text):
    """Sends via Telegram. Returns True on 2xx, False otherwise. Never raises."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": CHAT_ID, "text": text}, timeout=10)
        if 200 <= r.status_code < 300:
            return True
        logging.error(f"send_telegram_message non-2xx: {r.status_code} {r.text[:200]}")
        return False
    except Exception as e:
        logging.error(f"send_telegram_message failed: {e}")
        return False


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
    current_time = datetime.now().strftime("%A %H:%M")
    vibe = get_vibe()
    last_sent = db_helpers.get_last_ai_message()
    last_sent_text = last_sent['text'] if last_sent else "(none)"

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

    # Cache spotify so triggers + context don't double-fetch this tick.
    try:
        spotify_raw = spotify_sync.get_recent_tracks()
    except Exception:
        spotify_raw = None

    fired_type = None
    fired_context = None
    fired_dedup_key = None
    fired_extra = None
    for trigger_type, trigger_fn in ALL_TRIGGERS:
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
        logging.info(f"tick: no trigger fired latency_ms={latency}")
        return

    # open_thread defers update_thread_referenced until after a successful send.
    success_callback = None
    if fired_type == 'open_thread' and fired_extra is not None:
        thread_id = fired_extra
        success_callback = lambda: db_helpers.update_thread_referenced(thread_id)

    _handle_trigger_send(fired_type, fired_context, fired_dedup_key, success_callback)
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

    _handle_trigger_send('home_arrival', context_str, dedup_key)
    latency = int((_time.time() - t0) * 1000)
    logging.info(f"presence_check: handled latency_ms={latency}")


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
    _scheduler.start()
    try:
        while True:
            _time.sleep(2)
    except (KeyboardInterrupt, SystemExit):
        _scheduler.shutdown()
