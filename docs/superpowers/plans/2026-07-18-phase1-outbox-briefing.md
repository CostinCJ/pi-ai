# Phase 1: Trigger Cleanup + Outbox + Daily Briefing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete the dead smalltalk triggers, add a lightweight outbox (urgent vs hold-for-briefing), and ship the first-activity daily briefing.

**Architecture:** Retrofit of the existing engine (spec: `docs/superpowers/specs/2026-07-18-lache-utility-redesign-design.md`, Section 1). `outbox.py` becomes the import-leaf delivery module (Telegram send + repeat suppression move there from `autonomy.py`); `briefing.py` collects structured data and phrases it with the LLM; `autonomy.py` schedules the briefing tick and keeps only `class_soon` + `post_game` in `ALL_TRIGGERS`.

**Tech Stack:** Python 3 (venv at `/home/pi/pi-ai/venv`), SQLite, APScheduler, Groq via `llm.chat`, pytest (`fake_db` / `fake_ollama` fixtures in `tests/conftest.py`).

## Global Constraints

- Working directory: `/home/pi/pi-ai`. Run tests with `venv/bin/pytest`.
- Every `llm.chat`/`chat_json` call MUST pass explicit `num_predict` (default is 150 and truncates JSON — caused the May–July reflection outage).
- Briefing and outbox failures must fail soft: a broken section is skipped and logged, never raises out of a scheduler job.
- The briefing BYPASSES repeat suppression (`suppress_repeats=False`) and the engagement gate — it is requested utility. Trigger-class sends keep both.
- No "good morning" filler, no questions fishing for replies, nothing invented — every briefing line traces to a data field.
- Voice: lowercase, direct. Persona is flavor, not padding.
- `outbox.py` must import only `config`, `db_helpers`, stdlib, `requests` — never `autonomy` (autonomy imports outbox; a cycle breaks service startup).

---

### Task 1: `outbox.py` — delivery module + queue table

**Files:**
- Create: `outbox.py`
- Create: `tests/test_outbox.py`
- Modify: `init_db.py` (add `outbox_queue` table before the final commit in `setup_database()`)
- Modify: `autonomy.py` (delete `send_telegram_message`, `_word_overlap`, `_is_repeat`; import from outbox)
- Modify: `tests/test_engagement.py` (repeat-suppression tests point at `outbox`)

**Interfaces:**
- Consumes: `db_helpers.get_conn()`, `db_helpers.get_recent_proactive_texts(days, limit)`, config `TELEGRAM_TOKEN`, `CHAT_ID`, `PROACTIVE_REPEAT_OVERLAP`, `PROACTIVE_REPEAT_DAYS`.
- Produces (later tasks rely on these exact names):
  - `outbox.send(text: str, urgency: str = "urgent", suppress_repeats: bool = True) -> bool`
  - `outbox.drain_queue() -> list[str]`
  - `outbox.send_telegram_message(text: str) -> bool`
  - `outbox.is_repeat(message: str) -> bool`

- [ ] **Step 1: Add the `outbox_queue` table to `init_db.py`**

Inside `setup_database()`, after the last existing `cursor.execute("CREATE TABLE IF NOT EXISTS ...")` block and before the commit/close at the end of the function, add:

```python
    # Outbox: non-urgent findings queue here and drain into the next briefing.
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS outbox_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        text TEXT NOT NULL,
        consumed INTEGER DEFAULT 0
    )
    ''')
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_outbox.py`:

```python
from unittest.mock import patch
import db_helpers
import outbox


def test_briefing_urgency_queues_instead_of_sending(fake_db):
    with patch.object(outbox, "send_telegram_message") as tg:
        ok = outbox.send("ptv dropped an album", urgency="briefing")
    assert ok
    tg.assert_not_called()
    assert outbox.drain_queue() == ["ptv dropped an album"]


def test_drain_marks_consumed(fake_db):
    outbox.send("item one", urgency="briefing")
    assert outbox.drain_queue() == ["item one"]
    assert outbox.drain_queue() == []


def test_drain_drops_stale_items(fake_db):
    outbox.send("old news", urgency="briefing")
    with db_helpers.get_conn() as conn:
        conn.execute(
            "UPDATE outbox_queue SET created_at = datetime('now', '-3 days')"
        )
    assert outbox.drain_queue() == []


def test_urgent_sends_immediately(fake_db):
    with patch.object(outbox, "send_telegram_message", return_value=True) as tg:
        ok = outbox.send("disk at 91%", urgency="urgent")
    assert ok
    tg.assert_called_once_with("disk at 91%")


def test_urgent_repeat_suppressed(fake_db):
    db_helpers.log_proactive("t", "k", "disk at 91%", delivered=1)
    with patch.object(outbox, "send_telegram_message") as tg:
        ok = outbox.send("disk at 91%", urgency="urgent")
    assert not ok
    tg.assert_not_called()


def test_urgent_repeat_check_can_be_bypassed(fake_db):
    db_helpers.log_proactive("t", "k", "same text", delivered=1)
    with patch.object(outbox, "send_telegram_message", return_value=True) as tg:
        ok = outbox.send("same text", urgency="urgent", suppress_repeats=False)
    assert ok
    tg.assert_called_once()


def test_is_repeat_matches_near_identical(fake_db):
    db_helpers.log_proactive("t", "k", "still warm out huh", delivered=1)
    assert outbox.is_repeat("still warm out huh")
    assert outbox.is_repeat("it's still warm out huh")
    assert not outbox.is_repeat("cold front tonight, 12 degrees by morning")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `venv/bin/pytest tests/test_outbox.py -v`
Expected: FAIL / ERROR with `ModuleNotFoundError: No module named 'outbox'`

- [ ] **Step 4: Create `outbox.py`**

The three moved functions come verbatim from `autonomy.py` (`send_telegram_message` at ~line 105, `_word_overlap` and `_is_repeat` near the top). Full file:

```python
"""Delivery module. Import-leaf: config/db_helpers/stdlib/requests ONLY —
autonomy imports this module, so importing autonomy here is a cycle.

urgency='urgent'   -> immediate Telegram send (repeat-suppressed by default)
urgency='briefing' -> queued in outbox_queue, drained into the next briefing
"""
import logging
import requests
import db_helpers
from config import (
    TELEGRAM_TOKEN, CHAT_ID,
    PROACTIVE_REPEAT_OVERLAP, PROACTIVE_REPEAT_DAYS,
)

log = logging.getLogger(__name__)


def send_telegram_message(text):
    """Sends via Telegram. Returns True on 2xx, False otherwise. Never raises."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": CHAT_ID, "text": text}, timeout=10)
        if 200 <= r.status_code < 300:
            return True
        log.error(f"send_telegram_message non-2xx: {r.status_code} {r.text[:200]}")
        return False
    except Exception as e:
        log.error(f"send_telegram_message failed: {e}")
        return False


def _word_overlap(a, b):
    wa, wb = set(a.lower().split()), set(b.lower().split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))


def is_repeat(message):
    """True if near-identical to a recently sent proactive message."""
    for prev in db_helpers.get_recent_proactive_texts(days=PROACTIVE_REPEAT_DAYS):
        if _word_overlap(message, prev) >= PROACTIVE_REPEAT_OVERLAP:
            return True
    return False


def send(text, urgency="urgent", suppress_repeats=True):
    """Route a message. Returns True if delivered (or queued)."""
    if urgency == "briefing":
        with db_helpers.get_conn() as conn:
            conn.execute("INSERT INTO outbox_queue (text) VALUES (?)", (text,))
        return True
    if suppress_repeats and is_repeat(text):
        log.info(f"outbox: suppressed repeat: {text[:60]}")
        return False
    return send_telegram_message(text)


def drain_queue():
    """Unconsumed briefing items, oldest first; marks them consumed.
    Items older than 48h are dropped — stale news isn't news."""
    with db_helpers.get_conn() as conn:
        conn.execute(
            "DELETE FROM outbox_queue WHERE created_at < datetime('now', '-48 hours')"
        )
        rows = conn.execute(
            "SELECT id, text FROM outbox_queue WHERE consumed=0 ORDER BY id"
        ).fetchall()
        if rows:
            ids = [r[0] for r in rows]
            conn.execute(
                f"UPDATE outbox_queue SET consumed=1 WHERE id IN ({','.join('?' * len(ids))})",
                ids,
            )
    return [r[1] for r in rows]
```

- [ ] **Step 5: Rewire `autonomy.py` to use outbox**

In `autonomy.py`:
1. Delete the entire `send_telegram_message` function (the `def` plus body, ~lines 105–117).
2. Delete the `_word_overlap` and `_is_repeat` functions.
3. Delete `import requests` (nothing else in the file uses it).
4. Add to the imports near the top (after `import db_helpers`):

```python
from outbox import send_telegram_message, is_repeat
```

5. In `_handle_trigger_send`, change the repeat check call `if _is_repeat(message):` to `if is_repeat(message):`.

- [ ] **Step 6: Update `tests/test_engagement.py`**

Replace the two repeat-suppression tests at the bottom (`test_repeat_suppression_catches_near_identical` and `test_word_overlap_empty_strings`) with outbox-based versions:

```python
import outbox


def test_repeat_suppression_catches_near_identical(fake_db):
    db_helpers.log_proactive("weather_flip", "k1", "still warm out huh", delivered=1)
    assert outbox.is_repeat("still warm out huh")
    assert outbox.is_repeat("it's still warm out huh")
    assert not outbox.is_repeat("cold front rolling in tonight, 12 degrees by morning")


def test_word_overlap_empty_strings():
    assert outbox._word_overlap("", "anything") == 0.0
```

(The `import outbox` goes at the top of the file with the other imports; remove nothing else.)

- [ ] **Step 7: Run the full suite**

Run: `venv/bin/pytest -q`
Expected: all tests pass (142 before this task + 7 new in test_outbox.py, minus nothing).

- [ ] **Step 8: Commit**

```bash
git add outbox.py tests/test_outbox.py init_db.py autonomy.py tests/test_engagement.py
git commit -m "feat: outbox delivery module (urgent vs hold-for-briefing)"
```

---

### Task 2: Delete the dead triggers

**Files:**
- Modify: `triggers.py` (delete 6 trigger functions), `autonomy.py` (dead branch), `config.py`, `brain.py` (only if grep finds references — see Step 3)
- Modify: `tests/test_triggers.py`, `tests/test_session.py`
- Delete: nothing at file level

**Interfaces:**
- Produces: `triggers.ALL_TRIGGERS == [('class_soon', has_class_soon_trigger), ('post_game', post_game_trigger)]`. `home_arrival_trigger` unchanged.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_triggers.py`:

```python
def test_all_triggers_is_exactly_class_soon_and_post_game():
    names = [name for name, _ in triggers.ALL_TRIGGERS]
    assert names == ["class_soon", "post_game"]
    for gone in ("free_reasoning_trigger", "pattern_surface_trigger",
                 "late_night_trigger", "session_trigger",
                 "weather_flip_trigger", "open_thread_trigger"):
        assert not hasattr(triggers, gone)
```

Run: `venv/bin/pytest tests/test_triggers.py::test_all_triggers_is_exactly_class_soon_and_post_game -v`
Expected: FAIL (names list currently longer; attributes exist)

- [ ] **Step 2: Delete from `triggers.py`**

Delete these functions entirely: `weather_flip_trigger`, `late_night_trigger`, `pattern_surface_trigger`, `open_thread_trigger`, `free_reasoning_trigger`, `session_trigger`, and the `GAME_KEYWORDS` set. Keep: `_utc_to_local`, `_recent_scans`, `has_class_soon_trigger`, `home_arrival_trigger`, `post_game_trigger`.

Update the imports at the top — remove `random` and `weather_sync`, and remove `PATTERN_TRIGGER_PROBABILITY` from the `config` import so it reads:

```python
from collections import deque
from datetime import datetime, timezone
import db_helpers
import schedule as uni_schedule
from network_radar import phone_is_home
from config import (
    AWAY_THRESHOLD_MIN, AWAY_DEBOUNCE_SCANS,
    RIOT_PUUID,
)
import riot_client
```

Replace `ALL_TRIGGERS` with:

```python
ALL_TRIGGERS = [
    ('class_soon', has_class_soon_trigger),
    ('post_game',  post_game_trigger),
]
```

- [ ] **Step 3: Remove dead references elsewhere**

1. `autonomy.py` `heartbeat()`: delete the dead `open_thread` success-callback block:

```python
    # open_thread defers update_thread_referenced until after a successful send.
    success_callback = None
    if fired_type == 'open_thread' and fired_extra is not None:
        thread_id = fired_extra
        success_callback = lambda: db_helpers.update_thread_referenced(thread_id)

    _handle_trigger_send(fired_type, fired_context, fired_dedup_key, success_callback)
```

becomes:

```python
    _handle_trigger_send(fired_type, fired_context, fired_dedup_key)
```

2. `config.py`: delete the line `PATTERN_TRIGGER_PROBABILITY = float(_opt("PATTERN_TRIGGER_PROBABILITY", "0.30"))`.
3. Verify nothing else references the deleted names:

Run: `grep -rn 'weather_flip_trigger\|free_reasoning_trigger\|session_trigger\|late_night_trigger\|pattern_surface_trigger\|open_thread_trigger\|PATTERN_TRIGGER_PROBABILITY\|GAME_KEYWORDS' --include='*.py' . | grep -v tests/ | grep -v venv`
Expected: no output. (String labels like `'weather_flip'` in tests are fine — only function/constant references matter.)

- [ ] **Step 4: Delete their tests**

- `tests/test_triggers.py`: delete `test_weather_flip_returns_change_summary`, `test_weather_flip_dedup_same_day`, `test_weather_flip_no_change`, `test_session_trigger_detects_game`, `test_session_trigger_no_game`, `test_free_reasoning_trigger_skipped_by_probability`, `test_free_reasoning_trigger_returns_silence`, `test_free_reasoning_trigger_returns_context_string`, `test_free_reasoning_trigger_dedup`, `test_free_reasoning_trigger_handles_llm_exception`, `test_pattern_surface_trigger_in_all_triggers`. Keep the two `class_soon` tests and the new Task-2 test.
- `tests/test_session.py`: delete the four `session_trigger` tests (`test_session_trigger_no_fire_when_no_snapshot`, `test_session_trigger_no_fire_when_no_game`, `test_session_trigger_fires_when_league_detected`, `test_session_trigger_no_refire_same_day`) and the `from triggers import session_trigger` line. Keep the session-snapshot DB tests above them.

- [ ] **Step 5: Run the full suite**

Run: `venv/bin/pytest -q`
Expected: all pass. Count drops by ~15 (deleted trigger tests) and gains 1.

- [ ] **Step 6: Commit**

```bash
git add triggers.py autonomy.py config.py tests/test_triggers.py tests/test_session.py
git commit -m "feat: delete smalltalk triggers — ALL_TRIGGERS is class_soon + post_game"
```

---

### Task 3: Briefing data collection

**Files:**
- Modify: `db_helpers.py` (three new helpers)
- Create: `briefing.py` (data/activity half)
- Create: `tests/test_briefing.py`

**Interfaces:**
- Consumes: `outbox.drain_queue()`, `uni_schedule.semester_active()` / `get_todays_classes()`, `weather_sync.get_current_weather()`, `db_helpers.get_latest_session_snapshot()`.
- Produces:
  - `db_helpers.spotify_played_within(minutes: int) -> bool`
  - `db_helpers.user_messaged_today() -> bool`
  - `db_helpers.get_reminders_due_today() -> list[dict]` (keys: id, text, fire_at)
  - `briefing.collect_data() -> dict` (possible keys: `weather`, `classes`, `reminders`, `updates` — absent when empty)
  - `briefing.user_is_active() -> bool`

- [ ] **Step 1: Add config tunables**

In `config.py`, after the `# --- Open thread expiry ---` block:

```python
# --- Daily briefing ---
BRIEFING_WINDOW_START = int(_opt("BRIEFING_WINDOW_START", "9"))
BRIEFING_WINDOW_END = int(_opt("BRIEFING_WINDOW_END", "13"))  # send regardless at this hour
BRIEFING_SPOTIFY_ACTIVE_MIN = int(_opt("BRIEFING_SPOTIFY_ACTIVE_MIN", "20"))
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_briefing.py`:

```python
from unittest.mock import patch
import db_helpers
import briefing
import outbox


def _play_track(minutes_ago):
    with db_helpers.get_conn() as conn:
        conn.execute(
            "INSERT INTO spotify_tracks (artist, title, played_at) "
            "VALUES ('ptv', 'song', datetime('now', 'localtime', ?))",
            (f'-{minutes_ago} minutes',),
        )


def test_spotify_played_within(fake_db):
    _play_track(5)
    assert db_helpers.spotify_played_within(20)
    assert not db_helpers.spotify_played_within(2)


def test_user_messaged_today(fake_db):
    assert not db_helpers.user_messaged_today()
    db_helpers.log_message("user", "yo")
    assert db_helpers.user_messaged_today()


def test_reminders_due_today_only(fake_db):
    with db_helpers.get_conn() as conn:
        conn.execute(
            "INSERT INTO reminders (text, fire_at) VALUES "
            "('today thing', datetime('now', 'localtime', '+2 hours')),"
            "('tomorrow thing', datetime('now', 'localtime', '+1 day'))"
        )
    due = db_helpers.get_reminders_due_today()
    assert [r["text"] for r in due] == ["today thing"]


def test_user_is_active_via_spotify(fake_db):
    _play_track(5)
    assert briefing.user_is_active()


def test_user_not_active_when_quiet(fake_db):
    with patch.object(db_helpers, "get_latest_session_snapshot", return_value=None):
        assert not briefing.user_is_active()


def test_collect_data_skips_empty_sections(fake_db):
    outbox.send("new ptv album: X", urgency="briefing")
    with patch.object(briefing.weather_sync, "get_current_weather",
                      return_value="22.0°C, clear sky"), \
         patch.object(briefing.uni_schedule, "semester_active", return_value=False):
        data = briefing.collect_data()
    assert data["weather"] == "22.0°C, clear sky"
    assert data["updates"] == ["new ptv album: X"]
    assert "classes" not in data
    assert "reminders" not in data


def test_collect_data_survives_broken_section(fake_db):
    with patch.object(briefing.weather_sync, "get_current_weather",
                      side_effect=RuntimeError("api down")), \
         patch.object(briefing.uni_schedule, "semester_active", return_value=False):
        data = briefing.collect_data()
    assert "weather" not in data  # skipped, not raised
```

Run: `venv/bin/pytest tests/test_briefing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'briefing'`

- [ ] **Step 3: Add the db_helpers functions**

In `db_helpers.py`, after `get_due_reminders()`:

```python
def get_reminders_due_today():
    """Undelivered reminders firing later today (localtime) — briefing preview."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, text, fire_at FROM reminders "
            "WHERE delivered=0 AND date(fire_at) = date('now', 'localtime') "
            "ORDER BY fire_at ASC"
        ).fetchall()
    return [{"id": r[0], "text": r[1], "fire_at": r[2]} for r in rows]


def spotify_played_within(minutes):
    """True if a track was played in the last N minutes (played_at is localtime)."""
    with get_conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM spotify_tracks "
            "WHERE played_at > datetime('now', 'localtime', ?)",
            (f'-{int(minutes)} minutes',),
        ).fetchone()[0]
    return count > 0


def user_messaged_today():
    """True if the user sent any message today (UTC day — close enough)."""
    with get_conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM conversations "
            "WHERE sender='user' AND timestamp >= date('now')"
        ).fetchone()[0]
    return count > 0
```

- [ ] **Step 4: Create `briefing.py` (data half)**

```python
"""Daily briefing: collect structured data, phrase it in Lache's voice, send
once per day at first sign of activity (fallback: BRIEFING_WINDOW_END sharp).

Hard rule inherited from the July 2026 hallucination bug: every line of the
sent briefing must trace to a field collected here. Nothing invented.
"""
import logging
from datetime import date, datetime

import db_helpers
import outbox
import schedule as uni_schedule
import weather_sync
from config import (
    BRIEFING_WINDOW_START, BRIEFING_WINDOW_END, BRIEFING_SPOTIFY_ACTIVE_MIN,
)

log = logging.getLogger(__name__)


def user_is_active():
    """Real activity signals only. Phone-on-wifi is NOT one — the phone is
    home and online while the user sleeps."""
    try:
        if db_helpers.spotify_played_within(BRIEFING_SPOTIFY_ACTIVE_MIN):
            return True
    except Exception as e:
        log.warning(f"briefing: spotify signal failed: {e}")
    try:
        if db_helpers.get_latest_session_snapshot() is not None:
            return True
    except Exception as e:
        log.warning(f"briefing: session signal failed: {e}")
    try:
        if db_helpers.user_messaged_today():
            return True
    except Exception as e:
        log.warning(f"briefing: message signal failed: {e}")
    return False


def collect_data():
    """Structured briefing data. Sections fail soft and are absent when empty."""
    data = {}
    try:
        weather = weather_sync.get_current_weather()
        if weather and "unavailable" not in weather:
            data["weather"] = weather
    except Exception as e:
        log.warning(f"briefing: weather failed: {e}")
    try:
        if uni_schedule.semester_active():
            classes = uni_schedule.get_todays_classes()
            if "No classes" not in classes:
                data["classes"] = classes
    except Exception as e:
        log.warning(f"briefing: classes failed: {e}")
    try:
        due = db_helpers.get_reminders_due_today()
        if due:
            data["reminders"] = [f"{r['fire_at'][11:16]} {r['text']}" for r in due]
    except Exception as e:
        log.warning(f"briefing: reminders failed: {e}")
    try:
        items = outbox.drain_queue()
        if items:
            data["updates"] = items
    except Exception as e:
        log.warning(f"briefing: outbox drain failed: {e}")
    return data
```

- [ ] **Step 5: Run tests**

Run: `venv/bin/pytest tests/test_briefing.py -v`
Expected: all 8 PASS

- [ ] **Step 6: Commit**

```bash
git add config.py db_helpers.py briefing.py tests/test_briefing.py
git commit -m "feat: briefing data collection + activity signals"
```

---

### Task 4: Briefing phrasing, sending, and scheduling

**Files:**
- Modify: `briefing.py` (add compose/send/tick), `autonomy.py` (register job)
- Test: `tests/test_briefing.py` (append)

**Interfaces:**
- Consumes: `llm.chat(messages, options, timeout)`, `persona.PERSONA`, `outbox.send`, `db_helpers.mark_proactive_attempted` / `was_proactive_attempted_today` / `log_message` / `log_proactive`, `briefing.collect_data` / `user_is_active` from Task 3.
- Produces:
  - `briefing.send_briefing(force: bool = False) -> bool`
  - `briefing.briefing_tick() -> None` (self-gating scheduler job, safe to run every 10 min all day)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_briefing.py`:

```python
def _fake_data():
    return {"weather": "22°C clear", "reminders": ["15:00 print report"]}


def test_compose_uses_llm_with_explicit_num_predict(fake_db, fake_ollama):
    fake_ollama["queue"].append("22 and clear. print the report at 15:00.")
    text = briefing.compose(_fake_data())
    assert text == "22 and clear. print the report at 15:00."
    options = fake_ollama["calls"][0]["options"]
    assert options.get("num_predict"), "explicit num_predict is mandatory"


def test_compose_falls_back_to_raw_lines_when_llm_empty(fake_db, fake_ollama):
    # queue empty -> fake chat returns "" -> plain data fallback, never nothing
    text = briefing.compose(_fake_data())
    assert "22°C clear" in text
    assert "15:00 print report" in text


def test_send_briefing_once_per_day(fake_db, fake_ollama):
    fake_ollama["queue"].append("morning line")
    with patch.object(briefing.weather_sync, "get_current_weather",
                      return_value="22°C clear"), \
         patch.object(briefing.uni_schedule, "semester_active", return_value=False), \
         patch.object(outbox, "send_telegram_message", return_value=True) as tg:
        assert briefing.send_briefing()
        assert not briefing.send_briefing()  # dedup
    assert tg.call_count == 1


def test_send_briefing_skips_when_no_data(fake_db, fake_ollama):
    with patch.object(briefing.weather_sync, "get_current_weather",
                      return_value="Weather data unavailable."), \
         patch.object(briefing.uni_schedule, "semester_active", return_value=False), \
         patch.object(outbox, "send_telegram_message") as tg:
        assert not briefing.send_briefing()
    tg.assert_not_called()


def test_tick_sends_when_active_inside_window(fake_db, fake_ollama, monkeypatch):
    fake_ollama["queue"].append("morning line")
    class FakeNow:
        @staticmethod
        def now():
            import datetime as _dt
            return _dt.datetime(2026, 7, 20, 10, 30)
    monkeypatch.setattr(briefing, "datetime", FakeNow)
    with patch.object(briefing, "user_is_active", return_value=True), \
         patch.object(briefing.weather_sync, "get_current_weather",
                      return_value="22°C clear"), \
         patch.object(briefing.uni_schedule, "semester_active", return_value=False), \
         patch.object(outbox, "send_telegram_message", return_value=True) as tg:
        briefing.briefing_tick()
    assert tg.call_count == 1


def test_tick_holds_when_inactive_inside_window(fake_db, monkeypatch):
    class FakeNow:
        @staticmethod
        def now():
            import datetime as _dt
            return _dt.datetime(2026, 7, 20, 10, 30)
    monkeypatch.setattr(briefing, "datetime", FakeNow)
    with patch.object(briefing, "user_is_active", return_value=False), \
         patch.object(outbox, "send_telegram_message") as tg:
        briefing.briefing_tick()
    tg.assert_not_called()


def test_tick_fallback_at_window_end(fake_db, fake_ollama, monkeypatch):
    fake_ollama["queue"].append("morning line")
    class FakeNow:
        @staticmethod
        def now():
            import datetime as _dt
            return _dt.datetime(2026, 7, 20, 13, 5)
    monkeypatch.setattr(briefing, "datetime", FakeNow)
    with patch.object(briefing, "user_is_active", return_value=False), \
         patch.object(briefing.weather_sync, "get_current_weather",
                      return_value="22°C clear"), \
         patch.object(briefing.uni_schedule, "semester_active", return_value=False), \
         patch.object(outbox, "send_telegram_message", return_value=True) as tg:
        briefing.briefing_tick()
    assert tg.call_count == 1


def test_tick_never_fires_outside_hours(fake_db, monkeypatch):
    class FakeNow:
        @staticmethod
        def now():
            import datetime as _dt
            return _dt.datetime(2026, 7, 20, 20, 0)
    monkeypatch.setattr(briefing, "datetime", FakeNow)
    with patch.object(outbox, "send_telegram_message") as tg:
        briefing.briefing_tick()
    tg.assert_not_called()
```

Run: `venv/bin/pytest tests/test_briefing.py -v`
Expected: new tests FAIL with `AttributeError: module 'briefing' has no attribute 'compose'`

- [ ] **Step 2: Add compose/send/tick to `briefing.py`**

Append (and add `from llm import chat` and `from persona import PERSONA` to the imports):

```python
_COMPOSE_RULES = (
    "You are Lache writing the user's morning briefing from DATA.\n"
    "Rules — non-negotiable:\n"
    "- Every statement must come from a DATA field. Invent NOTHING.\n"
    "- lowercase, direct, compact. 1-4 short lines.\n"
    "- No greeting, no 'good morning', no questions, no filler, no emojis.\n"
    "- Order: weather, classes, reminders, updates. Skip absent fields.\n"
)


def _fallback_text(data):
    """LLM down or off-voice: send the raw data lines. Utility beats voice."""
    lines = []
    if "weather" in data:
        lines.append(data["weather"])
    if "classes" in data:
        lines.append(data["classes"])
    for r in data.get("reminders", []):
        lines.append(f"reminder {r}")
    lines.extend(data.get("updates", []))
    return "\n".join(lines)


def compose(data):
    if not data:
        return None
    payload = "\n".join(
        f"{key}: {value}" for key, value in data.items()
    )
    messages = [
        {"role": "system", "content": f"{PERSONA}\n\n{_COMPOSE_RULES}"},
        {"role": "user", "content": f"DATA:\n{payload}"},
    ]
    try:
        text = chat(messages, {"temperature": 0.4, "num_predict": 220}, timeout=60)
    except Exception as e:
        log.warning(f"briefing: compose LLM failed: {e}")
        text = None
    return text.strip() if text and text.strip() else _fallback_text(data)


def _dedup_key():
    return f"briefing_{date.today().isoformat()}"


def send_briefing(force=False):
    """Build and send today's briefing. Returns True if a message went out."""
    if not force and db_helpers.was_proactive_attempted_today("briefing", _dedup_key()):
        return False
    data = collect_data()
    db_helpers.mark_proactive_attempted("briefing", _dedup_key())
    if not data:
        log.info("briefing: no data at all, skipping today")
        return False
    text = compose(data)
    if not text:
        return False
    # Bypasses repeat suppression: briefings are legitimately similar day to day.
    sent = outbox.send(text, urgency="urgent", suppress_repeats=False)
    if sent:
        db_helpers.log_message("ai", text)
        db_helpers.log_proactive("briefing", _dedup_key(), text, delivered=1)
    return sent


def briefing_tick():
    """Scheduler job, every 10 min. Sends at first activity signal inside the
    window; at BRIEFING_WINDOW_END sends regardless. After that hour, nothing
    (a reboot at 15:00 must not trigger a stale 'morning' briefing)."""
    try:
        now = datetime.now()
        if db_helpers.was_proactive_attempted_today("briefing", _dedup_key()):
            return
        if now.hour < BRIEFING_WINDOW_START or now.hour > BRIEFING_WINDOW_END:
            return
        if now.hour == BRIEFING_WINDOW_END or user_is_active():
            send_briefing()
    except Exception as e:
        log.error(f"briefing_tick failed: {e}", exc_info=True)
```

- [ ] **Step 3: Register the job in `autonomy.py`**

Add `import briefing` with the other imports, and in the `__main__` block after the existing `add_job` lines:

```python
    _scheduler.add_job(briefing.briefing_tick, 'interval', minutes=10)
```

- [ ] **Step 4: Run the full suite**

Run: `venv/bin/pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add briefing.py autonomy.py tests/test_briefing.py
git commit -m "feat: daily briefing — first-activity send with 13:00 fallback"
```

---

### Task 5: Deploy and verify end-to-end

**Files:**
- Modify: `/home/pi/document.md` (What's Done note), production DB (new table via init_db)

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Create the outbox_queue table in the production DB**

Run: `venv/bin/python init_db.py`
Expected: exits 0. Verify: `sqlite3 memory.db ".schema outbox_queue"` shows the table.

- [ ] **Step 2: Full suite one last time**

Run: `venv/bin/pytest -q`
Expected: all pass.

- [ ] **Step 3: Restart services** (needs sudo — if the session can't, ask the user to run it)

Run: `sudo systemctl restart piai piaibot && systemctl is-active piai piaibot`
Expected: `active` twice.

- [ ] **Step 4: Live end-to-end check**

Run: `venv/bin/python -c "import outbox, briefing; outbox.send('test item from deploy', urgency='briefing'); print('sent:', briefing.send_briefing(force=True))"`
Expected: `sent: True` and a real Telegram briefing arrives containing weather and "test item from deploy". This is the observable proof; do not skip it.

Then check the scheduler picked up the job: `grep -i briefing /home/pi/pi-ai/autonomy.log | tail -3` after the next 10-min tick (or just confirm no startup errors: `systemctl status piai | tail -5`).

- [ ] **Step 5: Update the master briefing doc**

In `/home/pi/document.md`, under the "Added July 18, 2026 (conversation-quality overhaul)" section, append:

```markdown
### Phase 1 of utility redesign (shipped)
- `outbox.py` — delivery module: `send(text, urgency)`; `urgent` → immediate (repeat-suppressed), `briefing` → queued in `outbox_queue`, drained into the next briefing. Telegram send + repeat suppression moved here from autonomy.
- `briefing.py` — daily briefing at first activity signal (Spotify <20min / fresh laptop session / user message today; phone-on-wifi deliberately not a signal) inside 09:00–13:00, sent regardless at 13:00, once/day. Content: weather, classes (semester only), today's reminders, queued updates. LLM-phrased, strictly grounded, raw-data fallback.
- Triggers deleted: free_reasoning, pattern_surface, late_night, session, weather_flip, open_thread. `ALL_TRIGGERS` = class_soon + post_game; home_arrival unchanged on the presence job.
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: phase 1 deployed — briefing live, docs updated"
```

---

## Self-review notes

- Spec coverage (Section 1): trigger deletions ✔ (Task 2), outbox ✔ (Task 1), briefing job + activity signals + 13:00 fallback + once/day + grounding + degenerate case ✔ (Tasks 3–4), engagement-gate bypass ✔ (briefing sends via outbox directly, never through `proactive_allowed`), repeat-suppression bypass ✔ (`suppress_repeats=False`).
- Not in this plan (later phases per spec): reminders NL/recurrence/snooze (Phase 2), watchers (Phase 3), reactive mode split / Brave search / pi_control (Phase 4).
- Type consistency: `outbox.send/drain_queue/is_repeat/send_telegram_message`, `briefing.collect_data/user_is_active/compose/send_briefing/briefing_tick`, `db_helpers.spotify_played_within/user_messaged_today/get_reminders_due_today` used identically across tasks.
