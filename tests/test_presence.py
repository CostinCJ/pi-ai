from datetime import datetime, timedelta
import db_helpers


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
