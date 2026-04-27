# Network Radar — Design Spec
_Date: 2026-04-27_

## Goal

Detect when the user's phone connects to the apartment WiFi after an absence of 25+ minutes. Log presence state changes to `memory.db`. Fire a proactive Telegram message from Lache when the user gets home.

---

## Architecture

Six components, all additions or minimal edits to existing files:

| Component | Change |
|---|---|
| `config.py` | Add `PHONE_MAC` constant |
| `network_radar.py` | New file — `phone_is_home()` scanner |
| `init_db.py` | Add `presence_log` table |
| `db_helpers.py` | Add `get_last_presence_event()`, `log_presence_event()` |
| `triggers.py` | Add `home_arrival_trigger()` + entry in `ALL_TRIGGERS` |
| `autonomy.py` | Add `presence_check()` APScheduler job (every 2 min) |

---

## Data Layer

### `presence_log` table

```sql
CREATE TABLE IF NOT EXISTS presence_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    event     TEXT NOT NULL   -- 'home' or 'away'
)
```

Logs **state changes only** — not every scan result. A typical day: one `away` row when the user leaves, one `home` row when they return.

### `db_helpers.py` additions

```python
def get_last_presence_event():
    # Returns {"event": "away"|"home", "timestamp": "..."} or None

def log_presence_event(event):
    # Writes one row to presence_log
```

### `config.py` addition

```python
PHONE_MAC = '<your-phone-mac>'  # e.g. 'aa:bb:cc:dd:ee:ff'
```

---

## Scanner: `network_radar.py`

```python
import subprocess
from config import PHONE_MAC

def phone_is_home() -> bool | None:
    """
    Returns True if PHONE_MAC is visible on the LAN.
    Returns False if scan succeeded but MAC not found.
    Returns None if scan failed (arp-scan not installed, timeout, etc.)
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

**Setup required (one-time):**
```bash
sudo apt install arp-scan
sudo visudo  # add: pi ALL=(ALL) NOPASSWD: /usr/sbin/arp-scan
```

`None` return value means the scanner failed — callers must skip any state update on `None` to avoid false `away` events.

---

## Trigger: `home_arrival_trigger()`

Added to `triggers.py`. Placed second in `ALL_TRIGGERS` (after `class_soon`).

**Logic per call:**

1. Call `phone_is_home()`
2. If `None` (scanner failed) → return `False, ""`
3. Get `last_event` from `presence_log`
4. **Phone home + last event was `'away'`** (arrival transition):
   - Calculate away duration: `now - last_event["timestamp"]`
   - Log `'home'` to `presence_log`
   - If duration ≥ 25 min → return `True` with context string
   - If duration < 25 min → return `False` (short errand, not worth messaging)
5. **Phone away + last event was `'home'` or no events** (departure transition):
   - Log `'away'` to `presence_log`
   - Return `False`
6. **No state change** → return `False`

**Context string (passed to LLM for phrasing):**
```
"user just got home at 01:34, was out for 1h 12min"
```

**Natural dedup:** The trigger fires only on the `home` state-change write. Since the DB is updated immediately, the next scan sees `last_event = 'home'` and takes path 6 — no re-fire.

---

## Autonomy: `presence_check()` in `autonomy.py`

A second APScheduler job running every 2 minutes, independent of the existing 10-minute `heartbeat()`.

```
scheduler.add_job(presence_check, 'interval', minutes=2)
```

`presence_check()` calls `home_arrival_trigger()` directly. If it fires:
- Calls `chat_with_retry()` with `PERSONA` system prompt to phrase the message
- Sends via `send_telegram_message()`
- Logs to `proactive_log` and calls `mark_proactive_attempted()`

This job runs **outside the quiet hours gate** — the whole point is catching late-night arrivals. The existing `heartbeat()` quiet hours (2am–9am) are unchanged for all other triggers.

**Scan cadence:** every 2 minutes → detection latency ≤ 2 minutes → away duration accuracy ±2 min.

---

## Timing Precision

| Event | Precision |
|---|---|
| Departure logged | Within 2 min of phone leaving |
| Arrival logged | Within 2 min of phone reconnecting |
| Away duration error | ±2 min (negligible for 25-min threshold) |

---

## Error Handling

- **`arp-scan` not installed:** `phone_is_home()` returns `None`, trigger skips silently. `autonomy.log` sees no errors.
- **Scan timeout (>15s):** Same — `None`, skip.
- **LLM phrasing fails:** `chat_with_retry` returns `ok=False` → `presence_check()` uses `IN_CHARACTER_FALLBACKS`.
- **DB write fails:** Wrapped in try/except in `db_helpers`, logged to `quality_log`.

---

## Files Changed

| File | Type | Change |
|---|---|---|
| `config.py` | Edit | Add `PHONE_MAC` |
| `network_radar.py` | New | `phone_is_home()` |
| `init_db.py` | Edit | Add `presence_log` table |
| `db_helpers.py` | Edit | 2 new helpers |
| `triggers.py` | Edit | `home_arrival_trigger()` + `ALL_TRIGGERS` entry |
| `autonomy.py` | Edit | `presence_check()` job, every 2 min |
