# Agent Transformation Design
**Date:** 2026-04-29
**Project:** Pi AI — Lache

---

## Goal

Transform Lache from a reactive + trigger-based Telegram bot into a lightweight agent that can:
1. Call real tools (web search, reminders)
2. Perceive and reason about photos
3. Handle multi-step agentic conversations
4. Make smarter, context-aware proactive decisions

Approach: surgical additions to the existing architecture. Nothing currently working is rewritten. Failures degrade gracefully to the current behaviour.

---

## Section 1 — Architecture Overview

Five focused changes:

| File | Change |
|---|---|
| `tools.py` | New file — `web_search()` + `set_reminder()` |
| `llm.py` | Add `chat_with_tools()` — Groq function-calling wrapper |
| `brain.py` | Add `generate_agentic_reply()` — replaces `generate_reply()` as bot entry point |
| `bot.py` | Add `handle_photo()` handler; add `/remind` command |
| `triggers.py` | Remove `pattern_surface` + `open_thread` from `ALL_TRIGGERS`; add `free_reasoning_trigger()` |
| `autonomy.py` | Add reminder delivery job (every 1 min); wire `free_reasoning_trigger` |
| `db_helpers.py` | Add `add_reminder()`, `get_due_reminders()`, `mark_reminder_delivered()` |
| `init_db.py` | Add `reminders` table |
| `config.py` | Add `GROQ_VISION_MODEL`, `SEARCH_MAX_RESULTS` |
| `requirements.txt` | Add `duckduckgo-search` |

The existing `generate_reply()` stays in `brain.py` as the fallback. If function-calling fails, `generate_agentic_reply()` falls back to it transparently.

---

## Section 2 — Tool Layer (`tools.py`)

Two tools with a clean, testable interface:

### `web_search(query: str) -> str`
- Uses `duckduckgo-search` library (free, no API key required)
- Returns top `SEARCH_MAX_RESULTS` (default 3) results formatted as: `Title — Snippet\nURL`
- Timeout: 8 seconds
- On failure: returns a plain error string (never raises)

### `set_reminder(text: str, fire_at: str) -> str`
- `fire_at` is an ISO datetime string (the LLM resolves natural language time expressions before calling the tool)
- Writes to `reminders` table in SQLite
- Returns a confirmation string, e.g. `"reminder set for 22:00"`
- On failure: returns error string

### New DB table: `reminders`
```sql
CREATE TABLE IF NOT EXISTS reminders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    text        TEXT NOT NULL,
    fire_at     TEXT NOT NULL,
    delivered   INTEGER DEFAULT 0,
    created_at  TEXT DEFAULT (datetime('now'))
)
```

### DB helpers
- `add_reminder(text, fire_at)` — insert row
- `get_due_reminders()` — `WHERE delivered=0 AND fire_at <= datetime('now')`
- `mark_reminder_delivered(id)` — sets `delivered=1`

### Reminder delivery
New APScheduler job in `autonomy.py`, interval: 1 minute. Queries due reminders, sends each via `send_telegram_message()`, marks delivered. Capped at 10 per tick to prevent burst on restart.

---

## Section 3 — Agentic Reply Path (`brain.py` + `llm.py`)

### `llm.py` — `chat_with_tools(messages, tools, options, timeout)`
- Calls Groq API with `tools` parameter (OpenAI-compatible function-calling format)
- Returns one of:
  - `("text reply", None, None)` — LLM replied directly
  - `(None, "tool_name", {args_dict})` — LLM wants to call a tool
- Logs same as `chat()`. Never raises — returns error tuple on exception.

### `brain.py` — `generate_agentic_reply(user_message, image_data=None)`

Entry point for all messages from `bot.py`. Runs the following loop:

```
1. Build context line (facts, spotify, session, weather, schedule) — same as before
2. Build messages list (system prompt + history + user message)
   - If image_data present: user message includes base64 image content block
     directed at GROQ_VISION_MODEL
3. Call chat_with_tools() with [web_search, set_reminder] schemas
4. If text reply → validate with is_in_character(), return
5. If tool call:
     a. Execute tool (web_search or set_reminder from tools.py)
     b. Append tool result as a new message in the chain
     c. Call chat() once more for final reply (no tools on this second call)
6. Max 2 tool hops — hard cap, prevents infinite loops
7. Any exception or function-calling unavailability → fall back to generate_reply()
```

Multi-turn context is free: SQLite conversation history persists across turns, so Lache can ask a clarifying question in message N and use the answer in message N+1 without special state.

### Photo path
When `image_data` is provided, `generate_agentic_reply` uses `GROQ_VISION_MODEL` (`meta-llama/llama-4-scout-17b-16e-instruct`) for the first call. The system prompt instructs the model to:
1. Describe what it sees in Lache's casual voice
2. If the image contains something worth remembering (schedule, note, person, place), extract it as a structured fact

Extracted facts feed into the existing `llm_facts` pipeline — no new storage path needed.

---

## Section 4 — Photo Handling (`bot.py`)

### `handle_photo(update, context)`

Registered for `filters.PHOTO | filters.Document.IMAGE`.

```
1. bot.get_file(photo[-1].file_id) → download to bytes in memory
2. base64.b64encode(bytes) → image_data string
3. caption = update.message.caption or ""
4. brain.generate_agentic_reply(user_message=caption, image_data=image_data)
5. Log, reply, trigger llm_facts thread — same as handle_message
```

`photo[-1]` is the highest-resolution version Telegram provides.

### `/remind` command

`/remind <time> <text>` — explicit command that calls `set_reminder()` directly, bypassing the LLM. Belt-and-suspenders alongside the natural language path.

Expects `HH:MM` format for time (today, or tomorrow if the time has already passed today). Example: `/remind 22:00 call mom` → stores reminder for 22:00 tonight, confirms with "reminder set for 22:00".

---

## Section 5 — Smarter Proactive System

### `triggers.py` — updated `ALL_TRIGGERS`

`pattern_surface_trigger` and `open_thread_trigger` removed. Replaced by `free_reasoning_trigger` at the end:

```python
ALL_TRIGGERS = [
    ('class_soon',      has_class_soon_trigger),
    ('new_artist',      new_artist_trigger),
    ('session',         session_trigger),
    ('weather_flip',    weather_flip_trigger),
    ('late_night',      late_night_trigger),
    ('free_reasoning',  free_reasoning_trigger),
]
```

### `free_reasoning_trigger()`

Fires with `PATTERN_TRIGGER_PROBABILITY` (30%) — same gate as before. Dedup key: `free_reasoning_{YYYY-MM-DD}` — at most once per day.

Context fed to the LLM:
- Current time + vibe
- Last 7 days of `daily_signal` (mood, energy, topics)
- Last 3 entries from `pattern_log`
- Open threads (status=`open`, `last_referenced`)
- `rolling_summary`
- Last message Lache sent + timestamp

Two-step LLM flow (consistent with how other triggers work):
1. **Trigger LLM call** (inside `free_reasoning_trigger`): given the rich context, produce a short context string describing what to surface (e.g. `"user mentioned wanting to learn guitar 3 days ago, hasn't brought it up since"`) — or the literal word `SILENCE`. If `SILENCE`, the trigger returns `(False, "")` and nothing is sent.
2. **Phrasing LLM call** (inside `_handle_trigger_send`, unchanged): turns the context string into Lache's actual outgoing message in his voice.

This adds 1 LLM call when `free_reasoning_trigger` fires — at most once per day at 30% probability, negligible on the free tier.

This consolidates pattern surfacing and thread follow-up into a single context-aware judgment. Lache can still do both — it just chooses which and why.

---

## Section 6 — Config & Dependencies

### `config.py` additions
```python
GROQ_VISION_MODEL  = _opt("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
SEARCH_MAX_RESULTS = int(_opt("SEARCH_MAX_RESULTS", "3"))
```

### New pip dependency
Install into the project venv:
```bash
/home/pi/pi-ai/venv/bin/pip install duckduckgo-search
```
Also add to `requirements-dev.txt` so it's documented.

### `.env.example` additions
```
GROQ_VISION_MODEL=meta-llama/llama-4-scout-17b-16e-instruct
SEARCH_MAX_RESULTS=3
```

---

## Groq Free Tier Impact

| Scenario | Extra LLM calls vs today |
|---|---|
| Plain text message, no tool needed | 0 (same as today) |
| Message that triggers a tool | +1 (tool result → final reply) |
| Photo message | +1 (vision call replaces standard call) |
| Proactive heartbeat, free_reasoning fires | 0 extra (replaces existing LLM call) |

Worst case: a tool-using message costs 2 LLM calls. Well within Groq's 14,400 req/day free tier for personal use.

---

## Failure Modes & Degradation

| Failure | Behaviour |
|---|---|
| `chat_with_tools()` raises | Falls back to `generate_reply()` |
| Tool execution fails | Tool returns error string; LLM writes reply acknowledging it |
| Vision model unavailable | `handle_photo` replies with in-character fallback |
| `duckduckgo-search` times out | `web_search()` returns error string |
| Reminder job crashes | APScheduler logs error; retry on next tick |
