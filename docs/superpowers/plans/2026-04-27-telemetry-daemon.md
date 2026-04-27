# Telemetry Daemon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Windows laptop daemon that POSTs the top 5 real apps by RAM every 2 minutes to a Pi HTTP receiver, so Lache sees a full session snapshot in every reply and can fire a proactive gaming trigger.

**Architecture:** Laptop `session_daemon.py` filters system noise via denylist, ranks by RAM, POSTs JSON to `session_server.py` on the Pi (bound to Tailscale IP only). Pi stores snapshots in a new `session_snapshot` SQLite table; `brain.py` injects the latest (if <5 min fresh) into both context builders; `session_trigger` fires once per day when a game is detected.

**Tech Stack:** Python stdlib `http.server` (Pi receiver), `psutil` + `requests` (laptop daemon), SQLite (storage), APScheduler already in use (no changes needed), Tailscale (transport/auth).

---

## File Map

| File | Action |
|---|---|
| `config.py` | Add `TAILSCALE_IP`, `SESSION_SERVER_PORT` |
| `init_db.py` | Add `session_snapshot` table (table 12) |
| `db_helpers.py` | Add `log_session_snapshot()`, `get_latest_session_snapshot()` |
| `brain.py` | Add `_format_session()`, inject into both context builders |
| `triggers.py` | Add `session_trigger()`, add to `ALL_TRIGGERS` at index 2 |
| `session_server.py` | NEW — Pi HTTP receiver |
| `session_daemon.py` | NEW — Windows laptop daemon |
| `tests/test_session.py` | NEW — all tests for this feature |
| `/etc/systemd/system/piaisession.service` | NEW — systemd unit |

---

## Task 1: Add config constants

**Files:**
- Modify: `config.py`

- [ ] **Step 1: Add constants to config.py**

Open `config.py` and append after the `PHONE_MAC` line:

```python
TAILSCALE_IP = '100.x.x.x'        # replace with: tailscale ip -4
SESSION_SERVER_PORT = 8765
```

- [ ] **Step 2: Find Pi's actual Tailscale IP and fill it in**

```bash
tailscale ip -4
```

Replace `100.x.x.x` in `config.py` with the output (e.g. `100.64.1.23`).

- [ ] **Step 3: Commit**

```bash
cd /home/pi/pi-ai && git add config.py && git commit -m "feat: add TAILSCALE_IP and SESSION_SERVER_PORT to config"
```

---

## Task 2: Add session_snapshot table to init_db.py

**Files:**
- Modify: `init_db.py`
- Test: `tests/test_session.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_session.py`:

```python
import sqlite3
import json
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Table existence
# ---------------------------------------------------------------------------

def test_session_snapshot_table_exists(fake_db):
    with __import__('db_helpers').get_conn() as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
    assert 'session_snapshot' in tables
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/test_session.py::test_session_snapshot_table_exists -v
```

Expected: `FAILED` — `AssertionError: assert 'session_snapshot' in {...}`

- [ ] **Step 3: Add the table to init_db.py**

In `init_db.py`, after the `presence_log` block (after line 117, before the column migrations), add:

```python
    # 12. Session Snapshot: top 5 laptop apps by RAM from telemetry daemon
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS session_snapshot (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            apps      TEXT NOT NULL
        )
    """)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/test_session.py::test_session_snapshot_table_exists -v
```

Expected: `PASSED`

- [ ] **Step 5: Migrate the live database**

```bash
cd /home/pi/pi-ai && venv/bin/python init_db.py
```

Expected output: `Brain initialized. Memory structure created at: /home/pi/pi-ai/memory.db`

- [ ] **Step 6: Commit**

```bash
git add init_db.py tests/test_session.py && git commit -m "feat: add session_snapshot table to init_db"
```

---

## Task 3: Add db_helpers functions

**Files:**
- Modify: `db_helpers.py`
- Test: `tests/test_session.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_session.py`:

```python
# ---------------------------------------------------------------------------
# db_helpers — log_session_snapshot / get_latest_session_snapshot
# ---------------------------------------------------------------------------

import db_helpers


SAMPLE_APPS = [
    {"name": "League of Legends", "ram_mb": 823},
    {"name": "Discord",           "ram_mb": 347},
    {"name": "Spotify",           "ram_mb": 241},
]


def test_get_latest_session_snapshot_returns_none_when_empty(fake_db):
    assert db_helpers.get_latest_session_snapshot() is None


def test_log_and_get_session_snapshot(fake_db):
    db_helpers.log_session_snapshot(SAMPLE_APPS)
    result = db_helpers.get_latest_session_snapshot()
    assert result is not None
    assert result[0]["name"] == "League of Legends"
    assert result[0]["ram_mb"] == 823
    assert len(result) == 3


def test_get_latest_session_snapshot_returns_none_when_stale(fake_db):
    stale_ts = (datetime.now() - timedelta(minutes=6)).strftime("%Y-%m-%d %H:%M:%S")
    with db_helpers.get_conn() as conn:
        conn.execute(
            "INSERT INTO session_snapshot (timestamp, apps) VALUES (?, ?)",
            (stale_ts, json.dumps(SAMPLE_APPS))
        )
    assert db_helpers.get_latest_session_snapshot() is None


def test_log_session_snapshot_trims_to_50_rows(fake_db):
    for i in range(55):
        db_helpers.log_session_snapshot([{"name": f"App{i}", "ram_mb": i}])
    with db_helpers.get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM session_snapshot").fetchone()[0]
    assert count == 50
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/test_session.py -k "snapshot" -v
```

Expected: 4 failures — `AttributeError: module 'db_helpers' has no attribute 'log_session_snapshot'`

- [ ] **Step 3: Implement the two functions in db_helpers.py**

Append to the bottom of `db_helpers.py`:

```python
def log_session_snapshot(apps):
    import json as _json
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO session_snapshot (apps) VALUES (?)",
            (_json.dumps(apps),)
        )
        conn.execute(
            "DELETE FROM session_snapshot WHERE id NOT IN "
            "(SELECT id FROM session_snapshot ORDER BY id DESC LIMIT 50)"
        )


def get_latest_session_snapshot():
    import json as _json
    from datetime import datetime as _dt, timedelta as _td
    with get_conn() as conn:
        row = conn.execute(
            "SELECT apps, timestamp FROM session_snapshot ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if not row:
        return None
    ts = _dt.strptime(row[1], "%Y-%m-%d %H:%M:%S")
    if (_dt.now() - ts).total_seconds() > 300:
        return None
    return _json.loads(row[0])
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/test_session.py -k "snapshot" -v
```

Expected: 4 passed (plus the table test = 5 total).

- [ ] **Step 5: Commit**

```bash
git add db_helpers.py tests/test_session.py && git commit -m "feat: add log_session_snapshot and get_latest_session_snapshot to db_helpers"
```

---

## Task 4: Add session_trigger to triggers.py

**Files:**
- Modify: `triggers.py`
- Test: `tests/test_session.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_session.py`:

```python
# ---------------------------------------------------------------------------
# session_trigger
# ---------------------------------------------------------------------------

from triggers import session_trigger


def test_session_trigger_no_fire_when_no_snapshot(fake_db):
    with patch("triggers.db_helpers.get_latest_session_snapshot", return_value=None):
        fired, ctx = session_trigger()
    assert fired is False
    assert ctx == ""


def test_session_trigger_no_fire_when_no_game(fake_db):
    apps = [
        {"name": "Discord",  "ram_mb": 347},
        {"name": "Spotify",  "ram_mb": 241},
        {"name": "chrome",   "ram_mb": 198},
    ]
    with patch("triggers.db_helpers.get_latest_session_snapshot", return_value=apps):
        fired, ctx = session_trigger()
    assert fired is False


def test_session_trigger_fires_when_league_detected(fake_db):
    apps = [
        {"name": "League of Legends", "ram_mb": 823},
        {"name": "Discord",           "ram_mb": 347},
    ]
    with patch("triggers.db_helpers.get_latest_session_snapshot", return_value=apps), \
         patch("triggers.db_helpers.was_proactive_attempted_today", return_value=False):
        fired, ctx = session_trigger()
    assert fired is True
    assert "league" in ctx.lower() or "League" in ctx
    assert "Discord" in ctx


def test_session_trigger_no_refire_same_day(fake_db):
    apps = [{"name": "League of Legends", "ram_mb": 823}]
    with patch("triggers.db_helpers.get_latest_session_snapshot", return_value=apps), \
         patch("triggers.db_helpers.was_proactive_attempted_today", return_value=True):
        fired, ctx = session_trigger()
    assert fired is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/test_session.py -k "session_trigger" -v
```

Expected: 4 failures — `ImportError: cannot import name 'session_trigger' from 'triggers'`

- [ ] **Step 3: Implement session_trigger in triggers.py**

In `triggers.py`, after the `open_thread_trigger` function and before `home_arrival_trigger`, add:

```python
GAME_KEYWORDS = {'league', 'valorant', 'cs2', 'cyberpunk', 'fortnite', 'minecraft', 'overwatch'}


def session_trigger():
    snapshot = db_helpers.get_latest_session_snapshot()
    if not snapshot:
        return False, ""

    game = next(
        (app["name"] for app in snapshot
         if any(kw in app["name"].lower() for kw in GAME_KEYWORDS)),
        None
    )
    if not game:
        return False, ""

    trigger_key = f"gaming_session_{datetime.now().strftime('%Y-%m-%d')}"
    if db_helpers.was_proactive_attempted_today('session', trigger_key):
        return False, ""

    others = [app["name"] for app in snapshot if app["name"] != game]
    others_str = ", ".join(others[:3]) if others else "nothing else notable"
    return True, f"user just started a gaming session, {game} is running alongside {others_str}"
```

- [ ] **Step 4: Add session_trigger to ALL_TRIGGERS at position 2**

Replace the `ALL_TRIGGERS` list at the bottom of `triggers.py`:

```python
ALL_TRIGGERS = [
    ('class_soon',     has_class_soon_trigger),
    ('new_artist',     new_artist_trigger),
    ('session',        session_trigger),
    ('weather_flip',   weather_flip_trigger),
    ('late_night',     late_night_trigger),
    ('pattern_surface', pattern_surface_trigger),
    ('open_thread',    open_thread_trigger),
]
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/test_session.py -k "session_trigger" -v
```

Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add triggers.py tests/test_session.py && git commit -m "feat: add session_trigger to triggers.py"
```

---

## Task 5: Inject session snapshot into brain.py

**Files:**
- Modify: `brain.py`
- Test: `tests/test_session.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_session.py`:

```python
# ---------------------------------------------------------------------------
# brain.py — session snapshot injection
# ---------------------------------------------------------------------------

import brain


BRAIN_APPS = [
    {"name": "League of Legends", "ram_mb": 823},
    {"name": "Discord",           "ram_mb": 347},
    {"name": "chrome",            "ram_mb": 198},
]


def test_build_context_includes_session_when_fresh(fake_db):
    with patch("brain.db_helpers.get_latest_session_snapshot", return_value=BRAIN_APPS), \
         patch("brain.db_helpers.get_user_facts", return_value="(no specific facts stored yet)"), \
         patch("brain.spotify_sync.get_recent_tracks", return_value="unavailable"), \
         patch("brain.db_helpers.get_recent_patterns", return_value="(no new patterns observed)"):
        ctx = brain._build_context_line("hey")
    assert "Session:" in ctx
    assert "League of Legends" in ctx
    assert "823MB" in ctx


def test_build_context_skips_session_when_none(fake_db):
    with patch("brain.db_helpers.get_latest_session_snapshot", return_value=None), \
         patch("brain.db_helpers.get_user_facts", return_value="(no specific facts stored yet)"), \
         patch("brain.spotify_sync.get_recent_tracks", return_value="unavailable"), \
         patch("brain.db_helpers.get_recent_patterns", return_value="(no new patterns observed)"):
        ctx = brain._build_context_line("hey")
    assert "Session:" not in ctx


def test_build_proactive_context_includes_session_when_fresh(fake_db):
    with patch("brain.db_helpers.get_latest_session_snapshot", return_value=BRAIN_APPS), \
         patch("brain.db_helpers.get_user_facts", return_value="(no specific facts stored yet)"), \
         patch("brain.spotify_sync.get_recent_tracks", return_value="unavailable"), \
         patch("brain.db_helpers.get_recent_patterns", return_value="(no new patterns observed)"):
        ctx = brain._build_proactive_context()
    assert "Session:" in ctx
    assert "Discord" in ctx
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/test_session.py -k "build_context" -v
```

Expected: 3 failures — `AssertionError: assert 'Session:' in ''`

- [ ] **Step 3: Add _format_session helper and inject into both context builders in brain.py**

In `brain.py`, add `_format_session` after the import block (after line 11):

```python
def _format_session(snapshot):
    if not snapshot:
        return None
    parts = [f"{app['name']} ({app['ram_mb']}MB)" for app in snapshot]
    return "Session: " + ", ".join(parts)
```

In `_build_context_line`, append after the Spotify block (after `parts.append(clean_spotify[:200])`):

```python
    session = _format_session(db_helpers.get_latest_session_snapshot())
    if session:
        parts.append(session)
```

In `_build_proactive_context`, append after the Spotify block (after `parts.append(clean_spotify[:200])`):

```python
    session = _format_session(db_helpers.get_latest_session_snapshot())
    if session:
        parts.append(session)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/test_session.py -k "build_context" -v
```

Expected: 3 passed.

- [ ] **Step 5: Run the full test suite to check for regressions**

```bash
cd /home/pi/pi-ai && venv/bin/pytest -v
```

Expected: all previously passing tests still pass, 3 new tests pass.

- [ ] **Step 6: Commit**

```bash
git add brain.py tests/test_session.py && git commit -m "feat: inject session snapshot into brain context builders"
```

---

## Task 6: Write session_server.py (Pi HTTP receiver)

**Files:**
- Create: `session_server.py`
- Test: `tests/test_session.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_session.py`:

```python
# ---------------------------------------------------------------------------
# session_server — _validate
# ---------------------------------------------------------------------------

import importlib, sys

def _get_validate():
    import session_server
    return session_server._validate

def test_validate_accepts_valid_payload():
    _validate = _get_validate()
    payload = {"apps": [{"name": "Discord", "ram_mb": 347}]}
    assert _validate(payload) is True


def test_validate_rejects_missing_apps_key():
    _validate = _get_validate()
    assert _validate({"data": []}) is False


def test_validate_rejects_empty_apps_list():
    _validate = _get_validate()
    assert _validate({"apps": []}) is False


def test_validate_rejects_missing_name():
    _validate = _get_validate()
    assert _validate({"apps": [{"ram_mb": 100}]}) is False


def test_validate_rejects_non_int_ram():
    _validate = _get_validate()
    assert _validate({"apps": [{"name": "Discord", "ram_mb": "347"}]}) is False


def test_validate_rejects_non_list_apps():
    _validate = _get_validate()
    assert _validate({"apps": "Discord"}) is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/test_session.py -k "validate" -v
```

Expected: 6 failures — `ModuleNotFoundError: No module named 'session_server'`

- [ ] **Step 3: Create session_server.py**

Create `/home/pi/pi-ai/session_server.py`:

```python
import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
import db_helpers
from config import TAILSCALE_IP, SESSION_SERVER_PORT

logging.basicConfig(
    filename='/home/pi/pi-ai/session_server.log',
    level=logging.INFO,
    format='%(asctime)s %(message)s'
)


def _validate(payload):
    if not isinstance(payload, dict):
        return False
    apps = payload.get('apps')
    if not isinstance(apps, list) or len(apps) == 0:
        return False
    for app in apps:
        if not isinstance(app.get('name'), str):
            return False
        if not isinstance(app.get('ram_mb'), int):
            return False
    return True


class SessionHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != '/session':
            self.send_response(404)
            self.end_headers()
            return
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            payload = json.loads(body)
        except Exception as e:
            logging.warning(f"parse error: {e}")
            self.send_response(400)
            self.end_headers()
            return

        if not _validate(payload):
            logging.warning(f"invalid payload: {str(payload)[:200]}")
            self.send_response(400)
            self.end_headers()
            return

        db_helpers.log_session_snapshot(payload['apps'])
        logging.info(f"accepted: {len(payload['apps'])} apps")
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        pass


if __name__ == '__main__':
    server = HTTPServer((TAILSCALE_IP, SESSION_SERVER_PORT), SessionHandler)
    logging.info(f"listening on {TAILSCALE_IP}:{SESSION_SERVER_PORT}")
    server.serve_forever()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/test_session.py -k "validate" -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add session_server.py tests/test_session.py && git commit -m "feat: add session_server.py Pi HTTP receiver"
```

---

## Task 7: Write session_daemon.py (Windows laptop daemon)

**Files:**
- Create: `session_daemon.py`
- Test: `tests/test_session.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_session.py`:

```python
# ---------------------------------------------------------------------------
# session_daemon — get_top_apps (filtering + ranking logic)
# ---------------------------------------------------------------------------

from unittest.mock import MagicMock
import session_daemon


def _make_proc(name, rss_bytes):
    p = MagicMock()
    p.info = {
        'name': name,
        'memory_info': MagicMock(rss=rss_bytes),
    }
    return p


def test_get_top_apps_strips_system_processes():
    procs = [
        _make_proc('svchost.exe',        500 * 1024 * 1024),
        _make_proc('Discord.exe',        347 * 1024 * 1024),
        _make_proc('msmpeng.exe',        400 * 1024 * 1024),
        _make_proc('LeagueClient.exe',   823 * 1024 * 1024),
    ]
    with patch('session_daemon.psutil.process_iter', return_value=procs):
        result = session_daemon.get_top_apps()
    names = [a['name'] for a in result]
    assert 'svchost' not in names
    assert 'msmpeng' not in names
    assert 'LeagueClient' in names
    assert 'Discord' in names


def test_get_top_apps_returns_max_5():
    procs = [_make_proc(f'App{i}.exe', (600 - i) * 1024 * 1024) for i in range(10)]
    with patch('session_daemon.psutil.process_iter', return_value=procs):
        result = session_daemon.get_top_apps()
    assert len(result) <= 5


def test_get_top_apps_sorted_by_ram_descending():
    procs = [
        _make_proc('Discord.exe',  200 * 1024 * 1024),
        _make_proc('Spotify.exe',  500 * 1024 * 1024),
        _make_proc('chrome.exe',   350 * 1024 * 1024),
    ]
    with patch('session_daemon.psutil.process_iter', return_value=procs):
        result = session_daemon.get_top_apps()
    assert result[0]['name'] == 'Spotify'
    assert result[0]['ram_mb'] == 500


def test_get_top_apps_strips_exe_extension():
    procs = [_make_proc('Discord.exe', 347 * 1024 * 1024)]
    with patch('session_daemon.psutil.process_iter', return_value=procs):
        result = session_daemon.get_top_apps()
    assert result[0]['name'] == 'Discord'
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/test_session.py -k "get_top_apps" -v
```

Expected: 4 failures — `ModuleNotFoundError: No module named 'session_daemon'` (or `No module named 'psutil'` — either is correct at this stage)

- [ ] **Step 3: Install psutil in the Pi venv (needed for import in tests)**

```bash
cd /home/pi/pi-ai && venv/bin/pip install psutil
```

- [ ] **Step 4: Create session_daemon.py**

Create `/home/pi/pi-ai/session_daemon.py`:

```python
import json
import logging
import time
import psutil
import requests

SESSION_SERVER_URL = 'http://100.x.x.x:8765/session'  # replace 100.x.x.x with Pi's Tailscale IP

SYSTEM_PROCESSES = {
    'system', 'registry', 'smss.exe', 'csrss.exe', 'wininit.exe',
    'services.exe', 'lsass.exe', 'lsaiso.exe', 'svchost.exe', 'dwm.exe',
    'winlogon.exe', 'fontdrvhost.exe', 'audiodg.exe', 'spoolsv.exe',
    'taskhostw.exe', 'runtimebroker.exe', 'searchindexer.exe',
    'searchhost.exe', 'startmenuexperiencehost.exe', 'shellexperiencehost.exe',
    'sihost.exe', 'ctfmon.exe', 'conhost.exe', 'dllhost.exe',
    'msmpeng.exe', 'nissrv.exe', 'securityhealthservice.exe',
    'wmiprvse.exe', 'textinputhost.exe', 'applicationframehost.exe',
    'backgroundtaskhost.exe', 'memory compression', 'sppsvc.exe',
    'dashost.exe', 'wudfhost.exe', 'widgetservice.exe', 'widgets.exe',
    'explorer.exe',
}

logging.basicConfig(
    filename='session_daemon.log',
    level=logging.INFO,
    format='%(asctime)s %(message)s'
)


def get_top_apps():
    procs = []
    for proc in psutil.process_iter(['name', 'memory_info']):
        try:
            name = proc.info['name'] or ''
            if name.lower() in SYSTEM_PROCESSES:
                continue
            ram_mb = proc.info['memory_info'].rss // (1024 * 1024)
            if ram_mb < 1:
                continue
            clean_name = name.replace('.exe', '').replace('.EXE', '').strip()
            procs.append({'name': clean_name, 'ram_mb': ram_mb})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    procs.sort(key=lambda x: x['ram_mb'], reverse=True)
    return procs[:5]


def main():
    logging.info("session daemon started")
    while True:
        try:
            apps = get_top_apps()
            requests.post(SESSION_SERVER_URL, json={'apps': apps}, timeout=10)
            logging.info(f"sent: {[a['name'] for a in apps]}")
        except (requests.ConnectionError, requests.Timeout) as e:
            logging.warning(f"send failed: {e}")
        except Exception as e:
            logging.error(f"unexpected error: {e}")
        time.sleep(120)


if __name__ == '__main__':
    main()
```

- [ ] **Step 5: Update SESSION_SERVER_URL with the real Tailscale IP**

Replace `100.x.x.x` in `session_daemon.py` with the same IP used in `config.py` (from Task 1 Step 2).

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/test_session.py -k "get_top_apps" -v
```

Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
git add session_daemon.py tests/test_session.py && git commit -m "feat: add session_daemon.py Windows laptop daemon"
```

---

## Task 8: Run full test suite

**Files:** none

- [ ] **Step 1: Run all tests**

```bash
cd /home/pi/pi-ai && venv/bin/pytest -v
```

Expected: all pre-existing tests pass + all new tests in `test_session.py` pass. Count should be 28 (existing) + 23 (new) = 51 total.

- [ ] **Step 2: Fix any failures before continuing**

If any pre-existing test fails, diagnose and fix before proceeding. Do not move to Task 9 with a red test suite.

---

## Task 9: Deploy systemd service and wire up laptop

**Files:**
- Create: `/etc/systemd/system/piaisession.service`

- [ ] **Step 1: Create the systemd service file**

```bash
sudo tee /etc/systemd/system/piaisession.service > /dev/null << 'EOF'
[Unit]
Description=Pi AI Session Snapshot Receiver
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/pi-ai
ExecStart=/home/pi/pi-ai/venv/bin/python /home/pi/pi-ai/session_server.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
```

- [ ] **Step 2: Enable and start the service**

```bash
sudo systemctl daemon-reload && sudo systemctl enable piaisession && sudo systemctl start piaisession
```

- [ ] **Step 3: Verify the service is running**

```bash
sudo systemctl status piaisession
```

Expected: `Active: active (running)`

- [ ] **Step 4: Smoke-test the endpoint from the Pi itself**

```bash
curl -s -X POST http://$(tailscale ip -4):8765/session \
  -H "Content-Type: application/json" \
  -d '{"apps":[{"name":"TestApp","ram_mb":200}]}' \
  -o /dev/null -w "%{http_code}"
```

Expected: `200`

- [ ] **Step 5: Verify the row landed in the database**

```bash
cd /home/pi/pi-ai && venv/bin/python -c "
import db_helpers
print(db_helpers.get_latest_session_snapshot())
"
```

Expected: `[{'name': 'TestApp', 'ram_mb': 200}]`

- [ ] **Step 6: Set up session_daemon.py on Windows laptop**

On the Windows laptop:
1. Install dependencies: `pip install psutil requests`
2. Copy `session_daemon.py` to a permanent folder (e.g. `C:\Users\<you>\pi-ai\session_daemon.py`)
3. Verify `SESSION_SERVER_URL` has the correct Pi Tailscale IP
4. Open Task Scheduler → Create Basic Task → Trigger: "When I log on" → Action: `pythonw C:\Users\<you>\pi-ai\session_daemon.py`
5. Run the task manually once to confirm it connects

- [ ] **Step 7: Verify end-to-end from laptop**

On the laptop, run manually:

```
python session_daemon.py
```

Check `session_daemon.log` — should show `sent: ['LeagueClient', 'Discord', ...]` (or whatever is running).

On the Pi, check:

```bash
cd /home/pi/pi-ai && venv/bin/python -c "
import db_helpers
snap = db_helpers.get_latest_session_snapshot()
print(snap)
"
```

Expected: a real list of your running apps.

- [ ] **Step 8: Commit**

```bash
cd /home/pi/pi-ai && git add session_server.py && git commit -m "deploy: piaisession systemd service live"
```

---

## Task 10: Restart live services and verify Lache sees session data

- [ ] **Step 1: Restart piai service so it picks up the triggers.py change**

```bash
sudo systemctl restart piai
```

- [ ] **Step 2: Restart piaibot service so it picks up brain.py change**

```bash
sudo systemctl restart piaibot
```

- [ ] **Step 3: Verify all three services are running**

```bash
sudo systemctl status piai piaibot piaisession
```

Expected: all three show `Active: active (running)`

- [ ] **Step 4: Send a test message via Telegram and verify session appears in context**

Send any message to Lache via Telegram. Then check `bot.log` to confirm the reply was generated (Lache should be able to reference what you're running if asked).

- [ ] **Step 5: Tail session_server.log to confirm ongoing pushes land**

```bash
tail -f /home/pi/pi-ai/session_server.log
```

Expected: a new `accepted: 5 apps` line every 2 minutes while laptop daemon is running.
