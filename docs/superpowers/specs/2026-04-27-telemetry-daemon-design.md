# Telemetry Daemon Design
**Date:** 2026-04-27
**Status:** Approved

## Goal

Give Lache a full picture of the user's active session on the laptop — top 5 real applications by RAM — rather than just the currently focused window. Lache sees "League + Discord + Spotify are all running" and can use that in replies and proactive messages.

---

## Architecture

Two devices, five components:

```
[Windows laptop]
  session_daemon.py
    → psutil: all processes → strip SYSTEM_PROCESSES denylist → top 5 by RAM
    → POST JSON every 2 min → http://<tailscale-pi-ip>:8765/session
    → silent on failure (Pi asleep/unreachable — skip tick, log locally)

[Raspberry Pi]
  session_server.py        (new systemd service: piaisession.service)
    → stdlib http.server, binds to Tailscale IP only (never 0.0.0.0)
    → validates payload → writes to session_snapshot table in memory.db
    → trims table to last 50 rows on every insert

  db_helpers.py            (two new helpers)
    → log_session_snapshot(apps_json)
    → get_latest_session_snapshot() → None if latest row > 5 min old

  brain.py                 (modified)
    → _build_context_line() + _build_proactive_context() both inject
      snapshot if fresh; silently skip if stale or None

  triggers.py              (new session_trigger)
    → detects gaming session start → fires once per session via proactive_state
    → slots into ALL_TRIGGERS between new_artist and weather_flip
```

---

## Transport & Security

- Laptop POSTs to Pi via Tailscale mesh (`100.x.x.x:8765`)
- Works on LAN and remotely (uni, home) without any configuration change
- Pi binds exclusively to its Tailscale IP — port is invisible outside the tailnet
- No additional auth token needed — WireGuard/Tailscale handles device-level auth
- Laptop must have Tailscale installed and joined to the same tailnet as the Pi

---

## Data Format

Laptop POST payload:
```json
{
  "apps": [
    {"name": "League of Legends", "ram_mb": 823},
    {"name": "Discord",           "ram_mb": 347},
    {"name": "Spotify",           "ram_mb": 241},
    {"name": "chrome",            "ram_mb": 198},
    {"name": "Code",              "ram_mb": 156}
  ]
}
```

Names come from `psutil`'s live process list — nothing is hardcoded. The example above is illustrative only; actual content depends on what's running at each 2-minute tick.

Pi validates: `apps` key exists, is a non-empty list, each item has `name` (str) and `ram_mb` (int). Rejects malformed payloads with HTTP 400.

What Lache sees injected into context:
```
Session: League of Legends (823MB), Discord (347MB), Spotify (241MB), Chrome (198MB), Code (156MB)
```

---

## Filtering — Windows System Process Denylist

Applied on the laptop before ranking. Case-insensitive match against `proc.name().lower()`.

```python
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
```

`explorer.exe` excluded — it's the Windows shell, always running, not a user-opened app.

---

## Database

New table in `memory.db` (added to `init_db.py`):

```sql
CREATE TABLE IF NOT EXISTS session_snapshot (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    apps      TEXT NOT NULL
);
```

`apps` stores the raw JSON string of the apps list. Trimmed to last 50 rows on every insert.

---

## brain.py Integration

`get_latest_session_snapshot()` returns `None` if:
- No rows in the table
- Most recent row timestamp > 5 minutes ago (laptop off/asleep)

When not None, both `_build_context_line()` and `_build_proactive_context()` prepend:
```
Session: <name> (<ram>MB), ...
```
to the context parts list alongside facts, Spotify, and patterns.

---

## Trigger Design

New `session_trigger` in `triggers.py`:

1. Calls `get_latest_session_snapshot()` — returns `False, ""` if None
2. Checks app names for known game identifiers (case-insensitive substring match):
   ```python
   GAME_KEYWORDS = {'league', 'valorant', 'cs2', 'cyberpunk', 'fortnite', 'minecraft', 'overwatch'}
   ```
3. If a game is detected:
   - Builds dedup key: `gaming_session_{YYYY-MM-DD}`
   - Checks `was_proactive_attempted_today('session', key)` — skips if already fired today
   - Context string: `"user just started a gaming session, {game} is running alongside {other apps}"`
4. If no game detected → `return False, ""` — non-gaming session data is already visible to Lache passively via `brain.py` context injection, no proactive trigger needed
5. Slots into `ALL_TRIGGERS` at position 2 (after `new_artist`, before `weather_flip`)

---

## Pi Receiver — `session_server.py`

- `http.server.BaseHTTPRequestHandler` subclass, no Flask dependency
- Listens on `TAILSCALE_IP:8765` (new constant in `config.py`)
- Only handles `POST /session` — everything else returns 404
- Runs as `piaisession.service` (same pattern as `piai.service`, `piaibot.service`)
- Logs accepted/rejected payloads to `/home/pi/pi-ai/session_server.log`

---

## Laptop Daemon — `session_daemon.py`

- Dependencies: `psutil`, `requests` (both installable via pip)
- Loop: collect → filter → rank → POST → sleep 120s
- `ConnectionError` / `Timeout`: log to `session_daemon.log`, continue loop (never crash)
- Startup: Windows Task Scheduler, trigger = "At log on", action = `pythonw session_daemon.py`
- No visible window (`pythonw` instead of `python`)

---

## New `config.py` Constant

```python
TAILSCALE_IP = '100.x.x.x'  # Pi's Tailscale IP — run `tailscale ip` on Pi to find it
SESSION_SERVER_PORT = 8765
```

---

## New Systemd Service — `piaisession.service`

```ini
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
```

---

## Files Changed / Created

| File | Change |
|---|---|
| `session_daemon.py` | NEW — Windows laptop daemon |
| `session_server.py` | NEW — Pi HTTP receiver |
| `config.py` | Add `TAILSCALE_IP`, `SESSION_SERVER_PORT` |
| `init_db.py` | Add `session_snapshot` table |
| `db_helpers.py` | Add `log_session_snapshot()`, `get_latest_session_snapshot()` |
| `brain.py` | Inject snapshot into both context builders |
| `triggers.py` | Add `session_trigger`, add to `ALL_TRIGGERS` |
| `/etc/systemd/system/piaisession.service` | NEW systemd unit |

---

## What's Out of Scope

- Authentication beyond Tailscale network membership
- Historical session analytics (no UI or reporting)
- Per-app window title tracking
- Mobile device session tracking
