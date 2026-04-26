import time as _time
import logging
import requests
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
import brain
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
    thought = brain.think_and_decide()
    latency = int((_time.time() - t0) * 1000)
    if thought and thought.strip().upper() != "SILENCE":
        db_helpers.log_message('ai', thought)
        send_telegram_message(thought)
        logging.info(f"tick: sent message latency_ms={latency}")
    elif thought is None:
        logging.error(f"tick: brain returned None (possible Ollama error) latency_ms={latency}")
    else:
        logging.info(f"tick: silence latency_ms={latency}")

if __name__ == '__main__':
    scheduler = BackgroundScheduler()
    scheduler.add_job(heartbeat, 'interval', minutes=60)
    scheduler.start()
    try:
        while True:
            time.sleep(2)
    except KeyboardInterrupt:
        scheduler.shutdown()
