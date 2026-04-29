from datetime import datetime, timedelta, timezone
import db_helpers
import triggers as _triggers


def test_get_last_presence_event_returns_none_when_empty(fake_db):
    assert db_helpers.get_last_presence_event() is None


def test_log_and_get_presence_event(fake_db):
    db_helpers.log_presence_event("away")
    result = db_helpers.get_last_presence_event()
    assert result is not None
    assert result["event"] == "away"
    assert "timestamp" in result


def test_get_last_presence_event_returns_most_recent(fake_db):
    db_helpers.log_presence_event("away")
    db_helpers.log_presence_event("home")
    result = db_helpers.get_last_presence_event()
    assert result["event"] == "home"


from unittest.mock import patch
from triggers import home_arrival_trigger


def _insert_presence(event, minutes_ago):
    # Match production: presence_log timestamps are stored in UTC (SQLite CURRENT_TIMESTAMP).
    ts = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%d %H:%M:%S")
    with db_helpers.get_conn() as conn:
        conn.execute(
            "INSERT INTO presence_log (event, timestamp) VALUES (?, ?)",
            (event, ts)
        )


def _reset_debounce():
    _triggers._recent_scans.clear()


def test_home_arrival_fires_after_long_absence(fake_db):
    _reset_debounce()
    _insert_presence("away", 35)
    with patch("triggers.phone_is_home", return_value=True):
        result = home_arrival_trigger()
    fired, context = result[0], result[1]
    assert fired is True
    assert "got home" in context
    assert "35min" in context or "34min" in context or "36min" in context  # ±1 min tolerance


def test_home_arrival_no_fire_short_trip(fake_db):
    _reset_debounce()
    _insert_presence("away", 10)
    with patch("triggers.phone_is_home", return_value=True):
        result = home_arrival_trigger()
    assert result[0] is False


def test_home_arrival_no_fire_scanner_failed(fake_db):
    _reset_debounce()
    _insert_presence("away", 60)
    with patch("triggers.phone_is_home", return_value=None):
        result = home_arrival_trigger()
    assert result[0] is False


def test_home_arrival_logs_away_after_debounce(fake_db):
    """Three consecutive misses should flip state to away."""
    from config import AWAY_DEBOUNCE_SCANS
    _reset_debounce()
    _insert_presence("home", 5)
    with patch("triggers.phone_is_home", return_value=False):
        for _ in range(AWAY_DEBOUNCE_SCANS):
            result = home_arrival_trigger()
            assert result[0] is False
    last = db_helpers.get_last_presence_event()
    assert last["event"] == "away"


def test_home_arrival_single_miss_does_not_flip(fake_db):
    """A single missed scan must not log 'away' — protects against arp-scan flapping."""
    _reset_debounce()
    _insert_presence("home", 5)
    with patch("triggers.phone_is_home", return_value=False):
        result = home_arrival_trigger()
    assert result[0] is False
    last = db_helpers.get_last_presence_event()
    assert last["event"] == "home"


def test_home_arrival_miss_then_hit_no_flap(fake_db):
    """miss → hit should not produce a fake away→home arrival message."""
    _reset_debounce()
    _insert_presence("home", 5)
    with patch("triggers.phone_is_home", return_value=False):
        home_arrival_trigger()
    with patch("triggers.phone_is_home", return_value=True):
        result = home_arrival_trigger()
    assert result[0] is False
    last = db_helpers.get_last_presence_event()
    assert last["event"] == "home"


def test_home_arrival_no_refire_when_already_home(fake_db):
    _reset_debounce()
    _insert_presence("home", 5)
    with patch("triggers.phone_is_home", return_value=True):
        result = home_arrival_trigger()
    assert result[0] is False


def test_home_arrival_fires_no_previous_event_then_away(fake_db):
    # No prior events: phone seen for first time → log home, don't fire (no away reference)
    _reset_debounce()
    with patch("triggers.phone_is_home", return_value=True):
        result = home_arrival_trigger()
    assert result[0] is False
    last = db_helpers.get_last_presence_event()
    assert last["event"] == "home"


import autonomy


def test_presence_check_sends_message_on_arrival(fake_db):
    """presence_check must phrase using PERSONA system prompt and send when trigger fires."""
    captured = {}

    def fake_chat_with_retry(messages, options=None, timeout=60, retry_hint=None):
        captured["messages"] = messages
        return "back already?", True

    with patch("autonomy.home_arrival_trigger",
               return_value=(True, "user just got home at 01:34, was out for 1h 12min")), \
         patch("autonomy.chat_with_retry", fake_chat_with_retry), \
         patch("autonomy.send_telegram_message") as mock_send, \
         patch("autonomy.db_helpers.log_message"), \
         patch("autonomy.db_helpers.mark_proactive_attempted"), \
         patch("autonomy.db_helpers.log_proactive"):
        autonomy.presence_check()

    assert mock_send.call_count == 1
    assert mock_send.call_args[0][0] == "back already?"
    msgs = captured["messages"]
    assert msgs[0]["role"] == "system"
    assert "Lache" in msgs[0]["content"]
    assert "01:34" in msgs[1]["content"] or "1h 12min" in msgs[1]["content"]
