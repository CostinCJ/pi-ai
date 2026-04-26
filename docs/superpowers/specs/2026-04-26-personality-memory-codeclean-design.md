# Pi AI: Personality, Memory & Code Health Implementation Plan

**Date**: 2026-04-26  
**Scope**: Improve Lache's personality & proactive awareness, build real memory & self-model, fix code foundation  
**Target**: Completion with live testing over ~2–3 weeks  
**Constraints**: Pi 5 4GB RAM, 1.7B model, <15s reactive latency budget

---

## Constraints (Every Decision Anchors to These)

- **RAM**: 4GB total. Ollama + Qwen3-1.7B Q4_K_M ≈ 1.6–2GB resident with KV cache. Leave ≥1GB free for Python + SQLite.
- **CPU**: Pi 5, no GPU. Cold start 20–50s, warm 3–15s. **Every extra Ollama call is a real cost** — never call it where a deterministic function will do.
- **Model size**: 1.7B is shallow. It will hallucinate JSON, drift in long contexts, and parrot phrases. Design *around* it: short prompts, low temperature for structured tasks, validation on every output, no chained reasoning.
- **No regressions in latency.** Reactive replies must stay ≤15s warm.

---

## Phase 0 — Code Health Foundation (Do First, No Behavior Change)

Pure cleanup that unblocks everything else and removes footguns.

### 0.1 Fix the `/api/generate` vs `/api/chat` Split

**Problem**: `config.py` defines `OLLAMA_URL` as `/api/generate`, but `brain.py` rewrites it to `/api/chat`. `reflection.py` and `consolidation.py` still hit `/api/generate` directly.

**Action**:
- Add both URLs to `config.py`:
  ```python
  OLLAMA_BASE = 'http://localhost:11434'
  OLLAMA_CHAT_URL = f'{OLLAMA_BASE}/api/chat'
  OLLAMA_GENERATE_URL = f'{OLLAMA_BASE}/api/generate'
  ```
- Remove the `.replace()` hack in `brain.py`.
- Migrate `reflection.py` and `consolidation.py` to `/api/chat` too — same model, same prompts, consistent endpoint, they benefit from `/no_think`.

### 0.2 Centralize Ollama I/O in One Module

**New file**: `llm.py` — single source of truth for all Ollama calls.

**Functions**:
- `chat(messages, options, timeout=60) -> str` — wraps `/api/chat`, returns cleaned content.
- `chat_json(messages, options, schema_keys, timeout=60) -> dict | None` — wraps `chat`, parses JSON, validates required keys, returns `None` on failure (no exceptions leaking).
- `_clean(text)` — moved here, single source of truth.

**Features**:
- Add **one retry with backoff** (1 retry, 2s sleep) on connection errors only. Do not retry on timeout — compounds the wait.
- Add **structured logging** to `/home/pi/pi-ai/llm.log`: timestamp, function caller, latency_ms, prompt_tokens (est. by len/4), success/fail. Log rotation: truncate at 5MB.

### 0.3 Centralize Banned Phrases & Cleaning

- Move `BANNED_PHRASES` and `_clean()` out of `brain.py` into `llm.py`. Both proactive and reactive paths use it.
- Add single predicate: `is_acceptable(text) -> bool`. Reuse everywhere.

### 0.4 Remove Dead Code

- `db_helpers.get_recent_history()` is unused (replaced by `_messages` variant). Delete it.
- The seed profile string in `db_helpers.get_latest_profile()` is load-bearing — extract to `SEED_PROFILE` constant at top of file so it's obvious.

### 0.5 Add Basic Error Boundaries

- `bot.py::handle_message`: wrap `brain.generate_reply` in try/except. On failure, send `"brain hiccup, try again in a sec"` and log to `bot.log`.
- `autonomy.py::heartbeat`: add a single log line per fired tick — when, what it decided, latency. File: `/home/pi/pi-ai/autonomy.log`.

### 0.6 Ollama Keepalive

- Add `Environment=OLLAMA_KEEP_ALIVE=30m` to **the Ollama systemd unit** (not piai.service). Find with `systemctl cat ollama`. Kills cold starts during evening use.

**Phase 0 acceptance criteria**: Services restart cleanly, `/status` works, sending a message produces a logged reply within previous latency budget. No new features yet.

---

## Phase 1 — Personality & Proactive Intelligence

Goal: Lache feels sharper, less generic, texts at *meaningful* moments — not on a dumb 60-min cron.

### 1.1 Tighten the Persona

**New file**: `persona.py` — separates persona from logic.

**Contents**:
- Move `PERSONA` from `brain.py` to `persona.py`.
- Add **negative few-shot**: one example showing what NOT to say, with a `# bad` marker. Small models learn more from "don't do X".
- Add **time-of-day mode** helper: deterministic short phrase, not parsed by model.
  ```python
  def get_vibe():
      hour = datetime.now().hour
      if 0 <= hour < 7:
          return "late-night low-key"
      elif 7 <= hour < 11:
          return "morning slow-start"
      elif 11 <= hour < 16:
          return "midday neutral"
      else:
          return "evening casual"
  ```
- Inject into system prompt as one line: `Vibe: {get_vibe()}`.

### 1.2 Event-Driven Proactive Triggers (Replace 60-min Cron Heartbeat)

**Problem**: Current `heartbeat` runs every 60 min, wastes LLM calls on SILENCE.

**Solution**: Deterministic triggers + LLM only for phrasing.

**Architecture**:
- APScheduler job runs every **10 minutes**, stays cheap — checks signals deterministically.
- Calls LLM **only if a signal fires**.

**Signals** (each is pure function returning `(should_speak: bool, context: str)`):

1. **Class soon**: `has_class_soon(within=1h)` and not mentioned today → "yo, OS lab in an hour, room L001"
2. **Spotify track change to notable artist**: cache last artist in SQLite. If new artist not seen in 7 days → "first time hearing $ARTIST, what made you put it on?"
3. **Weather flip**: cache yesterday's weather. If today's temp differs by >8°C or precipitation type changed → mention it.
4. **Late-night idle**: 00:30–01:45, no message in 3h, last user activity today → casual check-in. (Respects 2am–9am quiet hours.)
5. **Pattern surface**: 30% chance per day, pick recent pattern from `pattern_log`, reference conversationally.
6. **Open thread follow-up**: ~3–5 days, pick thread last referenced >3 days ago ("yo, did you ever fix that amp?").

**LLM prompt** (single, tight):
```
Phrase this as 1 short Lache message: {fact}
```
Temperature 0.7, num_predict 60.

**Result**: <5 LLM calls per day for proactive (down from 24), each grounded in real event.

**Cooldown**: Stay at 90 min. Quiet hours stay 2am–9am.

### 1.3 Trigger-Tracking Table

New table `proactive_log`:
```sql
CREATE TABLE proactive_log (
    id INTEGER PRIMARY KEY,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    trigger_type TEXT,    -- 'class_soon', 'new_artist', etc.
    trigger_key TEXT,     -- dedup key, e.g. 'OS lab 2026-04-27'
    message_sent TEXT
);
```
Used to dedupe ("did I already mention this class today?") and analyze patterns.

### 1.4 Context Line Becomes Richer But Not Longer

**Changes**:
- Cap each section at 200 chars. If facts > 200, take **5 most recently updated** (add `ORDER BY last_updated DESC LIMIT 5`).
- Drop "Recent tracks: " prefix from Spotify, just give data.
- Stop including patterns in *every* reactive call. Include patterns **only in proactive** thinking and in messages where user input > 40 chars (signal of real conversation).

---

## Phase 2 — Memory & Self-Model

Goal: Lache actually remembers you across weeks. Better extraction, structured mood, conversation continuity, no model bloat.

### 2.1 Schema Additions

New tables:

```sql
-- Mood / day-shape signal (one row per day, written by consolidation)
CREATE TABLE daily_signal (
    date TEXT PRIMARY KEY,        -- 'YYYY-MM-DD'
    mood TEXT,                    -- 'low', 'neutral', 'up', 'wired', 'social' (closed vocab)
    energy INTEGER,               -- 1-5
    main_topics TEXT,             -- comma-separated, max 3
    summary TEXT,                 -- 2 sentences
    message_count INTEGER
);

-- Rolling summary (one row, replaced daily)
CREATE TABLE rolling_summary (
    id INTEGER PRIMARY KEY,
    generated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    summary TEXT                  -- ~300 chars, top line from last ~50 messages
);

-- Open threads (things to potentially follow up on)
CREATE TABLE open_threads (
    id INTEGER PRIMARY KEY,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    description TEXT,             -- "wants to learn fingerstyle guitar"
    status TEXT DEFAULT 'open',   -- 'open', 'closed', 'stale'
    last_referenced DATETIME
);

-- Track cached state
CREATE TABLE proactive_state (
    key TEXT PRIMARY KEY,
    value TEXT,                   -- JSON-encoded, e.g. last_artist, yesterday_weather
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

Extend existing `user_facts`:
```sql
ALTER TABLE user_facts ADD COLUMN source TEXT DEFAULT 'unknown';      -- 'realtime', 'consolidation', 'manual'
ALTER TABLE user_facts ADD COLUMN confidence REAL DEFAULT 1.0;
ALTER TABLE user_facts ADD COLUMN times_referenced INTEGER DEFAULT 0;
```

Add migrations to `init_db.py` idempotently (`CREATE TABLE IF NOT EXISTS`, wrap ALTER in try/except for existing columns).

### 2.2 Fact Extraction — Deterministic-First, LLM-Second

**New file**: `regex_facts.py` — tier-1 extractor, no LLM.

**Tier 1** (regex, no LLM):
```python
FACT_PATTERNS = [
    (r"\bi (bought|got|own|have|own)\s+(?:a |an |the )?([^.,!?]{3,40})", "owns"),
    (r"\bi (quit|stopped|started)\s+([^.,!?]{3,40})", "did"),
    (r"\bi'?m? (a|an)\s+([a-z]{3,30})\b(?!.*tired|bored|sick)", "is_a"),
    (r"\bi (love|hate|prefer)\s+([^.,!?]{3,40})", "prefers"),
]
```
Produces **candidate facts** with confidence 0.6.

**Tier 2** (LLM cleanup, batched daily in `consolidation.py`):
- Reads tier-1 candidates from last 24h.
- Single LLM call validates + refines wording.
- Promotes to confidence 0.95 or rejects.

**Net effect**: Realtime extraction becomes *zero* LLM calls. Consolidation's existing daily call does double duty.

**Action**: Drop the realtime background-thread Ollama call from `brain.py` entirely.

### 2.3 Mood Signal

Extend `consolidation.py` JSON schema:
```json
{
  "facts": {...},
  "summary": "...",
  "mood": "low|neutral|up|wired|social",
  "energy": 1-5,
  "main_topics": ["league", "guitar"]
}
```

Insert one row per day into `daily_signal`. No new LLM call — extends the existing one.

**In `brain.py`**: Inject last 3 days of mood as one line: `Recent: Sat=neutral, Fri=low, Thu=wired`. **Only in proactive context**, not reactive — keeps reactive prompts tight.

### 2.4 Conversation Continuity Beyond 8 Messages

Two-tier history:
- **Hot** (last 8 messages, full text) — already exists.
- **Warm** (rolling summary of last ~50 messages, ~300 chars). Updated by `consolidation.py` daily. Stored in `rolling_summary` table (one row).

**In system prompt**: Add one line for messages > 40 chars: `Earlier: {rolling_summary}`.

### 2.5 Open Threads

During `consolidation.py`, JSON output adds `open_threads` array: things the user expressed intent about ("wants to fix the guitar amp", "thinking about quitting league").

Stored in `open_threads` table.

**New proactive trigger** (Phase 1.2 #6): Every 3–5 days, pick a random thread last referenced >3 days ago, mention it. Marks `last_referenced`.

### 2.6 Reflection Upgrade

`reflection.py` (Sunday 3am):
- Migrate to `/api/chat`.
- Reads `daily_signal` rows from past 7 days as structured input alongside conversations.
- Output includes `closed_threads` array — patterns of finished topics. Marks matching `open_threads.status='closed'`.

---

## Phase 3 — New Small Features Riding on the Foundation

Cheap additions unlocked by Phases 0–2.

### 3.1 `/consolidate` Telegram Command

Manual trigger for `consolidation.py::extract_facts_and_summarize()`. Useful for testing.

### 3.2 `/forget <key>` Telegram Command

Removes fact from `user_facts` by key. Power-user maintenance.

### 3.3 `/threads` Telegram Command

Lists current `open_threads` with status. Sanity check on memory system.

---

## File Changes Summary

| File | Phase | Change |
|---|---|---|
| `config.py` | 0 | Add `OLLAMA_CHAT_URL` / `OLLAMA_GENERATE_URL` |
| `llm.py` | 0 | **NEW** — all Ollama I/O, `_clean`, banned phrases, JSON helper, retry, logging |
| `persona.py` | 1 | **NEW** — PERSONA + few-shots + vibe helper |
| `regex_facts.py` | 2 | **NEW** — tier-1 deterministic extractor |
| `triggers.py` | 1 | **NEW** — pure-function signal detectors (class_soon, new_artist, weather_flip, late_night, pattern_surface, open_thread) |
| `brain.py` | 0,1,2 | Use `llm.py`, use `persona.py`, slim context line, drop realtime Ollama fact call |
| `db_helpers.py` | 0,2 | Remove dead fn, new helpers for `daily_signal`, `open_threads`, `rolling_summary`, `proactive_state` |
| `init_db.py` | 0,2 | Idempotent migrations for new tables/columns |
| `autonomy.py` | 1 | New trigger-based heartbeat, 10-min poll, call trigger functions |
| `consolidation.py` | 0,2 | `/api/chat`, extended JSON schema (mood/energy/topics/threads), tier-2 fact validation |
| `reflection.py` | 0,2 | `/api/chat`, ingest daily_signal, output closed_threads |
| `bot.py` | 0,3 | Error boundary, `/consolidate`, `/forget`, `/threads` commands |
| `spotify_sync.py` | 1 | Add cached "last seen artist" tracking via SQLite (no new API calls) |
| `weather_sync.py` | 1 | Add `get_weather_change()` returning structured delta vs yesterday |

---

## Sequencing & Migration Strategy

1. **Phase 0 first, in one batch.** Land it, restart services, watch logs 24h. No behavior change expected.
2. **Phase 2 schema before Phase 1 triggers** — `open_threads` + `daily_signal` must exist before signals can read them.
3. **Phase 1 in slices**:
   - Ship event-driven heartbeat with signals 1–3 (deterministic, low risk).
   - Confirm it fires correctly via `proactive_log`.
   - Then add signals 4–6.
4. **Phase 3 last.** Trivial once rest is in.

Each slice is independently deployable. Restart with `systemctl restart piai piaibot` and tail logs.

---

## What This Plan Is NOT Doing (and Why)

- **No model upgrade to Qwen3-2B.** 1.7B Q4_K_M already uses ~1.8GB; 2B would push memory + slow tokens/sec. Revisit if quality still feels shallow after these changes.
- **No embedding-based memory / vector DB.** Adds 200–500MB RAM and another moving part. Structured tables + warm summary cover 90% of RAG's upside at this scale.
- **No new external data sources.** YAGNI until existing ones are well-used.
- **No async rewrite of bot.py.** python-telegram-bot is already async; bottleneck is Ollama, not the bot.
- **No comprehensive test suite.** Out of scope; verification via logs and live Telegram testing per slice.

---

## Success Criteria

- **Phase 0**: All services restart cleanly, no latency regression, all requests logged.
- **Phase 1**: Proactive triggers fire <5 times/day, Lache texts about real events (class, music, weather), not generic.
- **Phase 2**: Facts extracted daily with 0 realtime LLM calls. Daily mood/energy captured. Open threads tracked. Rolling history visible when needed.
- **Phase 3**: Commands work, user can inspect + maintain memory.
- **Overall**: Lache feels like a presence over 2+ weeks, remembers 3+ facts, surfaces patterns, proactive chatter grounded in real signals.
