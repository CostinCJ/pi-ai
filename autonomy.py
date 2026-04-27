import time as _time
import logging
import requests
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
import db_helpers
from config import TELEGRAM_TOKEN, CHAT_ID
from triggers import ALL_TRIGGERS, home_arrival_trigger
from llm import chat_with_retry
from persona import PERSONA

logging.basicConfig(filename='/home/pi/pi-ai/autonomy.log', level=logging.INFO,
                    format='%(asctime)s %(message)s')


def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": text}, timeout=10)
    except Exception as e:
        logging.error(f"send_telegram_message failed: {e}")


def heartbeat():
    t0 = _time.time()
    hour = datetime.now().hour
    if 2 <= hour < 9:
        logging.info("tick: quiet hours, skipped")
        return
    if db_helpers.was_recently_active(minutes=90):
        logging.info("tick: recently active, skipped")
        return

    fired_type = None
    fired_context = None
    for trigger_type, trigger_fn in ALL_TRIGGERS:
        try:
            should_speak, context_str = trigger_fn()
            if should_speak:
                fired_type = trigger_type
                fired_context = context_str
                break
        except Exception as e:
            logging.error(f"trigger {trigger_type} error: {e}")

    if not fired_type:
        latency = int((_time.time() - t0) * 1000)
        logging.info(f"tick: no trigger fired latency_ms={latency}")
        return

    phrasing_messages = [
        {"role": "system", "content": (
            f"{PERSONA}\n\n"
            "You will be given a one-line idea. Rephrase it in Lache's voice. "
            "Output ONE casual lowercase sentence, max 20 words. No emojis, "
            "no metaphors, no compliments, no follow-up explanation. If the "
            "idea is empty, reply with the literal word SILENCE."
        )},
        {"role": "user", "content": fired_context},
    ]
    try:
        message, ok = chat_with_retry(
            phrasing_messages,
            {"temperature": 0.7, "num_predict": 60},
            timeout=60,
        )
    except Exception as e:
        logging.error(f"LLM phrasing failed for trigger {fired_type}: {e}")
        return

    if not ok or not message or message.strip().upper() == "SILENCE":
        latency = int((_time.time() - t0) * 1000)
        logging.info(f"tick: trigger={fired_type} returned silence latency_ms={latency}")
        db_helpers.mark_proactive_attempted(fired_type, fired_context[:100])
        return

    db_helpers.log_message('ai', message)
    db_helpers.mark_proactive_attempted(fired_type, fired_context[:100])
    db_helpers.log_proactive(fired_type, fired_context[:100], message)
    send_telegram_message(message)

    latency = int((_time.time() - t0) * 1000)
    logging.info(f"tick: sent trigger={fired_type} latency_ms={latency}")


def presence_check():
    t0 = _time.time()
    try:
        should_speak, context_str = home_arrival_trigger()
    except Exception as e:
        logging.error(f"presence_check trigger error: {e}")
        return

    if not should_speak:
        return

    phrasing_messages = [
        {"role": "system", "content": (
            f"{PERSONA}\n\n"
            "You will be given a one-line idea. Rephrase it in Lache's voice. "
            "Output ONE casual lowercase sentence, max 20 words. No emojis, "
            "no metaphors, no compliments, no follow-up explanation. If the "
            "idea is empty, reply with the literal word SILENCE."
        )},
        {"role": "user", "content": context_str},
    ]
    try:
        message, ok = chat_with_retry(
            phrasing_messages,
            {"temperature": 0.7, "num_predict": 60},
            timeout=60,
        )
    except Exception as e:
        logging.error(f"LLM phrasing failed for home_arrival: {e}")
        return

    if not ok or not message or message.strip().upper() == "SILENCE":
        latency = int((_time.time() - t0) * 1000)
        logging.info(f"presence_check: silence latency_ms={latency}")
        db_helpers.mark_proactive_attempted('home_arrival', context_str[:100])
        return

    db_helpers.log_message('ai', message)
    db_helpers.mark_proactive_attempted('home_arrival', context_str[:100])
    db_helpers.log_proactive('home_arrival', context_str[:100], message)
    send_telegram_message(message)

    latency = int((_time.time() - t0) * 1000)
    logging.info(f"presence_check: sent home_arrival latency_ms={latency}")


if __name__ == '__main__':
    scheduler = BackgroundScheduler()
    scheduler.add_job(heartbeat, 'interval', minutes=10)
    scheduler.add_job(presence_check, 'interval', minutes=2)
    scheduler.start()
    try:
        while True:
            _time.sleep(2)
    except KeyboardInterrupt:
        scheduler.shutdown()
