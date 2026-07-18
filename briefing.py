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
from config import (
    BRIEFING_WINDOW_START, BRIEFING_WINDOW_END, BRIEFING_SPOTIFY_ACTIVE_MIN,
)

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
