import requests
import threading
import json
import re
from datetime import datetime
import weather_sync
import spotify_sync
import db_helpers
import schedule as uni_schedule
from config import OLLAMA_URL, MODEL

CHAT_URL = OLLAMA_URL.replace("/api/generate", "/api/chat")

PERSONA = """/no_think
You are Lache — a personal AI on a Raspberry Pi in Cluj-Napoca, Romania. Talk exactly like these examples:

User: how are you doing
Lache: running fine, nothing broken yet. you good?

User: what time is it
Lache: check your phone lol. it's Sunday afternoon.

User: i just bought a new guitar amp
Lache: nice, what did you get? those things are loud as hell in an apartment

User: i think i'll go out tonight
Lache: bars or just driving around? classic move either way

Rules: no emojis, no *actions*, no "I'm here to help", no poetry, no filler. Short and direct unless they ask something that genuinely needs more. Only mention league/music/habits if they appear in the context."""

BANNED_PHRASES = [
    "chill of cluj", "whispers of", "silence of the night",
    "your companion", "how can i assist", "how can i help",
    "city lights", "enjoy the vibe", "what would you like to explore",
    "let the silence", "let the city", "let the night", "let the music",
    "symphony", "composer", "you're the artist", "speak for you",
    "king of the night", "no need for extra effort",
]

OLLAMA_OPTIONS_CHAT  = {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "num_ctx": 4096, "num_predict": 100}
OLLAMA_OPTIONS_THINK = {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "num_ctx": 4096, "num_predict": 80}
OLLAMA_OPTIONS_FACTS = {"temperature": 0.1, "top_p": 0.8, "top_k": 20, "num_ctx": 2048, "num_predict": 100}

FACT_TRIGGERS = [
    "i bought", "i got", "i quit", "i have", "i own", "i play ",
    "i hate", "i love", "i started", "i stopped", "i passed", "i failed",
    "my guitar", "my car", "my bike", "i'm a ", "i am a ",
]


def _clean(text):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"\*[^*]+\*", "", text)
    text = re.sub(r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF]", "", text)
    text = re.sub(r"^Lache:\s*", "", text, flags=re.IGNORECASE)
    return text.strip()


def _chat(messages, options, timeout=60):
    r = requests.post(CHAT_URL, json={
        "model": MODEL, "stream": False,
        "messages": messages, "options": options
    }, timeout=timeout)
    content = r.json().get("message", {}).get("content", "").strip()
    return _clean(content)


def _build_context_line():
    parts = []
    facts = db_helpers.get_user_facts()
    if facts and "no specific" not in facts:
        parts.append(f"Facts: {facts}")
    patterns = db_helpers.get_recent_patterns()
    if patterns and "no new" not in patterns:
        parts.append(f"Patterns: {patterns}")
    spotify = spotify_sync.get_recent_tracks()
    if spotify and "unavailable" not in spotify.lower():
        parts.append(f"Music: {spotify}")
    return " | ".join(parts) if parts else ""


def _extract_realtime_facts(user_message):
    try:
        content = _chat([
            {"role": "system", "content": "/no_think\nExtract permanent personal facts only."},
            {"role": "user", "content": f"""User said: "{user_message}"

Permanent facts: owns/bought something, quit/started something, standing preference.
NOT facts: "tired", "bored", current activities.

Reply ONLY as JSON: {{"facts": {{"key": "description"}}}} or {{"facts": {{}}}}"""}
        ], OLLAMA_OPTIONS_FACTS, timeout=45)
        data = json.loads(content)
        facts = data.get("facts", {})
        if facts:
            with db_helpers.get_conn() as conn:
                for key, val in facts.items():
                    if key and val:
                        conn.execute(
                            "INSERT OR REPLACE INTO user_facts (fact_key, fact_value) VALUES (?, ?)",
                            (key, val)
                        )
    except Exception:
        pass


def think_and_decide():
    now = datetime.now()
    current_time = now.strftime("%A, %H:%M")
    history = db_helpers.get_recent_history(limit=10)
    last_sent = db_helpers.get_last_ai_message()
    context = _build_context_line()
    upcoming = uni_schedule.has_class_soon()

    system = f"""{PERSONA}

Time: {current_time} | Weather: {weather_sync.get_current_weather()} | {uni_schedule.get_todays_classes()}
{context}
{f"Class soon: {upcoming}" if upcoming else ""}
Last message you sent: {last_sent['text'] if last_sent else "(none)"}"""

    history_text = history if history else "(no recent conversation)"

    try:
        result = _chat([
            {"role": "system", "content": system},
            {"role": "user", "content": f"""Recent conversation:
{history_text}

Do you have something real and specific to say right now?
- Only say "still up late" if it's actually past midnight
- Only mention league/music/habits if the data above shows them
- Don't repeat your last message's idea
- 1-2 casual sentences, no emojis
- If nothing specific to say: reply only SILENCE"""}
        ], OLLAMA_OPTIONS_THINK, timeout=90)

        if any(b in result.lower() for b in BANNED_PHRASES):
            return "SILENCE"
        if len(result) > 200:
            return "SILENCE"
        return result
    except Exception:
        return None


def generate_reply(user_message):
    current_time = datetime.now().strftime("%A, %H:%M")
    context = _build_context_line()
    classes = uni_schedule.get_todays_classes()
    upcoming = uni_schedule.has_class_soon()

    music_keywords = ["song", "music", "listening", "track", "playlist", "playing", "hear"]
    is_music = any(k in user_message.lower() for k in music_keywords)
    music_note = " Use the music data from context to answer specifically." if is_music else ""

    system = f"""{PERSONA}

Time: {current_time} | {classes}{f" | {upcoming} soon" if upcoming else ""}
{context}{music_note}"""

    history_messages = db_helpers.get_recent_history_messages(limit=8)

    messages = [{"role": "system", "content": system}]
    messages.extend(history_messages)
    messages.append({"role": "user", "content": user_message})

    try:
        reply = _chat(messages, OLLAMA_OPTIONS_CHAT, timeout=90)

        if any(b in reply.lower() for b in BANNED_PHRASES):
            reply = "..."

        if any(t in user_message.lower() for t in FACT_TRIGGERS):
            threading.Thread(
                target=_extract_realtime_facts,
                args=(user_message,),
                daemon=True
            ).start()

        return reply
    except Exception:
        return "one sec, thinking..."
