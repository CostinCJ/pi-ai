from datetime import datetime, date, timedelta
from config import SAPT1_ANCHOR, SEMESTER_RANGES


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


def is_sapt1():
    """Anchor-based parity. Each ISO week increments parity by 1."""
    today = date.today()
    anchor = _anchor_date()
    today_iso = today.isocalendar()
    anchor_iso = anchor.isocalendar()
    delta_weeks = (today_iso[0] - anchor_iso[0]) * 52 + (today_iso[1] - anchor_iso[1])
    return delta_weeks % 2 == 0


TIMETABLE = {
    0: [  # Luni
        {"start": 14, "end": 16, "subject": "OS lab", "room": "L001", "every": True},
    ],
    1: [  # Marți
        {"start": 14, "end": 16, "subject": "OS seminar", "room": "L001", "every": False, "week": 2},
    ],
    2: [  # Miercuri
        {"start": 12, "end": 14, "subject": "VVSS seminar", "room": "C510", "every": False, "week": 1},
        {"start": 14, "end": 16, "subject": "Calcul numeric lab", "room": "L439", "every": True},
        {"start": 16, "end": 18, "subject": "VVSS lab", "room": "DC405", "every": False, "week": 1},
        {"start": 18, "end": 20, "subject": "Etică", "room": "2/I", "every": True},
    ],
    3: [  # Joi
        {"start": 8,  "end": 10, "subject": "TRSI lab", "room": "L336", "every": False, "week": 2},
        {"start": 10, "end": 12, "subject": "TRSI curs", "room": "C335", "every": True},
        {"start": 16, "end": 18, "subject": "OOP lab", "room": "L002", "every": True},
        {"start": 18, "end": 20, "subject": "CVDL lab", "room": "L439", "every": False, "week": 2},
    ],
    4: [  # Vineri
        {"start": 14, "end": 16, "subject": "Licență lab", "room": "L404", "every": False, "week": 1},
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


def get_next_class():
    """Returns the next upcoming class today, or None if none left."""
    if not semester_active():
        return None
    now = datetime.now()
    day = now.weekday()
    slots = TIMETABLE.get(day, [])
    sapt1 = is_sapt1()
    for s in sorted(slots, key=lambda x: x["start"]):
        slot_dt = now.replace(hour=s["start"], minute=0, second=0, microsecond=0)
        if slot_dt <= now:
            continue
        if _slot_active(s, sapt1):
            return s
    return None


def has_class_soon(within_hours=2):
    """Returns a string like 'TRSI curs in ~45min' or None."""
    next_class = get_next_class()
    if not next_class:
        return None
    now = datetime.now()
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
