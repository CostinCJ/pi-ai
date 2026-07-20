from datetime import date

import db_helpers
import autonomy
import outbox
import schedule as uni_schedule


def _seed_proactive(n, responded_ids=()):
    for i in range(n):
        row_id = db_helpers.log_proactive("free_reasoning", f"key_{i}", f"message {i}", delivered=1)
        if i in responded_ids:
            with db_helpers.get_conn() as conn:
                conn.execute("UPDATE proactive_log SET user_responded=1 WHERE id=?", (row_id,))


def test_engagement_engaged_with_little_data(fake_db):
    _seed_proactive(3)
    assert autonomy.engagement_level() == "engaged"


def test_engagement_ignored_after_window_of_silence(fake_db):
    _seed_proactive(10)
    assert autonomy.engagement_level() == "ignored"


def test_engagement_dead_after_long_silence(fake_db):
    _seed_proactive(25)
    assert autonomy.engagement_level() == "dead"


def test_engagement_recovers_on_any_reply(fake_db):
    _seed_proactive(25, responded_ids={24})
    assert autonomy.engagement_level() == "engaged"


def test_proactive_allowed_engaged_lets_everything_through(fake_db):
    _seed_proactive(2)
    assert autonomy.proactive_allowed("free_reasoning")
    assert autonomy.proactive_allowed("weather_flip")


def test_proactive_allowed_ignored_blocks_low_value(fake_db):
    _seed_proactive(10)
    assert not autonomy.proactive_allowed("free_reasoning")
    assert not autonomy.proactive_allowed("weather_flip")
    assert not autonomy.proactive_allowed("session")


def test_proactive_allowed_ignored_caps_daily_volume(fake_db):
    # 10 unanswered sends today already exceeds the ignored-level daily cap,
    # so even high-value triggers are muted until tomorrow.
    _seed_proactive(10)
    assert not autonomy.proactive_allowed("class_soon")


def test_proactive_allowed_dead_core_only(fake_db):
    _seed_proactive(25)
    assert not autonomy.proactive_allowed("class_soon")
    assert not autonomy.proactive_allowed("late_night")


def _seed_briefings(n):
    for i in range(n):
        db_helpers.log_proactive("briefing", f"briefing_2026-07-{i:02d}", f"briefing text {i}", delivered=1)


def test_engagement_ignores_briefing_rows(fake_db):
    # Briefings are delivered=1, user_responded=0 by design (they ask no
    # questions) — they must not drive engagement_level() down or consume
    # the backoff send budget.
    _seed_briefings(25)
    assert autonomy.engagement_level() == "engaged"
    responded, total = db_helpers.proactive_engagement(10)
    assert total == 0
    assert db_helpers.proactive_sent_count(hours=24) == 0


def test_repeat_suppression_catches_near_identical(fake_db):
    db_helpers.log_proactive("weather_flip", "k1", "still warm out huh", delivered=1)
    assert outbox.is_repeat("still warm out huh")
    assert outbox.is_repeat("it's still warm out huh")
    assert not outbox.is_repeat("cold front rolling in tonight, 12 degrees by morning")


def test_word_overlap_empty_strings():
    assert outbox._word_overlap("", "anything") == 0.0


def test_semester_active_ranges(monkeypatch):
    monkeypatch.setattr(uni_schedule, "SEMESTER_RANGES", "2026-02-23:2026-06-07,2026-09-28:2026-12-20")
    assert uni_schedule.semester_active(date(2026, 3, 15))
    assert uni_schedule.semester_active(date(2026, 10, 1))
    assert not uni_schedule.semester_active(date(2026, 7, 18))   # summer break
    assert not uni_schedule.semester_active(date(2026, 12, 25))  # winter break


def test_no_class_trigger_during_break(monkeypatch):
    monkeypatch.setattr(uni_schedule, "SEMESTER_RANGES", "2026-02-23:2026-06-07")
    monkeypatch.setattr(uni_schedule, "semester_active", lambda today=None: False)
    assert uni_schedule.get_next_class() is None
    assert uni_schedule.has_class_soon() is None
    assert "break" in uni_schedule.get_todays_classes()
