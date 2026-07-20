"""is_sapt1 must survive ISO-year boundaries. 2026 has 53 ISO weeks, so any
`year_diff * 52` arithmetic flips parity for every date in 2027+."""
from datetime import date

import schedule as uni_schedule


def test_sapt1_parity_near_anchor(monkeypatch):
    monkeypatch.setattr(uni_schedule, "SAPT1_ANCHOR", "2026-04-27")
    assert uni_schedule.is_sapt1(date(2026, 4, 27)) is True
    assert uni_schedule.is_sapt1(date(2026, 5, 4)) is False
    assert uni_schedule.is_sapt1(date(2026, 5, 3)) is True  # Sunday, same week


def test_sapt1_parity_across_53_week_iso_year(monkeypatch):
    monkeypatch.setattr(uni_schedule, "SAPT1_ANCHOR", "2026-04-27")
    # 2027-03-01 is exactly 44 calendar weeks after the anchor Monday -> săpt 1.
    assert (date(2027, 3, 1) - date(2026, 4, 27)).days == 44 * 7
    assert uni_schedule.is_sapt1(date(2027, 3, 1)) is True
    assert uni_schedule.is_sapt1(date(2027, 3, 8)) is False


def test_sapt1_defaults_to_today(monkeypatch):
    monkeypatch.setattr(uni_schedule, "SAPT1_ANCHOR", "2026-04-27")
    assert uni_schedule.is_sapt1() == uni_schedule.is_sapt1(date.today())
