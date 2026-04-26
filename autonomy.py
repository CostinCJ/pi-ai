import time
import requests
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
import brain
import db_helpers
from config import TELEGRAM_TOKEN, CHAT_ID

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": text})

def heartbeat():
    hour = datetime.now().hour
    if 2 <= hour < 9:
        return
    if db_helpers.was_recently_active(minutes=90):
        return
    thought = brain.think_and_decide()
    if thought and thought.strip().upper() != "SILENCE":
        db_helpers.log_message('ai', thought)
        send_telegram_message(thought)

if __name__ == '__main__':
    scheduler = BackgroundScheduler()
    scheduler.add_job(heartbeat, 'interval', minutes=60)
    scheduler.start()
    try:
        while True:
            time.sleep(2)
    except KeyboardInterrupt:
        scheduler.shutdown()
