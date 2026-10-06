import json
import logging
import random
import re
from datetime import datetime
import weather_sync
import db_helpers
import tools as _tools
import schedule as uni_schedule
from llm import chat, chat_with_retry, is_acceptable, chat_with_tools, is_in_character
from persona import PERSONA, IN_CHARACTER_FALLBACKS, get_vibe
from config import (
    LONG_USER_MESSAGE_THRESHOLD, IN_CHARACTER_MAX_CHARS_LONG,
    GROQ_VISION_MODEL, SPOTIFY_CONTEXT_LIMIT,
)

_log = logging.getLogger('brain')

LLM_OPTIONS_CHAT = {"temperature": 0.7, "top_p": 0.8, "num_predict": 100}
LLM_OPTIONS_THINK = {"temperature": 0.7, "top_p": 0.8, "num_predict": 80}
MAX_TOOL_STEPS = 3
_REMINDER_REQUEST = re.compile(
    r"\b(remind me|ping me|remember me|set (a |up a )?reminder)\b", re.I
)
REMINDER_FAILED_REPLY = "couldn't save that reminder. try again with a date and time"

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
                "(e.g. 'tonight at 10') to an ISO datetime before calling. The current "
                "date is in the Time line of the system prompt; never search for it."
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
    last_presence = db_helpers.get_last_presence_event()
    if last_presence:
        parts.append(f"User location: {last_presence['event']} ({last_presence['timestamp']})")
    battery = db_helpers.get_last_battery()
    if battery:
        charge_state = "charging" if battery["charging"] else "not charging"
        parts.append(f"Phone battery: {battery['level']}% ({charge_state})")
    return " | ".join(parts) if parts else ""


def think_and_decide(spotify_raw=None):
    now = datetime.now()
    current_time = now.strftime("%a %d %b, %H:%M")
    last_sent = db_helpers.get_last_ai_message()
    spotify_clean = db_helpers.get_recent_spotify(limit=SPOTIFY_CONTEXT_LIMIT)
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


def _append_tool_turn(messages, tool_name, tool_args, tool_call_id, result):
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


def _generate_vision_reply(user_message, image_data):
    system = (
        f"{PERSONA}\n\n"
        f"The user sent you an image. "
        "Describe what you see in your casual voice (one or two sentences). "
        "If the image contains something worth remembering — a schedule, a note, "
        "a place, a person — mention it naturally so it can be logged.\n"
        f"Time: {datetime.now().strftime('%a %d %b, %H:%M')} | Vibe: {get_vibe()}"
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
    current_time = datetime.now().strftime("%a %d %b %Y, %H:%M")
    spotify_clean = db_helpers.get_recent_spotify(limit=SPOTIFY_CONTEXT_LIMIT)
    context = _build_context_line(user_message, spotify_clean)
    classes = uni_schedule.get_todays_classes()
    upcoming = uni_schedule.has_class_soon()
    music_keywords = ["song", "music", "listening", "track", "playlist", "playing", "hear"]
    is_music = any(k in user_message.lower() for k in music_keywords)
    music_note = " Use the music data from context to answer specifically." if is_music else ""
    rolling, rolling_at = db_helpers.get_rolling_summary_meta()
    is_long = len(user_message) > LONG_USER_MESSAGE_THRESHOLD
    if rolling and is_long:
        age_tag = f" ({rolling_at[:10]})" if rolling_at else ""
        earlier = f"\nEarlier{age_tag}: {rolling[:300]}"
    else:
        earlier = ""
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

    text = None
    used_tools = False
    reminder_saved = False
    for _ in range(MAX_TOOL_STEPS):
        text, tool_name, tool_args, tool_call_id = chat_with_tools(
            messages, TOOL_SCHEMAS, LLM_OPTIONS_CHAT, timeout=90
        )
        if not tool_name:
            break
        used_tools = True
        result = _execute_tool(tool_name, tool_args)
        if tool_name == "set_reminder" and str(result).startswith("reminder set"):
            reminder_saved = True
        _append_tool_turn(messages, tool_name, tool_args, tool_call_id, result)
        text = None

    is_reminder_request = bool(_REMINDER_REQUEST.search(user_message))
    if is_reminder_request and not reminder_saved and not used_tools:
        _, tool_name, tool_args, tool_call_id = chat_with_tools(
            messages, TOOL_SCHEMAS, LLM_OPTIONS_CHAT, timeout=90,
            tool_choice={"type": "function", "function": {"name": "set_reminder"}},
        )
        if tool_name == "set_reminder":
            result = _execute_tool(tool_name, tool_args)
            reminder_saved = str(result).startswith("reminder set")
            _append_tool_turn(messages, tool_name, tool_args, tool_call_id, result)
            used_tools = True
            text = None

    if text is None and used_tools:
        text = chat(messages, LLM_OPTIONS_CHAT, timeout=90)

    # The model happily claims "got it, i'll ping you" without saving anything.
    if is_reminder_request and not reminder_saved:
        _log.warning(f"reminder request not saved: {user_message[:120]!r}")
        return REMINDER_FAILED_REPLY

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
    current_time = datetime.now().strftime("%a %d %b, %H:%M")
    spotify_clean = db_helpers.get_recent_spotify(limit=SPOTIFY_CONTEXT_LIMIT)
    context = _build_context_line(user_message, spotify_clean)
    classes = uni_schedule.get_todays_classes()
    upcoming = uni_schedule.has_class_soon()

    music_keywords = ["song", "music", "listening", "track", "playlist", "playing", "hear"]
    is_music = any(k in user_message.lower() for k in music_keywords)
    music_note = " Use the music data from context to answer specifically." if is_music else ""

    rolling, rolling_at = db_helpers.get_rolling_summary_meta()
    is_long = len(user_message) > LONG_USER_MESSAGE_THRESHOLD
    if rolling and is_long:
        age_tag = f" ({rolling_at[:10]})" if rolling_at else ""
        earlier = f"\nEarlier{age_tag}: {rolling[:300]}"
    else:
        earlier = ""

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
