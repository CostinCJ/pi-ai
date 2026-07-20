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


def test_post_game_skips_match_already_in_log(fake_db, monkeypatch):
    """The daily proactive_state dedup resets at midnight; riot_match_log is
    the persistent record. A match announced once must never re-fire the next
    day just because it's still the most recent one."""
    monkeypatch.setattr(triggers, "RIOT_PUUID", "puuid1", raising=False)
    with db_helpers.get_conn() as conn:
        conn.execute(
            "INSERT INTO riot_match_log (match_id, played_at) VALUES ('EUN1_1', datetime('now'))"
        )
    with patch("triggers.riot_client.get_recent_match_ids", return_value=["EUN1_1"]), \
         patch("triggers.riot_client.get_match") as get_match:
        result = triggers.post_game_trigger()
    assert result[0] is False
    get_match.assert_not_called()
