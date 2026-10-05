"""class_soon must be able to flag a class that started before quiet hours
ended (e.g. the 8:00 Monday Ethics lecture, while QUIET_HOURS_END=9) — otherwise
the 1h lookahead never gets a chance to see it before it's already underway,
and the user gets no heads-up for that slot at all."""
from datetime import datetime

import schedule as uni_schedule


def test_has_class_soon_flags_in_progress_class_missed_during_quiet_hours(monkeypatch):
    monkeypatch.setattr(uni_schedule, "SEMESTER_RANGES", "2026-01-01:2026-12-31")
    monkeypatch.setattr(uni_schedule, "SAPT1_ANCHOR", "2026-04-27")
    # Monday 2026-07-13 08:30: Ethics lecture 8-10 (weekly).
    now = datetime(2026, 7, 13, 8, 30)
    result = uni_schedule.has_class_soon(within_hours=1, now=now)
    assert result is not None
    assert "Ethics & Research Methodology lecture" in result
    assert "8:00" in result


def test_has_class_soon_does_not_flag_in_progress_class_outside_quiet_gap(monkeypatch):
    monkeypatch.setattr(uni_schedule, "SEMESTER_RANGES", "2026-01-01:2026-12-31")
    monkeypatch.setattr(uni_schedule, "SAPT1_ANCHOR", "2026-04-27")
    # Thursday 2026-07-23 14:30, săpt 1: Programming Paradigms lecture (14-16)
    # started well after quiet hours; the 16:00 seminar is 90min away.
    now = datetime(2026, 7, 23, 14, 30)
    assert uni_schedule.is_sapt1(now.date()) is True
    result = uni_schedule.has_class_soon(within_hours=1, now=now)
    assert result is None


def test_has_class_soon_still_returns_upcoming_class(monkeypatch):
    monkeypatch.setattr(uni_schedule, "SEMESTER_RANGES", "2026-01-01:2026-12-31")
    monkeypatch.setattr(uni_schedule, "SAPT1_ANCHOR", "2026-04-27")
    # Tuesday 2026-07-21 15:30, săpt 1: Requirements Engineering lecture
    # (16-18) is 30min away and nothing is currently in progress.
    now = datetime(2026, 7, 21, 15, 30)
    assert uni_schedule.is_sapt1(now.date()) is True
    result = uni_schedule.has_class_soon(within_hours=1, now=now)
    assert result is not None
    assert "Requirements Engineering lecture" in result
    assert "in ~30min" in result
