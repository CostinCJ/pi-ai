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


from unittest.mock import patch
from triggers import home_arrival_trigger


def _insert_presence(event, minutes_ago):
    ts = (datetime.now() - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%d %H:%M:%S")
    with db_helpers.get_conn() as conn:
        conn.execute(
            "INSERT INTO presence_log (event, timestamp) VALUES (?, ?)",
            (event, ts)
        )


def test_home_arrival_fires_after_long_absence(fake_db):
    _insert_presence("away", 35)
    with patch("triggers.phone_is_home", return_value=True):
        fired, context = home_arrival_trigger()
    assert fired is True
    assert "got home" in context
    assert "35min" in context or "34min" in context or "36min" in context  # ±1 min tolerance


def test_home_arrival_no_fire_short_trip(fake_db):
    _insert_presence("away", 10)
    with patch("triggers.phone_is_home", return_value=True):
        fired, context = home_arrival_trigger()
    assert fired is False


def test_home_arrival_no_fire_scanner_failed(fake_db):
    _insert_presence("away", 60)
    with patch("triggers.phone_is_home", return_value=None):
        fired, context = home_arrival_trigger()
    assert fired is False


def test_home_arrival_logs_away_on_departure(fake_db):
    _insert_presence("home", 5)
    with patch("triggers.phone_is_home", return_value=False):
        fired, _ = home_arrival_trigger()
    assert fired is False
    last = db_helpers.get_last_presence_event()
    assert last["event"] == "away"


def test_home_arrival_no_refire_when_already_home(fake_db):
    _insert_presence("home", 5)
    with patch("triggers.phone_is_home", return_value=True):
        fired, _ = home_arrival_trigger()
    assert fired is False


def test_home_arrival_fires_no_previous_event_then_away(fake_db):
    # No prior events: phone seen for first time → log home, don't fire (no away reference)
    with patch("triggers.phone_is_home", return_value=True):
        fired, _ = home_arrival_trigger()
    assert fired is False
    last = db_helpers.get_last_presence_event()
    assert last["event"] == "home"
