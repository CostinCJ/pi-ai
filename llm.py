import time
import json
import re
import os
import inspect
import requests
from config import OLLAMA_CHAT_URL, MODEL

BANNED_PHRASES = [
    "chill of cluj", "whispers of", "silence of the night",
    "your companion", "how can i assist", "how can i help",
    "city lights", "enjoy the vibe", "what would you like to explore",
    "let the silence", "let the city", "let the night", "let the music",
    "symphony", "composer", "you're the artist", "speak for you",
    "king of the night", "no need for extra effort",
]

LOG_PATH = '/home/pi/pi-ai/llm.log'
LOG_MAX_BYTES = 5 * 1024 * 1024  # 5MB

def _rotate_log():
    if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > LOG_MAX_BYTES:
        with open(LOG_PATH, 'w'):
            pass

def _log(caller, latency_ms, success):
    _rotate_log()
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    status = 'ok' if success else 'fail'
    with open(LOG_PATH, 'a') as f:
        f.write(f"{ts} caller={caller} latency_ms={latency_ms:.0f} status={status}\n")

def _clean(text):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"\*[^*]+\*", "", text)
    text = re.sub(r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF]", "", text)
    text = re.sub(r"^Lache:\s*", "", text, flags=re.IGNORECASE)
    return text.strip()

def is_acceptable(text):
    lower = text.lower()
    return not any(b in lower for b in BANNED_PHRASES)

def chat(messages, options=None, timeout=60):
    caller = inspect.stack()[1].function
    if options is None:
        options = {}
    t0 = time.time()
    for attempt in range(2):
        try:
            r = requests.post(OLLAMA_CHAT_URL, json={
                "model": MODEL, "stream": False,
                "messages": messages, "options": options
            }, timeout=timeout)
            content = r.json().get("message", {}).get("content", "").strip()
            result = _clean(content)
            _log(caller, (time.time() - t0) * 1000, True)
            return result
        except requests.exceptions.ConnectionError:
            if attempt == 0:
                time.sleep(2)
                continue
            _log(caller, (time.time() - t0) * 1000, False)
            raise
        except requests.exceptions.Timeout:
            _log(caller, (time.time() - t0) * 1000, False)
            raise
        except Exception:
            _log(caller, (time.time() - t0) * 1000, False)
            raise

def chat_json(messages, options=None, schema_keys=None, timeout=60):
    caller = inspect.stack()[1].function
    try:
        raw = chat(messages, options, timeout)
        raw = re.sub(r"```json\s*", "", raw)
        raw = re.sub(r"```\s*", "", raw)
        data = json.loads(raw)
        if schema_keys:
            for k in schema_keys:
                if k not in data:
                    return None
        return data
    except Exception as e:
        _log(caller, 0, False)
        with open(LOG_PATH, 'a') as f:
            f.write(f"  chat_json error: {type(e).__name__}: {e}\n")
        return None
