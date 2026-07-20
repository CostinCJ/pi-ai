"""class_soon must be able to flag a class that started before quiet hours
ended (e.g. the 8:00 Thursday TRSI lab, while QUIET_HOURS_END=9) — otherwise
the 1h lookahead never gets a chance to see it before it's already underway,
and the user gets no heads-up for that slot at all."""
from datetime import datetime

import schedule as uni_schedule


def test_has_class_soon_flags_in_progress_class_missed_during_quiet_hours(monkeypatch):
    monkeypatch.setattr(uni_schedule, "SEMESTER_RANGES", "2026-01-01:2026-12-31")
    monkeypatch.setattr(uni_schedule, "SAPT1_ANCHOR", "2026-04-27")
    # Thursday 2026-07-16 08:30, săpt 2 (TRSI lab 8-10 is week=2 only).
    now = datetime(2026, 7, 16, 8, 30)
    assert uni_schedule.is_sapt1(now.date()) is False
    result = uni_schedule.has_class_soon(within_hours=1, now=now)
    assert result is not None
    assert "TRSI lab" in result
    assert "8:00" in result


def test_has_class_soon_does_not_flag_in_progress_class_outside_quiet_gap(monkeypatch):
    monkeypatch.setattr(uni_schedule, "SEMESTER_RANGES", "2026-01-01:2026-12-31")
    monkeypatch.setattr(uni_schedule, "SAPT1_ANCHOR", "2026-04-27")
    # Friday 2026-07-24 14:30, săpt 1 (Licență lab 14-16 is week=1, the only
    # slot that day) — already started well after quiet hours, no next class.
    now = datetime(2026, 7, 24, 14, 30)
    assert uni_schedule.is_sapt1(now.date()) is True
    result = uni_schedule.has_class_soon(within_hours=1, now=now)
    assert result is None


def test_has_class_soon_still_returns_upcoming_class(monkeypatch):
    monkeypatch.setattr(uni_schedule, "SEMESTER_RANGES", "2026-01-01:2026-12-31")
    monkeypatch.setattr(uni_schedule, "SAPT1_ANCHOR", "2026-04-27")
    # Wednesday 2026-07-22 11:30, săpt 1: VVSS seminar (12-14, week=1) is
    # 30min away and nothing is currently in progress.
    now = datetime(2026, 7, 22, 11, 30)
    assert uni_schedule.is_sapt1(now.date()) is True
    result = uni_schedule.has_class_soon(within_hours=1, now=now)
    assert result is not None
    assert "VVSS seminar" in result
    assert "in ~30min" in result
