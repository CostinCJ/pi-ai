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


def _fake_data():
    return {"weather": "22°C clear", "reminders": ["15:00 print report"]}


def test_compose_uses_llm_with_explicit_num_predict(fake_db, fake_ollama):
    fake_ollama["queue"].append("22 and clear. print the report at 15:00.")
    text = briefing.compose(_fake_data())
    assert text == "22 and clear. print the report at 15:00."
    options = fake_ollama["calls"][0]["options"]
    assert options.get("num_predict"), "explicit num_predict is mandatory"


def test_compose_falls_back_to_raw_lines_when_llm_empty(fake_db, fake_ollama):
    # queue empty -> fake chat returns "" -> plain data fallback, never nothing
    text = briefing.compose(_fake_data())
    assert "22°C clear" in text
    assert "15:00 print report" in text


def test_send_briefing_once_per_day(fake_db, fake_ollama):
    fake_ollama["queue"].append("morning line")
    with patch.object(briefing.weather_sync, "get_current_weather",
                      return_value="22°C clear"), \
         patch.object(briefing.uni_schedule, "semester_active", return_value=False), \
         patch.object(outbox, "send_telegram_message", return_value=True) as tg:
        assert briefing.send_briefing()
        assert not briefing.send_briefing()  # dedup
    assert tg.call_count == 1


def test_send_briefing_skips_when_no_data(fake_db, fake_ollama):
    with patch.object(briefing.weather_sync, "get_current_weather",
                      return_value="Weather data unavailable."), \
         patch.object(briefing.uni_schedule, "semester_active", return_value=False), \
         patch.object(outbox, "send_telegram_message") as tg:
        assert not briefing.send_briefing()
    tg.assert_not_called()


def test_send_briefing_logs_undelivered_on_send_failure(fake_db, fake_ollama):
    # A failed outbox.send() must not lose the composed text — it should be
    # logged with delivered=0 so retry_undelivered() picks it up later.
    fake_ollama["queue"].append("morning line")
    with patch.object(briefing.weather_sync, "get_current_weather",
                      return_value="22°C clear"), \
         patch.object(briefing.uni_schedule, "semester_active", return_value=False), \
         patch.object(outbox, "send_telegram_message", return_value=False):
        assert not briefing.send_briefing()
    with db_helpers.get_conn() as conn:
        rows = conn.execute(
            "SELECT trigger_type, delivered, message_sent FROM proactive_log"
        ).fetchall()
    assert rows == [("briefing", 0, "morning line")]
    # retry_undelivered() must actually pick this row up.
    undelivered = db_helpers.get_undelivered_proactive()
    assert any(r["message_sent"] == "morning line" for r in undelivered)


def test_tick_sends_when_active_inside_window(fake_db, fake_ollama, monkeypatch):
    fake_ollama["queue"].append("morning line")
    class FakeNow:
        @staticmethod
        def now():
            import datetime as _dt
            return _dt.datetime(2026, 7, 20, 10, 30)
    monkeypatch.setattr(briefing, "datetime", FakeNow)
    with patch.object(briefing, "user_is_active", return_value=True), \
         patch.object(briefing.weather_sync, "get_current_weather",
                      return_value="22°C clear"), \
         patch.object(briefing.uni_schedule, "semester_active", return_value=False), \
         patch.object(outbox, "send_telegram_message", return_value=True) as tg:
        briefing.briefing_tick()
    assert tg.call_count == 1


def test_tick_holds_when_inactive_inside_window(fake_db, monkeypatch):
    class FakeNow:
        @staticmethod
        def now():
            import datetime as _dt
            return _dt.datetime(2026, 7, 20, 10, 30)
    monkeypatch.setattr(briefing, "datetime", FakeNow)
    with patch.object(briefing, "user_is_active", return_value=False), \
         patch.object(outbox, "send_telegram_message") as tg:
        briefing.briefing_tick()
    tg.assert_not_called()


def test_tick_fallback_at_window_end(fake_db, fake_ollama, monkeypatch):
    fake_ollama["queue"].append("morning line")
    class FakeNow:
        @staticmethod
        def now():
            import datetime as _dt
            return _dt.datetime(2026, 7, 20, 13, 5)
    monkeypatch.setattr(briefing, "datetime", FakeNow)
    with patch.object(briefing, "user_is_active", return_value=False), \
         patch.object(briefing.weather_sync, "get_current_weather",
                      return_value="22°C clear"), \
         patch.object(briefing.uni_schedule, "semester_active", return_value=False), \
         patch.object(outbox, "send_telegram_message", return_value=True) as tg:
        briefing.briefing_tick()
    assert tg.call_count == 1


def test_tick_never_fires_outside_hours(fake_db, monkeypatch):
    class FakeNow:
        @staticmethod
        def now():
            import datetime as _dt
            return _dt.datetime(2026, 7, 20, 20, 0)
    monkeypatch.setattr(briefing, "datetime", FakeNow)
    with patch.object(outbox, "send_telegram_message") as tg:
        briefing.briefing_tick()
    tg.assert_not_called()
