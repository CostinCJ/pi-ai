from datetime import datetime, date

# Week parity: săpt 1 = odd ISO week, săpt 2 = even ISO week
# If your schedule feels flipped, change this to: week % 2 == 0
def is_sapt1():
    return datetime.now().isocalendar()[1] % 2 == 0

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

def get_todays_classes():
    day = datetime.now().weekday()
    slots = TIMETABLE.get(day, [])
    if not slots:
        return "No classes today."

    sapt1 = is_sapt1()
    active = []
    for s in slots:
        if s["every"]:
            active.append(s)
        elif s["week"] == 1 and sapt1:
            active.append(s)
        elif s["week"] == 2 and not sapt1:
            active.append(s)

    if not active:
        return "No classes today (off week)."

    parts = [f"{s['subject']} {s['start']}:00-{s['end']}:00 ({s['room']})" for s in active]
    return "Classes today: " + ", ".join(parts)

def get_next_class():
    """Returns the next upcoming class today, or None if none left."""
    day = datetime.now().weekday()
    now_hour = datetime.now().hour
    slots = TIMETABLE.get(day, [])
    sapt1 = is_sapt1()

    for s in sorted(slots, key=lambda x: x["start"]):
        if s["start"] <= now_hour:
            continue
        if s["every"]:
            return s
        if s["week"] == 1 and sapt1:
            return s
        if s["week"] == 2 and not sapt1:
            return s
    return None

def has_class_soon(within_hours=2):
    """Returns a string like 'TRSI curs in ~1h' or None."""
    next_class = get_next_class()
    if not next_class:
        return None
    hours_away = next_class["start"] - datetime.now().hour
    if 0 < hours_away <= within_hours:
        return f"{next_class['subject']} in ~{hours_away}h ({next_class['room']})"
    return None
