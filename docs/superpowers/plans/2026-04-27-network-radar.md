# Network Radar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect phone presence on the apartment WiFi via `arp-scan`, log state changes to `memory.db`, and fire a proactive Telegram message from Lache when the user arrives home after 25+ minutes away.

**Architecture:** A new `network_radar.py` module exposes `phone_is_home() -> bool | None`. A new `home_arrival_trigger()` in `triggers.py` compares the current scan result against the last logged presence state and fires on arrival transitions ≥ 25 min. A second APScheduler job `presence_check()` in `autonomy.py` runs every 2 minutes — independent of the main heartbeat and not subject to quiet hours — calling the trigger and phrasing/sending the message if it fires.

**Tech Stack:** Python 3, SQLite (via `db_helpers`), `subprocess` + `arp-scan` CLI, APScheduler (already installed), python-telegram-bot (already installed).

---

## File Map

| File | Action | What changes |
|---|---|---|
| `config.py` | Edit | Add `PHONE_MAC` constant |
| `init_db.py` | Edit | Add `presence_log` table (table 11) |
| `db_helpers.py` | Edit | Add `log_presence_event()`, `get_last_presence_event()` |
| `network_radar.py` | Create | `phone_is_home()` using `subprocess` + `arp-scan` |
| `triggers.py` | Edit | Add `home_arrival_trigger()` — NOT added to `ALL_TRIGGERS` |
| `autonomy.py` | Edit | Add `presence_check()` function + second scheduler job |
| `tests/test_network_radar.py` | Create | Tests for `phone_is_home()` |
| `tests/test_presence.py` | Create | Tests for DB helpers, trigger logic, and `presence_check()` |

> **Note on `ALL_TRIGGERS`:** `home_arrival_trigger` is intentionally NOT added to `ALL_TRIGGERS`. It is called exclusively from `presence_check()` which runs every 2 minutes. Adding it to `ALL_TRIGGERS` would double-fire it (once from heartbeat, once from presence_check) and subject it to the 90-min `was_recently_active` guard.

---

## Task 1: System Setup (one-time, no code)

**Files:** none

- [ ] **Step 1: Install arp-scan**

```bash
sudo apt install arp-scan
```

Expected output: `arp-scan` installed. Verify with:
```bash
arp-scan --version
```
Expected: `arp-scan 1.9.x` (or similar).

- [ ] **Step 2: Add sudoers entry so `pi` user can run arp-scan without a password**

```bash
sudo visudo
```

Add this line at the end of the file:
```
pi ALL=(ALL) NOPASSWD: /usr/sbin/arp-scan
```

Save and exit (`:wq` in vi). Verify:
```bash
sudo -n arp-scan -l --quiet 2>&1 | head -5
```
Expected: output listing local network devices (no password prompt). If you get `sudo: a password is required`, the sudoers line was not saved correctly.

---

## Task 2: Add `PHONE_MAC` to `config.py`

**Files:**
- Modify: `/home/pi/pi-ai/config.py:19`

- [ ] **Step 1: Add `PHONE_MAC` constant**

Open `/home/pi/pi-ai/config.py`. The current last line is:
```python
LAPTOP_MAC = 'AA-BB-CC-DD-EE-FF'
```

Add one line after it:
```python
PHONE_MAC = '<your-phone-mac>'  # e.g. 'aa:bb:cc:dd:ee:ff' — lowercase, colon-separated
```

Replace `<your-phone-mac>` with your actual phone MAC address. Find it on Android: Settings → About Phone → Status → Wi-Fi MAC. On iOS: Settings → Wi-Fi → tap your network → Wi-Fi Address.

- [ ] **Step 2: Commit**

```bash
cd /home/pi/pi-ai
git add config.py
git commit -m "feat: add PHONE_MAC to config"
```

---

## Task 3: Add `presence_log` table to `init_db.py`

**Files:**
- Modify: `/home/pi/pi-ai/init_db.py:108`

- [ ] **Step 1: Add `presence_log` CREATE TABLE after the `quality_log` block**

In `/home/pi/pi-ai/init_db.py`, after line 108 (the closing `""")` of the quality_log block), add:

```python

    # 11. Presence Log: Phone home/away state changes from network radar
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS presence_log (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            event     TEXT NOT NULL
        )
    """)
```

- [ ] **Step 2: Verify the file still runs cleanly**

```bash
cd /home/pi/pi-ai
/home/pi/pi-ai/venv/bin/python init_db.py
```

Expected: `Brain initialized. Memory structure created at: /home/pi/pi-ai/memory.db`

- [ ] **Step 3: Commit**

```bash
git add init_db.py
git commit -m "feat: add presence_log table to schema"
```

---

## Task 4: Add presence helpers to `db_helpers.py` + tests

**Files:**
- Modify: `/home/pi/pi-ai/db_helpers.py:198` (append after `log_quality_event`)
- Create: `/home/pi/pi-ai/tests/test_presence.py`

- [ ] **Step 1: Write the failing tests**

Create `/home/pi/pi-ai/tests/test_presence.py`:

```python
from datetime import datetime, timedelta
import db_helpers


def test_get_last_presence_event_returns_none_when_empty(fake_db):
    assert db_helpers.get_last_presence_event() is None


def test_log_and_get_presence_event(fake_db):
    db_helpers.log_presence_event("away")
    result = db_helpers.get_last_presence_event()
    assert result is not None
    assert result["event"] == "away"
    assert "timestamp" in result


def test_get_last_presence_event_returns_most_recent(fake_db):
    db_helpers.log_presence_event("away")
    db_helpers.log_presence_event("home")
    result = db_helpers.get_last_presence_event()
    assert result["event"] == "home"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/pi/pi-ai
/home/pi/pi-ai/venv/bin/pytest tests/test_presence.py -v
```

Expected: 3 failures with `AttributeError: module 'db_helpers' has no attribute 'get_last_presence_event'`.

- [ ] **Step 3: Add the two helpers to `db_helpers.py`**

Append to the end of `/home/pi/pi-ai/db_helpers.py` (after `log_quality_event`):

```python

def log_presence_event(event):
    with get_conn() as conn:
        conn.execute("INSERT INTO presence_log (event) VALUES (?)", (event,))


def get_last_presence_event():
    with get_conn() as conn:
        row = conn.execute(
            "SELECT event, timestamp FROM presence_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return {"event": row[0], "timestamp": row[1]} if row else None
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
/home/pi/pi-ai/venv/bin/pytest tests/test_presence.py -v
```

Expected: 3 tests PASSED.

- [ ] **Step 5: Run the full suite to check for regressions**

```bash
/home/pi/pi-ai/venv/bin/pytest -v
```

Expected: all previously passing tests still PASS.

- [ ] **Step 6: Commit**

```bash
git add db_helpers.py tests/test_presence.py
git commit -m "feat: add presence_log helpers to db_helpers"
```

---

## Task 5: Create `network_radar.py` + tests

**Files:**
- Create: `/home/pi/pi-ai/network_radar.py`
- Create: `/home/pi/pi-ai/tests/test_network_radar.py`

- [ ] **Step 1: Write the failing tests**

Create `/home/pi/pi-ai/tests/test_network_radar.py`:

```python
from unittest.mock import patch, MagicMock
import network_radar


def _mock_run(stdout):
    result = MagicMock()
    result.stdout = stdout
    return result


def test_phone_is_home_true():
    with patch("network_radar.PHONE_MAC", "aa:bb:cc:dd:ee:ff"), \
         patch("network_radar.subprocess.run", return_value=_mock_run(
             "192.168.1.10\taa:bb:cc:dd:ee:ff\tApple, Inc.\n"
         )):
        assert network_radar.phone_is_home() is True


def test_phone_is_home_false():
    with patch("network_radar.PHONE_MAC", "aa:bb:cc:dd:ee:ff"), \
         patch("network_radar.subprocess.run", return_value=_mock_run(
             "192.168.1.1\t11:22:33:44:55:66\tTP-Link\n"
         )):
        assert network_radar.phone_is_home() is False


def test_phone_is_home_none_on_exception():
    with patch("network_radar.subprocess.run", side_effect=Exception("not found")):
        assert network_radar.phone_is_home() is None


def test_phone_is_home_case_insensitive():
    with patch("network_radar.PHONE_MAC", "AA:BB:CC:DD:EE:FF"), \
         patch("network_radar.subprocess.run", return_value=_mock_run(
             "192.168.1.10\taa:bb:cc:dd:ee:ff\tApple\n"
         )):
        assert network_radar.phone_is_home() is True
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
/home/pi/pi-ai/venv/bin/pytest tests/test_network_radar.py -v
```

Expected: `ModuleNotFoundError: No module named 'network_radar'`.

- [ ] **Step 3: Create `network_radar.py`**

Create `/home/pi/pi-ai/network_radar.py`:

```python
import subprocess
from config import PHONE_MAC


def phone_is_home():
    """
    Returns True if PHONE_MAC is visible on the LAN via arp-scan.
    Returns False if scan succeeded but MAC not found.
    Returns None if the scan failed (not installed, timeout, permission error).
    """
    try:
        result = subprocess.run(
            ['sudo', 'arp-scan', '-l', '--quiet'],
            capture_output=True, text=True, timeout=15
        )
        return PHONE_MAC.lower() in result.stdout.lower()
    except Exception:
        return None
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
/home/pi/pi-ai/venv/bin/pytest tests/test_network_radar.py -v
```

Expected: 4 tests PASSED.

- [ ] **Step 5: Run the full suite**

```bash
/home/pi/pi-ai/venv/bin/pytest -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add network_radar.py tests/test_network_radar.py
git commit -m "feat: add network_radar module with phone_is_home()"
```

---

## Task 6: Add `home_arrival_trigger()` to `triggers.py` + tests

**Files:**
- Modify: `/home/pi/pi-ai/triggers.py` (append before `ALL_TRIGGERS`)
- Modify: `/home/pi/pi-ai/tests/test_presence.py` (add trigger tests)

- [ ] **Step 1: Write the failing tests**

Append to `/home/pi/pi-ai/tests/test_presence.py`:

```python
from unittest.mock import patch
from datetime import datetime, timedelta
from triggers import home_arrival_trigger


def _insert_presence(event, minutes_ago):
    ts = (datetime.now() - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%d %H:%M:%S")
    with db_helpers.get_conn() as conn:
        conn.execute(
            "INSERT INTO presence_log (event, timestamp) VALUES (?, ?)",
            (event, ts)
        )


def test_home_arrival_fires_after_long_absence(fake_db):
    _insert_presence("away", 35)
    with patch("triggers.phone_is_home", return_value=True):
        fired, context = home_arrival_trigger()
    assert fired is True
    assert "got home" in context
    assert "35min" in context or "34min" in context or "36min" in context  # ±1 min tolerance


def test_home_arrival_no_fire_short_trip(fake_db):
    _insert_presence("away", 10)
    with patch("triggers.phone_is_home", return_value=True):
        fired, context = home_arrival_trigger()
    assert fired is False


def test_home_arrival_no_fire_scanner_failed(fake_db):
    _insert_presence("away", 60)
    with patch("triggers.phone_is_home", return_value=None):
        fired, context = home_arrival_trigger()
    assert fired is False


def test_home_arrival_logs_away_on_departure(fake_db):
    _insert_presence("home", 5)
    with patch("triggers.phone_is_home", return_value=False):
        fired, _ = home_arrival_trigger()
    assert fired is False
    last = db_helpers.get_last_presence_event()
    assert last["event"] == "away"


def test_home_arrival_no_refire_when_already_home(fake_db):
    _insert_presence("home", 5)
    with patch("triggers.phone_is_home", return_value=True):
        fired, _ = home_arrival_trigger()
    assert fired is False


def test_home_arrival_fires_no_previous_event_then_away(fake_db):
    # No prior events: phone seen for first time → log home, don't fire (no away reference)
    with patch("triggers.phone_is_home", return_value=True):
        fired, _ = home_arrival_trigger()
    assert fired is False
    last = db_helpers.get_last_presence_event()
    assert last["event"] == "home"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
/home/pi/pi-ai/venv/bin/pytest tests/test_presence.py -v -k "home_arrival"
```

Expected: `ImportError: cannot import name 'home_arrival_trigger' from 'triggers'`.

- [ ] **Step 3: Add `home_arrival_trigger()` to `triggers.py`**

In `/home/pi/pi-ai/triggers.py`, add the import at the top (after existing imports on line 6):

```python
from network_radar import phone_is_home
```

Then append the function before the `ALL_TRIGGERS` list (before line 110):

```python

def home_arrival_trigger():
    is_home = phone_is_home()
    if is_home is None:
        return False, ""

    last = db_helpers.get_last_presence_event()
    now = datetime.now()

    if is_home:
        if last is None or last["event"] == "away":
            if last is not None:
                away_since = datetime.strptime(last["timestamp"], "%Y-%m-%d %H:%M:%S")
                minutes_away = int((now - away_since).total_seconds() / 60)
            else:
                minutes_away = 0

            db_helpers.log_presence_event("home")

            if minutes_away < 25:
                return False, ""

            hours = minutes_away // 60
            mins = minutes_away % 60
            duration_str = f"{hours}h {mins}min" if hours > 0 else f"{mins}min"
            arrival_time = now.strftime("%H:%M")
            context = f"user just got home at {arrival_time}, was out for {duration_str}"
            return True, context
        return False, ""
    else:
        if last is None or last["event"] == "home":
            db_helpers.log_presence_event("away")
        return False, ""

```

> **Do NOT add `home_arrival_trigger` to `ALL_TRIGGERS`** — it is called directly by `presence_check()` in autonomy.py, which runs every 2 minutes. Adding it to `ALL_TRIGGERS` would double-fire it.

- [ ] **Step 4: Run the trigger tests**

```bash
/home/pi/pi-ai/venv/bin/pytest tests/test_presence.py -v
```

Expected: all tests PASS. The duration test uses ±1 minute tolerance to account for test execution time.

- [ ] **Step 5: Run the full suite**

```bash
/home/pi/pi-ai/venv/bin/pytest -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add triggers.py tests/test_presence.py
git commit -m "feat: add home_arrival_trigger to triggers"
```

---

## Task 7: Add `presence_check()` to `autonomy.py` + test

**Files:**
- Modify: `/home/pi/pi-ai/autonomy.py`
- Modify: `/home/pi/pi-ai/tests/test_presence.py` (append one test)

- [ ] **Step 1: Write the failing test**

Append to `/home/pi/pi-ai/tests/test_presence.py`:

```python
import autonomy


def test_presence_check_sends_message_on_arrival(fake_db):
    """presence_check must phrase using PERSONA system prompt and send when trigger fires."""
    captured = {}

    def fake_chat_with_retry(messages, options=None, timeout=60, retry_hint=None):
        captured["messages"] = messages
        return "back already?", True

    with patch("autonomy.home_arrival_trigger",
               return_value=(True, "user just got home at 01:34, was out for 1h 12min")), \
         patch("autonomy.chat_with_retry", fake_chat_with_retry), \
         patch("autonomy.send_telegram_message") as mock_send, \
         patch("autonomy.db_helpers.log_message"), \
         patch("autonomy.db_helpers.mark_proactive_attempted"), \
         patch("autonomy.db_helpers.log_proactive"):
        autonomy.presence_check()

    assert mock_send.call_count == 1
    assert mock_send.call_args[0][0] == "back already?"
    msgs = captured["messages"]
    assert msgs[0]["role"] == "system"
    assert "Lache" in msgs[0]["content"]
    assert "01:34" in msgs[1]["content"] or "1h 12min" in msgs[1]["content"]
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
/home/pi/pi-ai/venv/bin/pytest tests/test_presence.py::test_presence_check_sends_message_on_arrival -v
```

Expected: `AttributeError: module 'autonomy' has no attribute 'presence_check'`.

- [ ] **Step 3: Add `presence_check()` and second scheduler job to `autonomy.py`**

In `/home/pi/pi-ai/autonomy.py`:

**a)** Add import at the top (after `from triggers import ALL_TRIGGERS` on line 8):
```python
from triggers import ALL_TRIGGERS, home_arrival_trigger
```

**b)** Add `presence_check()` function after `heartbeat()` and before `if __name__ == '__main__':` (after line 83):

```python

def presence_check():
    t0 = _time.time()
    try:
        should_speak, context_str = home_arrival_trigger()
    except Exception as e:
        logging.error(f"presence_check trigger error: {e}")
        return

    if not should_speak:
        return

    phrasing_messages = [
        {"role": "system", "content": (
            f"{PERSONA}\n\n"
            "You will be given a one-line idea. Rephrase it in Lache's voice. "
            "Output ONE casual lowercase sentence, max 20 words. No emojis, "
            "no metaphors, no compliments, no follow-up explanation. If the "
            "idea is empty, reply with the literal word SILENCE."
        )},
        {"role": "user", "content": context_str},
    ]
    try:
        message, ok = chat_with_retry(
            phrasing_messages,
            {"temperature": 0.7, "num_predict": 60},
            timeout=60,
        )
    except Exception as e:
        logging.error(f"LLM phrasing failed for home_arrival: {e}")
        return

    if not ok or not message or message.strip().upper() == "SILENCE":
        latency = int((_time.time() - t0) * 1000)
        logging.info(f"presence_check: silence latency_ms={latency}")
        db_helpers.mark_proactive_attempted('home_arrival', context_str[:100])
        return

    db_helpers.log_message('ai', message)
    db_helpers.mark_proactive_attempted('home_arrival', context_str[:100])
    db_helpers.log_proactive('home_arrival', context_str[:100], message)
    send_telegram_message(message)

    latency = int((_time.time() - t0) * 1000)
    logging.info(f"presence_check: sent home_arrival latency_ms={latency}")

```

**c)** In the `if __name__ == '__main__':` block, add the second scheduler job (after the existing `scheduler.add_job` line):

```python
    scheduler.add_job(presence_check, 'interval', minutes=2)
```

The full `__main__` block should look like:
```python
if __name__ == '__main__':
    scheduler = BackgroundScheduler()
    scheduler.add_job(heartbeat, 'interval', minutes=10)
    scheduler.add_job(presence_check, 'interval', minutes=2)
    scheduler.start()
    try:
        while True:
            _time.sleep(2)
    except KeyboardInterrupt:
        scheduler.shutdown()
```

- [ ] **Step 4: Run the test**

```bash
/home/pi/pi-ai/venv/bin/pytest tests/test_presence.py::test_presence_check_sends_message_on_arrival -v
```

Expected: PASS.

- [ ] **Step 5: Run the full suite**

```bash
/home/pi/pi-ai/venv/bin/pytest -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add autonomy.py tests/test_presence.py
git commit -m "feat: add presence_check() job to autonomy — fires every 2 min"
```

---

## Task 8: Migrate live DB and restart services

**Files:** none (runtime migration + service restart)

- [ ] **Step 1: Add `presence_log` to the live database**

```bash
cd /home/pi/pi-ai
/home/pi/pi-ai/venv/bin/python init_db.py
```

Expected: `Brain initialized. Memory structure created at: /home/pi/pi-ai/memory.db`

Verify the table was created:
```bash
sqlite3 /home/pi/pi-ai/memory.db ".tables"
```

Expected: `presence_log` appears in the output alongside the existing tables.

- [ ] **Step 2: Restart both services to pick up the code changes**

```bash
sudo systemctl restart piai piaibot
```

- [ ] **Step 3: Verify both services are running**

```bash
sudo systemctl status piai piaibot --no-pager
```

Expected: both show `Active: active (running)`.

- [ ] **Step 4: Smoke-test the scanner manually**

```bash
cd /home/pi/pi-ai
/home/pi/pi-ai/venv/bin/python -c "
from network_radar import phone_is_home
result = phone_is_home()
print('phone_is_home() =', result)
"
```

Expected: `True` if your phone is on WiFi, `False` if it isn't, `None` if arp-scan failed.

- [ ] **Step 5: Tail the autonomy log to confirm presence_check ticks**

```bash
tail -f /home/pi/pi-ai/autonomy.log
```

Wait ~2 minutes. You should see `presence_check` log lines appearing alongside the existing `heartbeat` lines. `Ctrl+C` to exit.

- [ ] **Step 6: End-to-end test**

Turn your phone's WiFi off. Wait 2–3 minutes (for the scanner to detect the departure and log `away`). Turn WiFi back on. Within 2 minutes you should receive a Telegram message from Lache.

Verify the presence_log:
```bash
sqlite3 /home/pi/pi-ai/memory.db "SELECT * FROM presence_log ORDER BY id DESC LIMIT 5;"
```

Expected: rows showing the `away` and `home` state transitions with timestamps.
