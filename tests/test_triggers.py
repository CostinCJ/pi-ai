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


def test_free_reasoning_trigger_skipped_by_probability(fake_db, monkeypatch):
    import triggers
    monkeypatch.setattr(triggers.random, "random", lambda: 0.99)
    ok, _ = triggers.free_reasoning_trigger()
    assert ok is False


def test_free_reasoning_trigger_returns_silence(fake_db, monkeypatch):
    import triggers, llm
    monkeypatch.setattr(triggers.random, "random", lambda: 0.0)
    monkeypatch.setattr(llm, "chat", lambda messages, options=None, timeout=60: "SILENCE")
    result = triggers.free_reasoning_trigger()
    assert result[0] is False


def test_free_reasoning_trigger_returns_context_string(fake_db, monkeypatch):
    import triggers, llm
    monkeypatch.setattr(triggers.random, "random", lambda: 0.0)
    monkeypatch.setattr(
        llm, "chat",
        lambda messages, options=None, timeout=60: "user mentioned guitar 3 days ago"
    )
    result = triggers.free_reasoning_trigger()
    assert result[0] is True
    assert result[1] == "user mentioned guitar 3 days ago"
    assert result[2].startswith("free_reasoning_")


def test_free_reasoning_trigger_dedup(fake_db, monkeypatch):
    import triggers, llm, db_helpers
    from datetime import datetime
    monkeypatch.setattr(triggers.random, "random", lambda: 0.0)
    trigger_key = f"free_reasoning_{datetime.now().strftime('%Y-%m-%d')}"
    db_helpers.mark_proactive_attempted("free_reasoning", trigger_key)
    monkeypatch.setattr(
        llm, "chat",
        lambda messages, options=None, timeout=60: "something interesting"
    )
    result = triggers.free_reasoning_trigger()
    assert result[0] is False


def test_free_reasoning_trigger_handles_llm_exception(fake_db, monkeypatch):
    import triggers, llm
    monkeypatch.setattr(triggers.random, "random", lambda: 0.0)

    def raise_err(*a, **kw):
        raise RuntimeError("groq down")

    monkeypatch.setattr(llm, "chat", raise_err)
    result = triggers.free_reasoning_trigger()
    assert result[0] is False


def test_pattern_surface_trigger_in_all_triggers():
    keys = [t[0] for t in triggers.ALL_TRIGGERS]
    assert "pattern_surface" in keys
