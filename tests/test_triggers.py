from unittest.mock import patch
from datetime import datetime, timedelta
import db_helpers
import triggers


def test_weather_flip_returns_change_summary(fake_db):
    fake_change = {"summary": "rain incoming", "delta_c": -10}
    with patch("triggers.weather_sync.get_weather_change", return_value=fake_change):
        result = triggers.weather_flip_trigger()
    assert result[0] is True
    assert result[1] == "rain incoming"
    assert result[2].startswith("weather_")


def test_weather_flip_dedup_same_day(fake_db):
    fake_change = {"summary": "rain incoming"}
    today_key = f"weather_{datetime.now().strftime('%Y-%m-%d')}"
    db_helpers.mark_proactive_attempted('weather_flip', today_key)
    with patch("triggers.weather_sync.get_weather_change", return_value=fake_change):
        ok, _ = triggers.weather_flip_trigger()
    assert ok is False


def test_weather_flip_no_change(fake_db):
    with patch("triggers.weather_sync.get_weather_change", return_value=None):
        ok, _ = triggers.weather_flip_trigger()
    assert ok is False


def test_session_trigger_detects_game(fake_db):
    snapshot = [
        {"name": "League of Legends", "ram_mb": 2000},
        {"name": "Discord", "ram_mb": 800},
    ]
    with patch("triggers.db_helpers.get_latest_session_snapshot", return_value=snapshot):
        result = triggers.session_trigger()
    assert result[0] is True
    assert "league" in result[1].lower()


def test_session_trigger_no_game(fake_db):
    snapshot = [{"name": "VSCode", "ram_mb": 800}]
    with patch("triggers.db_helpers.get_latest_session_snapshot", return_value=snapshot):
        ok, _ = triggers.session_trigger()
    assert ok is False


def test_pattern_surface_picks_recent(fake_db):
    with db_helpers.get_conn() as conn:
        for i, p in enumerate(["old pattern", "newer pattern", "newest pattern"]):
            conn.execute("INSERT INTO pattern_log (pattern_description) VALUES (?)", (p,))
    # force the random gate open
    with patch("triggers.random.random", return_value=0.0), \
         patch("triggers.random.choices", side_effect=lambda choices, weights, k: [choices[0]]):
        result = triggers.pattern_surface_trigger()
    assert result[0] is True
    # choices[0] is the most-recent row in our DESC ordering
    assert "newest" in result[1]
    assert result[2].startswith("pattern_")


def test_class_soon_returns_attempt_dedup_key(fake_db):
    with patch("triggers.uni_schedule.has_class_soon", return_value="TRSI curs in ~45min"):
        result = triggers.has_class_soon_trigger()
    assert result[0] is True
    assert result[2].startswith("class_soon_")


def test_class_soon_dedup_after_attempt(fake_db):
    with patch("triggers.uni_schedule.has_class_soon", return_value="TRSI curs in ~45min"):
        first = triggers.has_class_soon_trigger()
    assert first[0] is True
    db_helpers.mark_proactive_attempted("class_soon", first[2])
    with patch("triggers.uni_schedule.has_class_soon", return_value="TRSI curs in ~45min"):
        second = triggers.has_class_soon_trigger()
    assert second[0] is False


def test_pattern_surface_skipped_by_random(fake_db):
    with patch("triggers.random.random", return_value=0.99):
        ok, _ = triggers.pattern_surface_trigger()
    assert ok is False


def test_open_thread_returns_thread_id_for_deferred_update(fake_db):
    db_helpers.add_open_thread("fix the guitar amp")
    result = triggers.open_thread_trigger()
    assert result[0] is True
    assert "guitar amp" in result[1]
    # 4-tuple: (True, context, dedup_key, thread_id) so the caller can defer
    # update_thread_referenced until after a successful send.
    assert len(result) == 4
    assert isinstance(result[3], int)
    # Critically: should NOT have been marked as referenced yet.
    threads = db_helpers.get_open_threads(status='open')
    assert threads[0]["last_referenced"] is None
