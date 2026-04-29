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
        return "yo, first time hearing architects in a while", True

    with patch("autonomy.ALL_TRIGGERS", [
        ("new_artist",
         lambda: (True, "first time hearing Architects in a while, what made you put it on?"))
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
    assert "Architects" in msgs[1]["content"]


import db_helpers


def test_new_artist_trigger_does_not_refire_after_silence(fake_db):
    """If autonomy attempts a trigger and the LLM returns SILENCE, the
    trigger must NOT fire again on the next tick — even though no message
    was logged to proactive_log."""
    db_helpers.set_proactive_state("last_artist", "Architects")

    # First attempt: LLM returns SILENCE.
    with patch("autonomy.chat_with_retry", return_value=("SILENCE", False)), \
         patch("autonomy.send_telegram_message"), \
         patch("autonomy.datetime", _FixedDatetime), \
         patch("autonomy.ALL_TRIGGERS", [("new_artist", autonomy.ALL_TRIGGERS[1][1])]), \
         patch("autonomy.db_helpers.was_recently_active", return_value=False), \
         patch("triggers.spotify_sync.get_recent_tracks", return_value="Recent tracks: Architects - x"):
        autonomy.heartbeat()

    # Second attempt: must NOT call chat_with_retry at all because the
    # trigger should already be marked attempted today.
    with patch("autonomy.chat_with_retry") as second_call, \
         patch("autonomy.send_telegram_message"), \
         patch("autonomy.datetime", _FixedDatetime), \
         patch("autonomy.ALL_TRIGGERS", [("new_artist", autonomy.ALL_TRIGGERS[1][1])]), \
         patch("autonomy.db_helpers.was_recently_active", return_value=False), \
         patch("triggers.spotify_sync.get_recent_tracks", return_value="Recent tracks: Architects - x"):
        autonomy.heartbeat()

    assert second_call.call_count == 0


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
