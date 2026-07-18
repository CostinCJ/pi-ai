from unittest.mock import patch
from datetime import datetime, timedelta
import db_helpers
import triggers


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


def test_all_triggers_is_exactly_class_soon_and_post_game():
    names = [name for name, _ in triggers.ALL_TRIGGERS]
    assert names == ["class_soon", "post_game"]
    for gone in ("free_reasoning_trigger", "pattern_surface_trigger",
                 "late_night_trigger", "session_trigger",
                 "weather_flip_trigger", "open_thread_trigger"):
        assert not hasattr(triggers, gone)
