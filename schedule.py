from datetime import datetime, date, timedelta
from config import SAPT1_ANCHOR, SEMESTER_RANGES, QUIET_HOURS_END


def _anchor_date():
    """Returns the configured săpt-1 reference date as a `date`."""
    return datetime.strptime(SAPT1_ANCHOR, "%Y-%m-%d").date()


def _semester_ranges():
    ranges = []
    for part in SEMESTER_RANGES.split(","):
        part = part.strip()
        if not part:
            continue
        start_s, end_s = part.split(":")
        ranges.append((
            datetime.strptime(start_s.strip(), "%Y-%m-%d").date(),
            datetime.strptime(end_s.strip(), "%Y-%m-%d").date(),
        ))
    return ranges


def semester_active(today=None):
    """True only inside a configured semester range. Outside (summer/winter
    break, exam sessions past the end date) the timetable is dead."""
    today = today or date.today()
    return any(start <= today <= end for start, end in _semester_ranges())


def is_sapt1(today=None):
    """Anchor-based parity: weeks elapsed between the Mondays of the two
    weeks. (ISO week arithmetic with `year_diff * 52` breaks on 53-week ISO
    years like 2026 and flips the parity for every later year.)"""
    today = today or date.today()
    anchor = _anchor_date()
    monday = today - timedelta(days=today.weekday())
    anchor_monday = anchor - timedelta(days=anchor.weekday())
    delta_weeks = (monday - anchor_monday).days // 7
    return delta_weeks % 2 == 0


TIMETABLE = {
    # Year 1 Sem 1, Software Engineering (English), group 248/1
    0: [  # Monday
        {"start": 8,  "end": 10, "subject": "Ethics & Research Methodology lecture", "room": "C335", "every": True},
        {"start": 16, "end": 18, "subject": "Agile lecture", "room": "C335", "every": True},
    ],
    1: [  # Tuesday
        {"start": 16, "end": 18, "subject": "Requirements Engineering lecture", "room": "DC401", "every": True},
        {"start": 18, "end": 20, "subject": "Agile seminar", "room": "DC401", "every": False, "week": 1},
        {"start": 18, "end": 20, "subject": "Requirements Engineering seminar", "room": "DC402", "every": False, "week": 2},
    ],
    3: [  # Thursday
        {"start": 14, "end": 16, "subject": "Programming Paradigms lecture", "room": "C335", "every": True},
        {"start": 16, "end": 18, "subject": "Programming Paradigms seminar", "room": "DC402", "every": False, "week": 1},
    ],
    4: [  # Friday
        {"start": 14, "end": 16, "subject": "Ethics & Research Methodology seminar", "room": "5/I", "every": False, "week": 2},
        {"start": 16, "end": 18, "subject": "Sustainable SE lecture", "room": "C036", "every": True},
        {"start": 18, "end": 20, "subject": "Sustainable SE seminar", "room": "L402", "every": False, "week": 1},
    ],
}


def _slot_active(slot, sapt1):
    if slot["every"]:
        return True
    if slot["week"] == 1 and sapt1:
        return True
    if slot["week"] == 2 and not sapt1:
        return True
    return False


def get_todays_classes():
    if not semester_active():
        return "No classes — semester break."
    day = datetime.now().weekday()
    slots = TIMETABLE.get(day, [])
    if not slots:
        return "No classes today."
    sapt1 = is_sapt1()
    active = [s for s in slots if _slot_active(s, sapt1)]
    if not active:
        return "No classes today (off week)."
    parts = [f"{s['subject']} {s['start']}:00-{s['end']}:00 ({s['room']})" for s in active]
    return "Classes today: " + ", ".join(parts)


def get_current_class(now=None):
    """Returns the slot active right now, or None."""
    now = now or datetime.now()
    if not semester_active(now.date()):
        return None
    day = now.weekday()
    slots = TIMETABLE.get(day, [])
    sapt1 = is_sapt1(now.date())
    for s in slots:
        if not _slot_active(s, sapt1):
            continue
        start_dt = now.replace(hour=s["start"], minute=0, second=0, microsecond=0)
        end_dt = now.replace(hour=s["end"], minute=0, second=0, microsecond=0)
        if start_dt <= now < end_dt:
            return s
    return None


def get_next_class(now=None):
    """Returns the next upcoming class today, or None if none left."""
    now = now or datetime.now()
    if not semester_active(now.date()):
        return None
    day = now.weekday()
    slots = TIMETABLE.get(day, [])
    sapt1 = is_sapt1(now.date())
    for s in sorted(slots, key=lambda x: x["start"]):
        slot_dt = now.replace(hour=s["start"], minute=0, second=0, microsecond=0)
        if slot_dt <= now:
            continue
        if _slot_active(s, sapt1):
            return s
    return None


def has_class_soon(within_hours=2, now=None):
    """Returns a string like 'Agile lecture in ~45min' or None.

    Also flags a class already in progress if it started before
    QUIET_HOURS_END: quiet hours mean the normal "in ~Xmin" heads-up never
    gets a chance to fire before an early class (e.g. an 8:00 lab) starts, so
    the first tick after quiet hours must still be able to say something.
    """
    now = now or datetime.now()
    current = get_current_class(now=now)
    if current and current["start"] < QUIET_HOURS_END:
        return (
            f"{current['subject']} started at {current['start']}:00, "
            f"ends {current['end']}:00 ({current['room']})"
        )
    next_class = get_next_class(now=now)
    if not next_class:
        return None
    slot_dt = now.replace(hour=next_class["start"], minute=0, second=0, microsecond=0)
    delta = slot_dt - now
    if delta.total_seconds() <= 0:
        return None
    if delta > timedelta(hours=within_hours):
        return None
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        when = f"{minutes}min"
    else:
        h = minutes // 60
        m = minutes % 60
        when = f"{h}h" if m == 0 else f"{h}h{m}min"
    return f"{next_class['subject']} in ~{when} ({next_class['room']})"
