from unittest.mock import patch
import db_helpers
import briefing
import outbox


def _play_track(minutes_ago):
    with db_helpers.get_conn() as conn:
        conn.execute(
            "INSERT INTO spotify_tracks (artist, title, played_at) "
            "VALUES ('ptv', 'song', datetime('now', 'localtime', ?))",
            (f'-{minutes_ago} minutes',),
        )


def test_spotify_played_within(fake_db):
    _play_track(5)
    assert db_helpers.spotify_played_within(20)
    assert not db_helpers.spotify_played_within(2)


def test_user_messaged_today(fake_db):
    assert not db_helpers.user_messaged_today()
    db_helpers.log_message("user", "yo")
    assert db_helpers.user_messaged_today()


def test_reminders_due_today_only(fake_db):
    with db_helpers.get_conn() as conn:
        conn.execute(
            "INSERT INTO reminders (text, fire_at) VALUES "
            "('today thing', datetime('now', 'localtime', '+2 hours')),"
            "('tomorrow thing', datetime('now', 'localtime', '+1 day'))"
        )
    due = db_helpers.get_reminders_due_today()
    assert [r["text"] for r in due] == ["today thing"]


def test_user_is_active_via_spotify(fake_db):
    _play_track(5)
    assert briefing.user_is_active()


def test_user_not_active_when_quiet(fake_db):
    with patch.object(db_helpers, "get_latest_session_snapshot", return_value=None):
        assert not briefing.user_is_active()


def test_collect_data_skips_empty_sections(fake_db):
    outbox.send("new ptv album: X", urgency="briefing")
    with patch.object(briefing.weather_sync, "get_current_weather",
                      return_value="22.0°C, clear sky"), \
         patch.object(briefing.uni_schedule, "semester_active", return_value=False):
        data = briefing.collect_data()
    assert data["weather"] == "22.0°C, clear sky"
    assert data["updates"] == ["new ptv album: X"]
    assert "classes" not in data
    assert "reminders" not in data


def test_collect_data_survives_broken_section(fake_db):
    with patch.object(briefing.weather_sync, "get_current_weather",
                      side_effect=RuntimeError("api down")), \
         patch.object(briefing.uni_schedule, "semester_active", return_value=False):
        data = briefing.collect_data()
    assert "weather" not in data  # skipped, not raised
