# Lache Utility Redesign — Design Spec

Date: 2026-07-18
Status: approved by user (sections 1–4 approved in conversation)

## Problem

Lache's proactive "presence" messaging failed: 336 proactive sends between April and July 2026 earned 15 replies (4.5%); the user stopped responding entirely after May 7. Root cause per user: **wrong direction** — small ambient observations ("still warm out huh") aren't wanted. The user wants Lache to be genuinely useful — briefings, reminders, alerts, good answers — with the personality as flavor on top, not as the product.

Prerequisite fixes (already shipped 2026-07-18, see master briefing): engagement-aware backoff, cross-day repeat suppression, semester calendar gating, consolidation monologue guard, reflection max_tokens fix, fact cleanup.

## Direction

Lache becomes **a utility with a voice**. Four jobs:

1. **Daily briefing** — one skimmable morning message, sent at first sign of activity.
2. **Smart reminders** — natural-language, recurring, snoozable.
3. **Watchers** — speak only when something real happens (new music, server problems, post-game, LoL patches).
4. **Reactive quality** — real answers, working search, Pi control from chat.

Architecture: **retrofit the existing engine** (autonomy.py APScheduler + bot.py + existing send pipeline with repeat-suppression and engagement gating), plus one borrowed idea: a lightweight outbox so non-urgent findings hold for the briefing instead of sending standalone.

## Section 1 — Delivery core + briefing

### Trigger cleanup
- `ALL_TRIGGERS` shrinks to `class_soon` + `post_game` (class_soon is real info — 1h heads-up before a class, semester-gated; the briefing covers the morning view, this covers the moment).
- **Delete** (code, not disable): `free_reasoning_trigger`, `pattern_surface_trigger`, `late_night_trigger`, `session_trigger`, `weather_flip_trigger`, `open_thread_trigger` (dead code — not in ALL_TRIGGERS since May), and their tests.
- `home_arrival_trigger` stays unchanged on the 2-min presence job (it had the best reply rate; "back at 4am again?" is the one flavor message that survives).
- Engagement gate (`engagement_level` / `proactive_allowed`) stays as a safety net **for trigger-class sends only** (home_arrival, post_game). The briefing, reminders, and urgent watcher alerts bypass it — they are requested utility, not ambient chatter, and must fire regardless of reply history.

### Outbox (`outbox.py`, ~80 lines)
- API: `outbox.send(text, urgency)` with `urgency ∈ {urgent, briefing}`.
- `urgent` → immediate Telegram send through the existing pipeline (repeat-suppression included).
- `briefing` → row in new `outbox_queue` table (id, created_at, text, consumed). Drained into the next briefing; consumed rows marked, rows older than 48h dropped.
- All senders (briefing job, watchers, reminders, home_arrival) route through it.

### Briefing job
- APScheduler job every 10 min, window 09:00–13:00.
- Activity signals (any → user is up): Spotify track played within last 20 min; laptop session snapshot fresh (<5 min); any user message today. Phone-on-wifi is explicitly NOT a signal (phone is online while user sleeps).
- First signal → send briefing; once per day (dedup key `briefing_YYYY-MM-DD`). No signal by 13:00 → send anyway.
- Content, in order, empty sections skipped:
  1. Weather now + today's arc (existing weather_sync)
  2. Today's classes — only when `SEMESTER_RANGES` active
  3. Reminders due today
  4. Queued `briefing`-urgency outbox items (new release, patch, etc.)
- Phrased by LLM in Lache's voice from structured data. Hard rule: **every line must trace to a supplied data field; nothing invented**. Explicit `num_predict` on the call.
- Degenerate case: nothing to say → one-line weather only. No padding, no "good morning" fluff, no engagement-fishing questions.

## Section 2 — Smart reminders

- Set via plain language in any message ("remind me thursday before lab to print the report", "every sunday at 8 remind me to call home"). Existing tool-calling loop; `set_reminder` tool schema extended: `fire_at` (ISO datetime), `recurrence` (`none|daily|weekly`), `text`.
- Parsing prompt receives current date/time **and the timetable**, so "before lab" resolves to a concrete time (lab 16:00 → fire 15:00).
- Anti-misparse rule: the confirmation reply always states the resolved time ("set: thu 15:00, print the report").
- DB migration: `reminders` gains `recurrence TEXT DEFAULT 'none'`.
- Delivery: existing 1-min `deliver_reminders` job → outbox `urgent`. Recurring reminders re-arm the next occurrence on delivery instead of being marked done.
- Snooze: user reply within ~10 min of a fired reminder ("snooze", "in an hour", "tomorrow") → new `snooze_reminder` tool re-arms the last-fired reminder. Track last-fired reminder id + timestamp in `proactive_state` or equivalent.
- Reminders due today also appear as a briefing line (preview; they still fire at their time).
- `/remind HH:MM` command stays as manual fallback.

## Section 3 — Watchers

New module `watchers.py`; each watcher is a function run on its own APScheduler cadence, pushing findings to the outbox. Shared `watcher_state` table (key, value, updated_at) for seen-state and cooldowns.

| Watcher | Cadence | Urgency | Logic |
|---|---|---|---|
| New music | daily, overnight | briefing | Top ~20 artists by listens from `spotify_tracks` (30-day window) → spotipy `artist_albums` latest release → new vs `watcher_state` → "X dropped: Y" |
| Server health | 10 min | urgent | disk >85%, temp >75°C, failed systemd units, unhealthy docker containers, **backup freshness**: newest `/home/pi/backups/pi-ai/memory-*.db.gz` older than 48h. 24h cooldown per condition via `watcher_state`. |
| Post-game | existing trigger | urgent | Unchanged code; dormant until `RIOT_API_KEY`/`RIOT_PUUID` set in `.env` (user action). |
| LoL patch | daily | briefing | `ddragon.leagueoflegends.com/api/versions.json` version bump (reliable) → "patch X is out" + link; best-effort 3-bullet summary from patch page, fail-soft to link only. |

Server-health messages are phrased in Lache's voice and replace `tg_alert.sh` for runtime monitoring; the bash traps inside backup scripts stay as last-resort (if Python is broken, bash still speaks).

## Section 4 — Reactive upgrade

- `is_in_character(text, mode)`: `proactive` keeps current limits (~220 chars, one sentence); `reactive` allows ~1200 chars, multiple sentences, lists. Voice rules (lowercase, direct, banned phrases, no wellness-speak) apply in both modes.
- Search: `tools.web_search()` becomes a provider interface. Primary: **Brave Search API** (`BRAVE_API_KEY` in `.env`, free tier — user grabs key). Fallback: current ddgs when no key or on error.
- Pi control: new `pi_control` tool. **Hard enum whitelist** — LLM selects an action name, never composes shell:
  - `status` (uptime, temp, disk, mem, service states), `disk`, `services`, `docker`, `backup_now`, `restart:{piai|piaibot|piaisession|lache-status}`
  - Each action maps to a fixed command string in code. Restarts require 4 specific NOPASSWD sudoers lines (the only root setup step in this design).
  - Every invocation logged. Chat-id whitelist already enforced by bot.py.

## Cross-cutting rules

- Every `chat_json`/LLM call passes explicit `num_predict` (regression from the reflection outage; enforce with a test that greps call sites).
- Briefing and watchers fail soft: a broken section/watcher is skipped and logged, never blocks the message or the loop.
- All new sends go through repeat-suppression.
- Tests per phase in the existing pytest harness: briefing assembly + activity-signal logic, reminder parse round-trip + recurrence re-arm + snooze, watcher state/dedup/cooldown, `pi_control` whitelist enforcement (unknown action rejected), `is_in_character` mode split.

## Build order (each phase independently shippable)

1. **Cleanup + briefing** — delete dead triggers, outbox, briefing job.
2. **Smart reminders** — schema, tools, snooze.
3. **Watchers** — music, server health first; patch notes after; post-game awaits Riot key.
4. **Reactive** — mode split, Brave search, pi_control.

## User-side prerequisites (not blockers, phases degrade gracefully)

- Riot API key (`RIOT_API_KEY`, `RIOT_PUUID`) → activates post-game + in-game suppression.
- Brave Search API key (`BRAVE_API_KEY`) → activates good search; ddgs fallback until then.
- 4 sudoers NOPASSWD lines → activates `restart` actions in pi_control.

## Out of scope

- Todo lists / task management (rejected — smart reminders only).
- BLE / SSID presence (Pi-side sensing can't track the user; documented dead end).
- MiniMax music generation (separate future project).
- Any re-expansion of ambient proactive messaging.
