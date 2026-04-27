from datetime import datetime
import random
import weather_sync
import spotify_sync
import db_helpers
import schedule as uni_schedule
from llm import chat, chat_with_retry, is_acceptable
from persona import PERSONA, IN_CHARACTER_FALLBACKS, get_vibe

OLLAMA_OPTIONS_CHAT  = {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "num_ctx": 4096, "num_predict": 100}
OLLAMA_OPTIONS_THINK = {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "num_ctx": 4096, "num_predict": 80}


def _format_session(snapshot):
    if not snapshot:
        return None
    parts = [f"{app['name']} ({app['ram_mb']}MB)" for app in snapshot]
    return "Session: " + ", ".join(parts)


def _build_context_line(user_message=""):
    parts = []
    facts = db_helpers.get_user_facts(limit=5)
    if facts and "no specific" not in facts:
        parts.append(f"Facts: {facts[:200]}")
    spotify = spotify_sync.get_recent_tracks()
    if spotify and "unavailable" not in spotify.lower():
        clean_spotify = spotify.replace("Recent tracks: ", "")
        parts.append(clean_spotify[:200])
    if len(user_message) > 40:
        patterns = db_helpers.get_recent_patterns()
        if patterns and "no new" not in patterns:
            parts.append(f"Patterns: {patterns[:200]}")
    session = _format_session(db_helpers.get_latest_session_snapshot())
    if session:
        parts.append(session)
    return " | ".join(parts) if parts else ""


def _build_proactive_context():
    parts = []
    facts = db_helpers.get_user_facts(limit=5)
    if facts and "no specific" not in facts:
        parts.append(f"Facts: {facts[:200]}")
    patterns = db_helpers.get_recent_patterns()
    if patterns and "no new" not in patterns:
        parts.append(f"Patterns: {patterns[:200]}")
    spotify = spotify_sync.get_recent_tracks()
    if spotify and "unavailable" not in spotify.lower():
        clean_spotify = spotify.replace("Recent tracks: ", "")
        parts.append(clean_spotify[:200])
    session = _format_session(db_helpers.get_latest_session_snapshot())
    if session:
        parts.append(session)
    return " | ".join(parts) if parts else ""


def think_and_decide():
    now = datetime.now()
    current_time = now.strftime("%A, %H:%M")
    last_sent = db_helpers.get_last_ai_message()
    context = _build_proactive_context()
    upcoming = uni_schedule.has_class_soon()

    system = f"""{PERSONA}

Time: {current_time} | Weather: {weather_sync.get_current_weather()} | {uni_schedule.get_todays_classes()}
{context}
{f"Class soon: {upcoming}" if upcoming else ""}
Last message you sent: {last_sent['text'] if last_sent else "(none)"}
Vibe: {get_vibe()}"""

    raw_history = db_helpers.get_recent_history_messages(limit=10)
    history_text = "".join(
        f"{'USER' if m['role']=='user' else 'LACHE'}: {m['content']}\n"
        for m in raw_history
    ) or "(no recent conversation)"

    try:
        result = chat([
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

        if not is_acceptable(result):
            return "SILENCE"
        if len(result) > 200:
            return "SILENCE"
        return result
    except Exception:
        return None


def generate_reply(user_message):
    current_time = datetime.now().strftime("%A, %H:%M")
    context = _build_context_line(user_message)
    classes = uni_schedule.get_todays_classes()
    upcoming = uni_schedule.has_class_soon()

    music_keywords = ["song", "music", "listening", "track", "playlist", "playing", "hear"]
    is_music = any(k in user_message.lower() for k in music_keywords)
    music_note = " Use the music data from context to answer specifically." if is_music else ""

    rolling = db_helpers.get_rolling_summary()
    earlier = f"\nEarlier: {rolling[:300]}" if rolling and len(user_message) > 40 else ""

    system = f"""{PERSONA}

Time: {current_time} | {classes}{f" | {upcoming} soon" if upcoming else ""}
{context}{music_note}{earlier}
Vibe: {get_vibe()}"""

    history_messages = db_helpers.get_recent_history_messages(limit=8)

    messages = [{"role": "system", "content": system}]
    messages.extend(history_messages)
    messages.append({"role": "user", "content": user_message})

    try:
        reply, ok = chat_with_retry(messages, OLLAMA_OPTIONS_CHAT, timeout=90)
    except Exception:
        return random.choice(IN_CHARACTER_FALLBACKS)

    if ok:
        return reply
    return random.choice(IN_CHARACTER_FALLBACKS)
