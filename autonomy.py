import time as _time
import logging
import requests
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
import db_helpers
from config import TELEGRAM_TOKEN, CHAT_ID

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

    from triggers import ALL_TRIGGERS
    from llm import chat

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

    try:
        message = chat(
            [{"role": "user", "content": f"Phrase this as 1 short Lache message: {fired_context}"}],
            {"temperature": 0.7, "num_predict": 60},
            timeout=60
        )
    except Exception as e:
        logging.error(f"LLM phrasing failed for trigger {fired_type}: {e}")
        return

    if not message or message.strip().upper() == "SILENCE":
        latency = int((_time.time() - t0) * 1000)
        logging.info(f"tick: trigger={fired_type} but LLM returned silence latency_ms={latency}")
        return

    db_helpers.log_message('ai', message)
    db_helpers.log_proactive(fired_type, fired_context[:100], message)
    send_telegram_message(message)

    latency = int((_time.time() - t0) * 1000)
    logging.info(f"tick: sent trigger={fired_type} latency_ms={latency}")


if __name__ == '__main__':
    scheduler = BackgroundScheduler()
    scheduler.add_job(heartbeat, 'interval', minutes=10)
    scheduler.start()
    try:
        while True:
            _time.sleep(2)
    except KeyboardInterrupt:
        scheduler.shutdown()
