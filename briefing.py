"""Daily briefing: collect structured data, phrase it in Lache's voice, send
once per day at first sign of activity (fallback: BRIEFING_WINDOW_END sharp).

Hard rule inherited from the July 2026 hallucination bug: every line of the
sent briefing must trace to a field collected here. Nothing invented.
"""
import logging
from datetime import date, datetime

import db_helpers
import outbox
import schedule as uni_schedule
import weather_sync
import llm
from config import (
    BRIEFING_WINDOW_START, BRIEFING_WINDOW_END, BRIEFING_SPOTIFY_ACTIVE_MIN,
)
from persona import PERSONA

log = logging.getLogger(__name__)


def user_is_active():
    """Real activity signals only. Phone-on-wifi is NOT one — the phone is
    home and online while the user sleeps."""
    try:
        if db_helpers.spotify_played_within(BRIEFING_SPOTIFY_ACTIVE_MIN):
            return True
    except Exception as e:
        log.warning(f"briefing: spotify signal failed: {e}")
    try:
        if db_helpers.get_latest_session_snapshot() is not None:
            return True
    except Exception as e:
        log.warning(f"briefing: session signal failed: {e}")
    try:
        if db_helpers.user_messaged_today():
            return True
    except Exception as e:
        log.warning(f"briefing: message signal failed: {e}")
    return False


def collect_data():
    """Structured briefing data. Sections fail soft and are absent when empty."""
    data = {}
    try:
        weather = weather_sync.get_current_weather()
        if weather and "unavailable" not in weather:
            data["weather"] = weather
    except Exception as e:
        log.warning(f"briefing: weather failed: {e}")
    try:
        if uni_schedule.semester_active():
            classes = uni_schedule.get_todays_classes()
            if "No classes" not in classes:
                data["classes"] = classes
    except Exception as e:
        log.warning(f"briefing: classes failed: {e}")
    try:
        due = db_helpers.get_reminders_due_today()
        if due:
            data["reminders"] = [f"{r['fire_at'][11:16]} {r['text']}" for r in due]
    except Exception as e:
        log.warning(f"briefing: reminders failed: {e}")
    try:
        items = outbox.drain_queue()
        if items:
            data["updates"] = items
    except Exception as e:
        log.warning(f"briefing: outbox drain failed: {e}")
    return data


_COMPOSE_RULES = (
    "You are Lache writing the user's morning briefing from DATA.\n"
    "Rules — non-negotiable:\n"
    "- Every statement must come from a DATA field. Invent NOTHING.\n"
    "- lowercase, direct, compact. 1-4 short lines.\n"
    "- No greeting, no 'good morning', no questions, no filler, no emojis.\n"
    "- Order: weather, classes, reminders, updates. Skip absent fields.\n"
)


def _fallback_text(data):
    """LLM down or off-voice: send the raw data lines. Utility beats voice."""
    lines = []
    if "weather" in data:
        lines.append(data["weather"])
    if "classes" in data:
        lines.append(data["classes"])
    for r in data.get("reminders", []):
        lines.append(f"reminder {r}")
    lines.extend(data.get("updates", []))
    return "\n".join(lines)


def compose(data):
    if not data:
        return None
    payload = "\n".join(
        f"{key}: {value}" for key, value in data.items()
    )
    messages = [
        {"role": "system", "content": f"{PERSONA}\n\n{_COMPOSE_RULES}"},
        {"role": "user", "content": f"DATA:\n{payload}"},
    ]
    try:
        text = llm.chat(messages, {"temperature": 0.4, "num_predict": 220}, timeout=60)
    except Exception as e:
        log.warning(f"briefing: compose LLM failed: {e}")
        text = None
    return text.strip() if text and text.strip() else _fallback_text(data)


def _dedup_key():
    return f"briefing_{date.today().isoformat()}"


def send_briefing(force=False):
    """Build and send today's briefing. Returns True if a message went out."""
    if not force and db_helpers.was_proactive_attempted_today("briefing", _dedup_key()):
        return False
    data = collect_data()
    db_helpers.mark_proactive_attempted("briefing", _dedup_key())
    if not data:
        log.info("briefing: no data at all, skipping today")
        return False
    text = compose(data)
    if not text:
        return False
    # Bypasses repeat suppression: briefings are legitimately similar day to day.
    sent = outbox.send(text, urgency="urgent", suppress_repeats=False)
    if sent:
        db_helpers.log_message("ai", text)
        db_helpers.log_proactive("briefing", _dedup_key(), text, delivered=1)
    else:
        # Drained outbox items are already consumed=1 and the composed text
        # would otherwise be lost; log it undelivered so retry_undelivered()
        # redelivers it.
        db_helpers.log_proactive("briefing", _dedup_key(), text, delivered=0)
    return sent


def briefing_tick():
    """Scheduler job, every 10 min. Sends at first activity signal inside the
    window; at BRIEFING_WINDOW_END sends regardless. After that hour, nothing
    (a reboot at 15:00 must not trigger a stale 'morning' briefing)."""
    try:
        now = datetime.now()
        if db_helpers.was_proactive_attempted_today("briefing", _dedup_key()):
            return
        if now.hour < BRIEFING_WINDOW_START or now.hour > BRIEFING_WINDOW_END:
            return
        if now.hour == BRIEFING_WINDOW_END or user_is_active():
            send_briefing()
    except Exception as e:
        log.error(f"briefing_tick failed: {e}", exc_info=True)
