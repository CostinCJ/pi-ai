import time
import json
import re
import os
import inspect
import groq as _groq
from config import (
    GROQ_API_KEY, GROQ_MODEL, LOG_DIR, LLM_LOG_MAX_BYTES,
    IN_CHARACTER_MAX_CHARS, IN_CHARACTER_MAX_CHARS_LONG,
)

_client = _groq.Groq(api_key=GROQ_API_KEY)

BANNED_PHRASES = [
    "chill of cluj", "whispers of", "silence of the night",
    "your companion", "how can i assist", "how can i help",
    "city lights", "enjoy the vibe", "what would you like to explore",
    "let the silence", "let the city", "let the night", "let the music",
    "symphony", "composer", "you're the artist", "speak for you",
    "king of the night", "no need for extra effort",
    "masterpiece", "the air is crisp", "alive with energy",
    "you're doing great", "just like the city", "today is perfect",
    "playlist is a", "as your personal", "personal ai",
    "i'm here to", "i am here to", "i'm just here to", "just here to",
    "here to listen", "what's on your mind", "what is on your mind",
]

LOG_PATH = os.path.join(str(LOG_DIR), 'llm.log')


def _rotate_log():
    if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > LLM_LOG_MAX_BYTES:
        with open(LOG_PATH, 'w'):
            pass


def _log(caller, latency_ms, success, extra=""):
    _rotate_log()
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    status = 'ok' if success else 'fail'
    line = f"{ts} caller={caller} latency_ms={latency_ms:.0f} status={status}"
    if extra:
        line += f" {extra}"
    with open(LOG_PATH, 'a') as f:
        f.write(line + "\n")


def _clean(text):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"</?think>", "", text)  # strip orphaned tags
    text = re.sub(r"\*[^*]+\*", "", text)
    text = re.sub(r"^Lache:\s*", "", text, flags=re.IGNORECASE)
    return text.strip()


def is_acceptable(text):
    lower = text.lower()
    return not any(b in lower for b in BANNED_PHRASES)


THINKING_LEAK_PHRASES = [
    "the user asked", "i need to respond", "i should check",
    "i should respond", "let me think", "okay, let's see",
    "first, i should", "the rules say", "respond appropriately",
]


def is_in_character(text, max_chars=None):
    """Structural style filter — catches poetry/sycophancy patterns the
    blocklist misses. Returns True if the text looks like Lache.
    `max_chars` defaults to IN_CHARACTER_MAX_CHARS; callers can pass
    IN_CHARACTER_MAX_CHARS_LONG for context-warranted long replies."""
    if not text or not text.strip():
        return False
    s = text.strip()
    cap = max_chars if max_chars is not None else IN_CHARACTER_MAX_CHARS
    if len(s) > cap:
        return False
    sentence_cap = 3 if cap <= IN_CHARACTER_MAX_CHARS else 6
    if s.count(".") + s.count("!") + s.count("?") > sentence_cap:
        return False
    if s.count("—") >= 2:
        return False
    lower = s.lower()
    if any(p in lower for p in THINKING_LEAK_PHRASES):
        return False
    words = [w for w in s.split() if w.isalpha()]
    if len(words) >= 6:
        capitalised = sum(1 for w in words if w[0].isupper())
        if capitalised / len(words) > 0.5:
            return False
    return is_acceptable(s)


def chat(messages, options=None, timeout=60, model=None):
    caller = inspect.stack()[1].function
    if options is None:
        options = {}
    t0 = time.time()

    kwargs = {}
    if 'temperature' in options:
        kwargs['temperature'] = options['temperature']
    if 'top_p' in options:
        kwargs['top_p'] = options['top_p']
    kwargs['max_tokens'] = options.get('num_predict') or options.get('max_tokens') or 150

    for attempt in range(2):
        try:
            completion = _client.chat.completions.create(
                model=model or GROQ_MODEL,
                messages=messages,
                timeout=timeout,
                **kwargs,
            )
            content = completion.choices[0].message.content or ""
            result = _clean(content)
            _log(caller, (time.time() - t0) * 1000, True)
            return result
        except _groq.APIConnectionError as e:
            if attempt == 0:
                time.sleep(2)
                continue
            _log(caller, (time.time() - t0) * 1000, False, f"err=APIConnectionError")
            raise
        except _groq.APITimeoutError:
            _log(caller, (time.time() - t0) * 1000, False, "err=APITimeoutError")
            raise
        except Exception as e:
            _log(caller, (time.time() - t0) * 1000, False, f"err={type(e).__name__}")
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
        _log(caller, 0, False, f"chat_json_err={type(e).__name__}")
        with open(LOG_PATH, 'a') as f:
            f.write(f"  chat_json error: {type(e).__name__}: {e}\n")
        return None


def chat_with_retry(messages, options=None, timeout=60, retry_hint=None, max_chars=None):
    """Generate, validate against `is_in_character`, and retry once with a
    corrective hint if the first try fails. Returns (text, ok_flag).

    `max_chars` lets callers loosen the in-character cap for long-form replies.
    """
    first = chat(messages, options, timeout)
    if is_in_character(first, max_chars=max_chars):
        return first, True

    import db_helpers as _db
    _db.log_quality_event('retry_triggered', first[:200])

    hint = retry_hint or (
        "your previous draft was either empty or too poetic. write one short, "
        "lowercase, casual sentence in lache's voice — no metaphors, no "
        "compliments, no marketing copy. just acknowledge or react briefly."
    )
    retry_messages = list(messages) + [
        {"role": "assistant", "content": first or "(empty)"},
        {"role": "user", "content": hint},
    ]
    second = chat(retry_messages, options, timeout)
    if is_in_character(second, max_chars=max_chars):
        _db.log_quality_event('retry_succeeded', second[:200])
        return second, True
    _db.log_quality_event('retry_failed', second[:200])
    return second, False


def chat_with_tools(messages, tools, options=None, timeout=60, model=None):
    """Call Groq with function-calling tools.

    Returns a 4-tuple:
      (text, None, None, None)          — LLM replied directly
      (None, tool_name, args, call_id)  — LLM wants to call a tool
      (None, None, None, None)          — error (caller should fall back)
    """
    caller = inspect.stack()[1].function
    if options is None:
        options = {}
    t0 = time.time()

    kwargs = {}
    if "temperature" in options:
        kwargs["temperature"] = options["temperature"]
    kwargs["max_tokens"] = options.get("num_predict") or options.get("max_tokens") or 150

    try:
        completion = _client.chat.completions.create(
            model=model or GROQ_MODEL,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            timeout=timeout,
            **kwargs,
        )
        choice = completion.choices[0]
        _log(caller, (time.time() - t0) * 1000, True)

        if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
            tc = choice.message.tool_calls[0]
            args = json.loads(tc.function.arguments)
            return None, tc.function.name, args, tc.id

        content = choice.message.content or ""
        return _clean(content), None, None, None

    except Exception as e:
        _log(caller, (time.time() - t0) * 1000, False, f"err={type(e).__name__}")
        return None, None, None, None
