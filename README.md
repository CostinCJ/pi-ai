# Lache - Pi 5 AI Companion

A self-hosted, proactive AI companion that runs on a Raspberry Pi 5 and talks to you over Telegram. Lache holds a persistent memory, learns facts over time, is aware of context (music, weather, presence, schedule), and reaches out on its own instead of only answering when spoken to.

Built in Python with a test-driven workflow: 40+ test modules, a CI pipeline, and design specs for each major feature.

## What it does

- **Conversational chat** over Telegram, backed by Groq-hosted LLMs (Llama 3.3 70B for text, Llama 4 Scout for vision, Whisper for voice notes).
- **Persistent memory** in SQLite: durable user facts with time-decay, full conversation history, and rolling weekly profiles.
- **Proactive engagement**: an autonomy loop that starts conversations based on triggers (schedule, music, weather, presence), with quiet hours and engagement-aware back-off so it never becomes spammy.
- **Presence awareness**: a "network radar" detects whether you are home by scanning the LAN and Tailscale for known devices, and adapts its behavior when you are away.
- **Context integrations**: Spotify now-playing, OpenWeatherMap, Riot Games (League of Legends) match data, and Brave Search for live web lookups.
- **Personality system**: a consistent voice with reflection, memory consolidation, and daily briefings.

## Architecture

| Layer | Modules |
| --- | --- |
| Interface | `bot.py` (Telegram listener), `session_server.py` / `session_daemon.py` (cross-device session sync) |
| Reasoning | `brain.py`, `llm.py`, `tools.py`, `persona.py`, `reflection.py`, `consolidation.py` |
| Autonomy | `autonomy.py`, `triggers.py`, `schedule.py`, `briefing.py`, `outbox.py` |
| Memory | `db_helpers.py`, `init_db.py`, `llm_facts.py`, `regex_facts.py` |
| Sensors | `network_radar.py`, `spotify_sync.py`, `weather_sync.py`, `riot_client.py` |
| Ops | `*.service` (systemd units), `scripts/` (restic backups, server hardening, cron, alerts) |

## Running it

Secrets and device-specific values are read from a `.env` file (never committed). Copy the template and fill in your own values:

```bash
cp .env.example .env
# edit .env: add your Groq / Telegram / Spotify keys and device MACs
python init_db.py
python bot.py        # Telegram listener
python autonomy.py   # proactive loop
```

On the Pi, the four `systemd` units keep the listener, autonomy loop, session receiver, and status API running.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Notes

This is a personal project shared as a portfolio piece. It is designed for a single-user deployment on your own hardware. All credentials and personal configuration live in `.env`; the memory database is git-ignored and never leaves the device.
