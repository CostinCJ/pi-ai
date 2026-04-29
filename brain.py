import json
import logging
import random
from datetime import datetime
import weather_sync
import spotify_sync
import db_helpers
import tools as _tools
import schedule as uni_schedule
from llm import chat, chat_with_retry, is_acceptable, chat_with_tools, is_in_character
from persona import PERSONA, IN_CHARACTER_FALLBACKS, get_vibe
from config import (
    LONG_USER_MESSAGE_THRESHOLD, IN_CHARACTER_MAX_CHARS_LONG,
    GROQ_VISION_MODEL,
)

_log = logging.getLogger('brain')

LLM_OPTIONS_CHAT = {"temperature": 0.7, "top_p": 0.8, "num_predict": 100}
LLM_OPTIONS_THINK = {"temperature": 0.7, "top_p": 0.8, "num_predict": 80}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web for current information. Use when the user asks "
                "about news, facts, or anything that needs up-to-date info."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_reminder",
            "description": (
                "Set a reminder for the user. Use when they ask to be reminded "
                "of something at a specific time. Resolve natural language times "
                "(e.g. 'tonight at 10') to an ISO datetime before calling."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "What to remind the user about"},
                    "fire_at": {
                        "type": "string",
                        "description": "ISO datetime string, e.g. '2026-04-29T22:00:00'",
                    },
                },
                "required": ["text", "fire_at"],
            },
        },
    },
]


def _format_session(snapshot):
    if not snapshot:
        return None
    parts = [f"{app['name']} ({app['ram_mb']}MB)" for app in snapshot]
    return "Session: " + ", ".join(parts)


def _spotify_clean(spotify_raw):
    if not spotify_raw or "unavailable" in spotify_raw.lower():
        return None
    return spotify_raw.replace("Recent tracks: ", "")


def _build_context_line(user_message="", spotify_clean=None):
    parts = []
    facts = db_helpers.get_user_facts(limit=5)
    if facts and "no specific" not in facts:
        parts.append(f"Facts: {facts[:200]}")
    if spotify_clean:
        parts.append(f"User's music: {spotify_clean[:200]}")
    if len(user_message) > LONG_USER_MESSAGE_THRESHOLD:
        patterns = db_helpers.get_recent_patterns()
        if patterns and "no new" not in patterns:
            parts.append(f"Patterns: {patterns[:200]}")
    session = _format_session(db_helpers.get_latest_session_snapshot())
    if session:
        parts.append(session)
    return " | ".join(parts) if parts else ""


def _build_proactive_context(spotify_clean=None):
    parts = []
    facts = db_helpers.get_user_facts(limit=5)
    if facts and "no specific" not in facts:
        parts.append(f"Facts: {facts[:200]}")
    patterns = db_helpers.get_recent_patterns()
    if patterns and "no new" not in patterns:
        parts.append(f"Patterns: {patterns[:200]}")
    if spotify_clean:
        parts.append(f"User's music: {spotify_clean[:200]}")
    session = _format_session(db_helpers.get_latest_session_snapshot())
    if session:
        parts.append(session)
    return " | ".join(parts) if parts else ""


def think_and_decide(spotify_raw=None):
    now = datetime.now()
    current_time = now.strftime("%A, %H:%M")
    last_sent = db_helpers.get_last_ai_message()
    spotify_clean = _spotify_clean(spotify_raw if spotify_raw is not None else spotify_sync.get_recent_tracks())
    context = _build_proactive_context(spotify_clean)
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
        ], LLM_OPTIONS_THINK, timeout=90)

        if not is_acceptable(result):
            return "SILENCE"
        if len(result) > 200:
            return "SILENCE"
        return result
    except Exception as e:
        _log.error(f"think_and_decide failed: {type(e).__name__}: {e}", exc_info=True)
        return None


def _execute_tool(tool_name, tool_args):
    if tool_name == "web_search":
        return _tools.web_search(tool_args.get("query", ""))
    if tool_name == "set_reminder":
        return _tools.set_reminder(
            tool_args.get("text", ""), tool_args.get("fire_at", "")
        )
    return f"unknown tool: {tool_name}"


def _generate_vision_reply(user_message, image_data):
    system = (
        f"{PERSONA}\n\n"
        f"The user sent you an image. "
        "Describe what you see in your casual voice (one or two sentences). "
        "If the image contains something worth remembering — a schedule, a note, "
        "a place, a person — mention it naturally so it can be logged.\n"
        f"Time: {datetime.now().strftime('%A, %H:%M')} | Vibe: {get_vibe()}"
    )
    user_content = [
        {"type": "text", "text": user_message or "what's in this?"},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}},
    ]
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]
    return chat(
        messages,
        {"temperature": 0.7, "num_predict": 200},
        timeout=90,
        model=GROQ_VISION_MODEL,
    )


def _generate_tool_reply(user_message):
    current_time = datetime.now().strftime("%A, %H:%M")
    spotify_clean = _spotify_clean(spotify_sync.get_recent_tracks())
    context = _build_context_line(user_message, spotify_clean)
    classes = uni_schedule.get_todays_classes()
    upcoming = uni_schedule.has_class_soon()
    music_keywords = ["song", "music", "listening", "track", "playlist", "playing", "hear"]
    is_music = any(k in user_message.lower() for k in music_keywords)
    music_note = " Use the music data from context to answer specifically." if is_music else ""
    rolling = db_helpers.get_rolling_summary()
    is_long = len(user_message) > LONG_USER_MESSAGE_THRESHOLD
    earlier = f"\nEarlier: {rolling[:300]}" if rolling and is_long else ""
    cap = IN_CHARACTER_MAX_CHARS_LONG if is_long else None

    system = (
        f"{PERSONA}\n\n"
        f"Time: {current_time} | {classes}"
        f"{f' | {upcoming} soon' if upcoming else ''}\n"
        f"{context}{music_note}{earlier}\n"
        f"Vibe: {get_vibe()}"
    )
    history_messages = db_helpers.get_recent_history_messages(limit=8)
    messages = [{"role": "system", "content": system}]
    messages.extend(history_messages)
    messages.append({"role": "user", "content": user_message})

    text, tool_name, tool_args, tool_call_id = chat_with_tools(
        messages, TOOL_SCHEMAS, LLM_OPTIONS_CHAT, timeout=90
    )

    if tool_name:
        result = _execute_tool(tool_name, tool_args)
        messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": tool_call_id,
                "type": "function",
                "function": {"name": tool_name, "arguments": json.dumps(tool_args)},
            }],
        })
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": str(result),
        })
        text = chat(messages, LLM_OPTIONS_CHAT, timeout=90)

    if text and is_in_character(text, max_chars=cap):
        return text
    return None


def generate_agentic_reply(user_message, image_data=None):
    try:
        if image_data:
            reply = _generate_vision_reply(user_message, image_data)
        else:
            reply = _generate_tool_reply(user_message)
        if reply:
            return reply
    except Exception as e:
        _log.error(f"generate_agentic_reply failed: {type(e).__name__}: {e}", exc_info=True)
    return generate_reply(user_message)


def generate_reply(user_message):
    current_time = datetime.now().strftime("%A, %H:%M")
    spotify_clean = _spotify_clean(spotify_sync.get_recent_tracks())
    context = _build_context_line(user_message, spotify_clean)
    classes = uni_schedule.get_todays_classes()
    upcoming = uni_schedule.has_class_soon()

    music_keywords = ["song", "music", "listening", "track", "playlist", "playing", "hear"]
    is_music = any(k in user_message.lower() for k in music_keywords)
    music_note = " Use the music data from context to answer specifically." if is_music else ""

    rolling = db_helpers.get_rolling_summary()
    is_long = len(user_message) > LONG_USER_MESSAGE_THRESHOLD
    earlier = f"\nEarlier: {rolling[:300]}" if rolling and is_long else ""

    system = f"""{PERSONA}

Time: {current_time} | {classes}{f" | {upcoming} soon" if upcoming else ""}
{context}{music_note}{earlier}
Vibe: {get_vibe()}"""

    history_messages = db_helpers.get_recent_history_messages(limit=8)

    messages = [{"role": "system", "content": system}]
    messages.extend(history_messages)
    messages.append({"role": "user", "content": user_message})

    # Allow longer replies when the user clearly asked for depth.
    cap = IN_CHARACTER_MAX_CHARS_LONG if is_long else None

    try:
        reply, ok = chat_with_retry(messages, LLM_OPTIONS_CHAT, timeout=90, max_chars=cap)
    except Exception as e:
        _log.error(f"generate_reply failed: {type(e).__name__}: {e}", exc_info=True)
        return random.choice(IN_CHARACTER_FALLBACKS)

    if ok:
        return reply
    return random.choice(IN_CHARACTER_FALLBACKS)
