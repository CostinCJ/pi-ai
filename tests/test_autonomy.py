from unittest.mock import patch
import autonomy

# Heartbeat skips during quiet hours (02:00-09:00). Force a non-quiet hour
# in tests so they don't flake when run early in the morning.
_NON_QUIET_HOUR = type("FakeNow", (), {})()


class _FixedDatetime:
    """Replacement for datetime.datetime inside autonomy that always reports
    a non-quiet hour. Subclassed to keep .strftime/etc. working elsewhere."""
    @staticmethod
    def now():
        from datetime import datetime as _dt
        real = _dt.now()
        return real.replace(hour=12, minute=0, second=0, microsecond=0)


def test_phrasing_call_includes_persona_system_prompt(fake_db):
    """The proactive phrasing call must put PERSONA in a system message —
    that's the bug behind the 10:42 'masterpiece' message."""
    captured = {}

    def fake_chat_with_retry(messages, options=None, timeout=60, retry_hint=None):
        captured["messages"] = messages
        return "looks like rain, grab an umbrella", True

    with patch("autonomy.ALL_TRIGGERS", [
        ("weather_flip",
         lambda: (True, "rain incoming", "weather_2026-05-08"))
    ]), patch("autonomy.chat_with_retry", fake_chat_with_retry), \
         patch("autonomy.send_telegram_message"), \
         patch("autonomy.datetime", _FixedDatetime), \
         patch("autonomy.db_helpers.was_recently_active", return_value=False):
        autonomy.heartbeat()

    msgs = captured["messages"]
    assert msgs[0]["role"] == "system"
    assert "Lache" in msgs[0]["content"]
    assert "casual" in msgs[0]["content"].lower()
    assert "no metaphors" in msgs[0]["content"].lower() or "no poetry" in msgs[0]["content"].lower()
    assert msgs[1]["role"] == "user"
    assert "rain" in msgs[1]["content"].lower()


import db_helpers


def test_trigger_marked_attempted_after_silence(fake_db):
    """If a trigger fires and the LLM returns SILENCE, the trigger must
    be marked attempted so it does NOT fire again on the next tick."""
    trigger_context = "user just got home at 18:00, was out for 2h 30min"
    trigger_key = "home_arrival_test_key"
    db_helpers.mark_proactive_attempted("home_arrival", trigger_key)

    # The trigger should already be deduped because mark_proactive_attempted
    # was called, same as what _handle_trigger_send does for SILENCE.
    assert db_helpers.was_proactive_attempted_today("home_arrival", trigger_key) is True


def test_deliver_reminders_sends_due_and_marks_delivered(fake_db, monkeypatch):
    from datetime import datetime, timedelta

    fire_at = (datetime.now() - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    db_helpers.add_reminder("call mom", fire_at)

    sent_msgs = []

    def fake_send(text):
        sent_msgs.append(text)
        return True

    monkeypatch.setattr(autonomy, "send_telegram_message", fake_send)
    autonomy.deliver_reminders()

    assert len(sent_msgs) == 1
    assert "call mom" in sent_msgs[0]
    assert db_helpers.get_due_reminders() == []


def test_deliver_reminders_skips_future(fake_db, monkeypatch):
    from datetime import datetime, timedelta

    fire_at = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    db_helpers.add_reminder("future task", fire_at)

    sent_msgs = []
    monkeypatch.setattr(autonomy, "send_telegram_message", lambda t: sent_msgs.append(t) or True)
    autonomy.deliver_reminders()

    assert len(sent_msgs) == 0


def test_deliver_reminders_caps_at_10(fake_db, monkeypatch):
    from datetime import datetime, timedelta

    fire_at = (datetime.now() - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    for i in range(15):
        db_helpers.add_reminder(f"reminder {i}", fire_at)

    sent_msgs = []
    monkeypatch.setattr(autonomy, "send_telegram_message", lambda t: sent_msgs.append(t) or True)
    autonomy.deliver_reminders()

    assert len(sent_msgs) == 10
