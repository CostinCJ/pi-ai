# Fix Conversational Failures Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the three confirmed user-facing failure modes — empty replies that drop on the floor, sycophantic/poetic persona drift on proactive messages, and a runaway proactive trigger that has been firing every 10 minutes since 16:51 today — and add the guardrails (retry, validation, structural style filter, dedup-by-attempt) needed to keep them from regressing.

**Architecture:** Wrap every Ollama call site (reactive `brain.generate_reply` + proactive `autonomy.heartbeat`) in the same three-layer pipeline: (1) generate with full persona context, (2) validate output (non-empty, in-character, length-bounded), (3) retry once with a corrective prompt, then (4) fall back to a hand-written in-character pool — never to empty, never to "...". Replace the proactive_log-based trigger dedup with a proactive_state attempt counter so SILENCE responses still cool the trigger down. Add a `quality_log` table so future drift is visible, not invisible.

**Tech Stack:** Python 3, SQLite, Ollama (Qwen3-1.7B Q4_K_M), python-telegram-bot 22.7, requests, pytest (new — added in Task 0).

---

## Diagnostic Evidence (April 26 2026, before plan)

Confirmed by reading `/home/pi/pi-ai/llm.log`, `/home/pi/pi-ai/autonomy.log`, and querying `/home/pi/pi-ai/memory.db`:

| Symptom user saw | Confirmed root cause |
|---|---|
| 4:46 PM "i m gonna go out" → no reply | DB stored `('2026-04-26 13:46:52', 'ai', '')`. `brain.generate_reply` returned `""`; bot.py called `update.message.reply_text("")`; Telegram raises `BadRequest: text is empty`; the exception lives outside the existing `try/except` (which only wraps `brain.generate_reply`), so python-telegram-bot's default error handler swallows it. Same thing happened to the 7:44 PM "i came from the city" message: DB row `('2026-04-26 16:45:17', 'ai', '')`. |
| 4:44 PM "..." reply | `brain.py:117` — when `is_acceptable` rejects the LLM output, the literal three-dot string is sent. No retry. |
| 10:42 AM proactive sycophancy ("masterpiece") | `autonomy.py:53-58` — the phrasing call sends a *single user message* (`"Phrase this as 1 short Lache message: …"`) with **no system prompt and no PERSONA**. The model has no idea who Lache is, so it produces neutral marketing-copy output. `is_acceptable` is never called on this path either. |
| "Infinite loop and never typed" | `autonomy.log` shows `tick: trigger=new_artist but LLM returned silence` every 10 minutes from 16:51 to now (19:51). `proactive_log` is empty. `triggers.py:new_artist_trigger` dedups by querying `proactive_log` for the artist, but `autonomy.py` only writes to `proactive_log` when a message is actually sent — SILENCE returns skip the write, so the trigger refires forever. `proactive_state.last_artist` = `'Architects'`. |
| 4:42 PM persona drift ("the air is crisp, the city is alive with energy") | The reactive path *does* use PERSONA, but `BANNED_PHRASES` only catches a hand-curated set of older patterns. None of "masterpiece", "the air is crisp", "alive with energy", "you're doing great", "just like the city" are in the list. `is_acceptable` returns True, the line is sent. |

---

## File Map

| File | Role | Change |
|---|---|---|
| `tests/__init__.py` | New empty package marker | Create |
| `tests/test_brain.py` | Unit tests for `generate_reply` retry/fallback | Create |
| `tests/test_autonomy.py` | Unit tests for proactive phrasing pipeline + dedup | Create |
| `tests/test_persona_filter.py` | Unit tests for `is_acceptable` + structural style filter | Create |
| `tests/test_bot_handler.py` | Async unit test for empty-reply path | Create |
| `tests/conftest.py` | Pytest fixtures (in-memory DB, fake Ollama) | Create |
| `requirements-dev.txt` | New — pins pytest + pytest-asyncio | Create |
| `llm.py` | Add `is_acceptable_strict` (structural filter) and `chat_with_retry` helper; expand `BANNED_PHRASES`; harden `_clean` whitespace handling | Modify |
| `persona.py` | Add `IN_CHARACTER_FALLBACKS` list; add `STYLE_RULES` constant for phrasing prompts | Modify |
| `brain.py` | `generate_reply` uses `chat_with_retry`, never returns empty/"..."; pulls fallback from `persona.IN_CHARACTER_FALLBACKS` | Modify |
| `autonomy.py` | Phrasing call uses PERSONA + STYLE_RULES system prompt; goes through `chat_with_retry`; logs SILENCE attempts to a new dedup mechanism | Modify |
| `triggers.py` | `new_artist_trigger` dedups via `proactive_state` (`new_artist_attempted:<artist>:<date>`), not `proactive_log` | Modify |
| `db_helpers.py` | Add `log_quality_event(event_type, detail)`; add `was_proactive_attempted_today(trigger_type, key)` and `mark_proactive_attempted(trigger_type, key)` | Modify |
| `init_db.py` | Add `quality_log` table | Modify |
| `bot.py` | Wrap `reply_text` in try/except; validate `ai_reply` non-empty before sending; detect repeated user message within 5 min | Modify |

---

## Task 0: Bootstrap Test Harness

**Files:**
- Create: `/home/pi/pi-ai/requirements-dev.txt`
- Create: `/home/pi/pi-ai/tests/__init__.py`
- Create: `/home/pi/pi-ai/tests/conftest.py`
- Create: `/home/pi/pi-ai/pytest.ini`

- [ ] **Step 1: Add dev requirements file**

Create `/home/pi/pi-ai/requirements-dev.txt`:
```
pytest==8.3.4
pytest-asyncio==0.25.0
```

- [ ] **Step 2: Install dev requirements**

Run: `/home/pi/pi-ai/venv/bin/pip install -r /home/pi/pi-ai/requirements-dev.txt`
Expected: `Successfully installed pytest-8.3.4 pytest-asyncio-0.25.0` (plus their deps).

- [ ] **Step 3: Create tests package marker**

Create `/home/pi/pi-ai/tests/__init__.py` as an empty file (zero bytes).

- [ ] **Step 4: Create pytest config**

Create `/home/pi/pi-ai/pytest.ini`:
```ini
[pytest]
testpaths = tests
asyncio_mode = auto
addopts = -ra -q
```

- [ ] **Step 5: Create shared fixtures**

Create `/home/pi/pi-ai/tests/conftest.py`:
```python
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def fake_db(tmp_path, monkeypatch):
    """Replace DB_PATH and the schema-creation flow with an empty in-memory-style file."""
    import init_db
    import db_helpers
    import config
    db_file = tmp_path / "test.db"
    monkeypatch.setattr(config, "DB_PATH", str(db_file))
    monkeypatch.setattr(db_helpers, "DB_PATH", str(db_file), raising=False)
    init_db.main()  # creates all tables in db_file
    return str(db_file)


@pytest.fixture
def fake_ollama(monkeypatch):
    """Patch llm.chat to return scripted responses in order."""
    import llm
    calls = []
    queue = []

    def fake_chat(messages, options=None, timeout=60):
        calls.append({"messages": messages, "options": options})
        if not queue:
            return ""
        return queue.pop(0)

    monkeypatch.setattr(llm, "chat", fake_chat)
    return {"calls": calls, "queue": queue}
```

- [ ] **Step 6: Verify pytest discovers the suite**

Run: `cd /home/pi/pi-ai && /home/pi/pi-ai/venv/bin/pytest --collect-only`
Expected: `no tests ran in <time>` or `collected 0 items` (no errors). If `init_db.main` is the wrong name, look at `init_db.py` and use whatever entrypoint actually creates the schema; if it's a top-level script, run its body via `runpy.run_path` instead.

- [ ] **Step 7: Commit**

```bash
cd /home/pi/pi-ai
git add requirements-dev.txt tests/__init__.py tests/conftest.py pytest.ini
git commit -m "test: bootstrap pytest harness with shared fixtures"
```

---

## Task 1: Failing Test — Empty LLM Output Must Not Reach Telegram

**Files:**
- Create: `/home/pi/pi-ai/tests/test_brain.py`

- [ ] **Step 1: Write the failing test**

Create `/home/pi/pi-ai/tests/test_brain.py`:
```python
from unittest.mock import patch
import brain


def test_generate_reply_never_returns_empty(fake_db):
    """If the LLM returns whitespace or nothing, generate_reply must still
    produce a non-empty in-character string."""
    with patch("brain.chat", return_value="   "):
        reply = brain.generate_reply("how are you")
    assert reply.strip() != ""
    assert reply != "..."


def test_generate_reply_never_returns_three_dots(fake_db):
    """If is_acceptable rejects the first try, the user must not see '...'."""
    with patch("brain.chat", return_value="your playlist is a masterpiece"):
        reply = brain.generate_reply("how are you")
    assert reply != "..."
    assert reply.strip() != ""
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd /home/pi/pi-ai && /home/pi/pi-ai/venv/bin/pytest tests/test_brain.py -v`
Expected: both tests FAIL — first because `chat` returns `"   "` which `_clean` strips to `""` and `brain.generate_reply` returns `""`; second because the existing `is_acceptable` path returns `"..."`.

- [ ] **Step 3: Commit the failing test**

```bash
cd /home/pi/pi-ai
git add tests/test_brain.py
git commit -m "test(brain): pin empty-reply and dot-fallback failure modes"
```

---

## Task 2: `chat_with_retry` and `IN_CHARACTER_FALLBACKS`

**Files:**
- Modify: `/home/pi/pi-ai/persona.py`
- Modify: `/home/pi/pi-ai/llm.py`

- [ ] **Step 1: Add `IN_CHARACTER_FALLBACKS` to persona.py**

In `/home/pi/pi-ai/persona.py`, append this constant after `get_vibe()`:
```python
# Last-resort replies when both the first generation and the retry fail validation.
# These must read like Lache: short, lowercase, no poetry, no sycophancy.
IN_CHARACTER_FALLBACKS = [
    "hm, brain glitched. say it again?",
    "blanked for a sec, what was that?",
    "yeah?",
    "tell me more",
    "go on",
]
```

- [ ] **Step 2: Add the structural style filter and retry helper to llm.py**

In `/home/pi/pi-ai/llm.py`, expand `BANNED_PHRASES` to include the patterns we caught today, then append two new functions before the existing `chat_json`:

Replace the current `BANNED_PHRASES` list with:
```python
BANNED_PHRASES = [
    # original list
    "chill of cluj", "whispers of", "silence of the night",
    "your companion", "how can i assist", "how can i help",
    "city lights", "enjoy the vibe", "what would you like to explore",
    "let the silence", "let the city", "let the night", "let the music",
    "symphony", "composer", "you're the artist", "speak for you",
    "king of the night", "no need for extra effort",
    # added 2026-04-26 — observed in production drift
    "masterpiece", "the air is crisp", "alive with energy",
    "you're doing great", "just like the city", "today is perfect",
    "playlist is a", "as your personal", "personal ai",
    "i'm here to", "i am here to",
]
```

Add this function below `is_acceptable`:
```python
def is_in_character(text):
    """Structural style filter — catches poetry/sycophancy patterns the
    blocklist misses. Returns True if the text looks like Lache."""
    if not text or not text.strip():
        return False
    s = text.strip()
    # Hard caps — Lache is short.
    if len(s) > 220:
        return False
    if s.count(".") + s.count("!") + s.count("?") > 3:
        return False
    # Em-dash + adjective is the signature poetry pattern ("alive — vibrant — perfect").
    if s.count("—") >= 2:
        return False
    # Title-case-everything is a marketing-copy tell.
    words = [w for w in s.split() if w.isalpha()]
    if len(words) >= 6:
        capitalised = sum(1 for w in words if w[0].isupper())
        if capitalised / len(words) > 0.5:
            return False
    return is_acceptable(s)
```

Add this function at the bottom of `llm.py` (after `chat_json`):
```python
def chat_with_retry(messages, options=None, timeout=60, retry_hint=None):
    """Generate, validate against `is_in_character`, and retry once with a
    corrective hint if the first try fails. Returns (text, ok_flag).

    ok_flag is False when both attempts failed — caller is responsible for
    surfacing an in-character fallback instead of the (possibly empty) text.
    """
    first = chat(messages, options, timeout)
    if is_in_character(first):
        return first, True
    hint = retry_hint or (
        "your previous draft was either empty or too poetic. write one short, "
        "lowercase, casual sentence in lache's voice — no metaphors, no "
        "compliments, no marketing copy. if you have nothing real to say, "
        "ask a short follow-up question."
    )
    retry_messages = list(messages) + [
        {"role": "assistant", "content": first or "(empty)"},
        {"role": "user", "content": hint},
    ]
    second = chat(retry_messages, options, timeout)
    if is_in_character(second):
        return second, True
    return second, False
```

- [ ] **Step 3: Add tests covering the new helpers**

Create `/home/pi/pi-ai/tests/test_persona_filter.py`:
```python
from llm import is_in_character


def test_rejects_empty():
    assert not is_in_character("")
    assert not is_in_character("   ")


def test_rejects_poetic_today_message():
    assert not is_in_character(
        "today is perfect, the air is crisp, and the city is "
        "alive with energy. you're doing great, just like the city."
    )


def test_rejects_marketing_compliment():
    assert not is_in_character(
        "Trivium and Of Mice & Men—your playlist is a masterpiece."
    )


def test_accepts_lache_voice():
    assert is_in_character("running fine, nothing broken yet. you good?")
    assert is_in_character("bars or just driving around?")
```

- [ ] **Step 4: Run filter tests, confirm they pass**

Run: `cd /home/pi/pi-ai && /home/pi/pi-ai/venv/bin/pytest tests/test_persona_filter.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/pi/pi-ai
git add persona.py llm.py tests/test_persona_filter.py
git commit -m "feat(llm): add chat_with_retry + structural in-character filter"
```

---

## Task 3: `brain.generate_reply` Uses Retry + Real Fallback

**Files:**
- Modify: `/home/pi/pi-ai/brain.py`

- [ ] **Step 1: Rewrite the body of `generate_reply`**

In `/home/pi/pi-ai/brain.py`, replace the existing `try`/`except` block at the end of `generate_reply` (currently lines 113–121, the block that calls `chat`, checks `is_acceptable`, and falls back to `"..."` or `"one sec, thinking..."`) with:
```python
    import random
    from persona import IN_CHARACTER_FALLBACKS
    from llm import chat_with_retry

    try:
        reply, ok = chat_with_retry(messages, OLLAMA_OPTIONS_CHAT, timeout=90)
    except Exception:
        return random.choice(IN_CHARACTER_FALLBACKS)

    if ok:
        return reply
    return random.choice(IN_CHARACTER_FALLBACKS)
```

Move the two new imports to the top of `brain.py` if you prefer; the inline form above is fine and keeps the diff small.

- [ ] **Step 2: Run the Task-1 tests, confirm they now pass**

Run: `cd /home/pi/pi-ai && /home/pi/pi-ai/venv/bin/pytest tests/test_brain.py -v`
Expected: 2 passed. Both replies are now non-empty and never `"..."`.

- [ ] **Step 3: Add a positive-path test**

Append to `/home/pi/pi-ai/tests/test_brain.py`:
```python
def test_generate_reply_passes_through_good_output(fake_db):
    with patch("brain.chat_with_retry", return_value=("yeah, going where?", True)):
        reply = brain.generate_reply("yeah i m going out")
    assert reply == "yeah, going where?"
```

Run: `cd /home/pi/pi-ai && /home/pi/pi-ai/venv/bin/pytest tests/test_brain.py -v`
Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
cd /home/pi/pi-ai
git add brain.py tests/test_brain.py
git commit -m "fix(brain): retry on bad output, fall back in-character not '...'"
```

---

## Task 4: Harden bot.py Against Empty / Failed Sends

**Files:**
- Modify: `/home/pi/pi-ai/bot.py`
- Create: `/home/pi/pi-ai/tests/test_bot_handler.py`

- [ ] **Step 1: Write the failing async test**

Create `/home/pi/pi-ai/tests/test_bot_handler.py`:
```python
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import bot


@pytest.mark.asyncio
async def test_empty_brain_reply_does_not_crash_handler(fake_db):
    """If brain.generate_reply returns empty, bot must not call reply_text('')."""
    update = MagicMock()
    update.message.text = "i m gonna go out"
    update.message.chat_id = 123
    update.message.reply_text = AsyncMock()

    ctx = MagicMock()
    ctx.bot.send_chat_action = AsyncMock()

    with patch("bot.brain.generate_reply", return_value=""):
        await bot.handle_message(update, ctx)

    # Either we never called reply_text (the handler short-circuited with a
    # logged warning) or we called it with non-empty text. We must NEVER call
    # it with an empty string.
    for call in update.message.reply_text.call_args_list:
        sent = call.args[0] if call.args else call.kwargs.get("text", "")
        assert sent and sent.strip(), f"sent empty payload: {sent!r}"


@pytest.mark.asyncio
async def test_telegram_reply_failure_is_logged_not_swallowed(fake_db, caplog):
    update = MagicMock()
    update.message.text = "hey"
    update.message.chat_id = 123
    update.message.reply_text = AsyncMock(side_effect=RuntimeError("network"))

    ctx = MagicMock()
    ctx.bot.send_chat_action = AsyncMock()

    with patch("bot.brain.generate_reply", return_value="hey back"):
        await bot.handle_message(update, ctx)  # must not raise

    assert any("reply_text" in r.message or "network" in r.message
               for r in caplog.records)
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `cd /home/pi/pi-ai && /home/pi/pi-ai/venv/bin/pytest tests/test_bot_handler.py -v`
Expected: both fail — current code calls `reply_text("")` and lets the second `reply_text` exception escape.

- [ ] **Step 3: Patch `handle_message`**

In `/home/pi/pi-ai/bot.py`, replace the body of `handle_message` (currently lines 19–37) with:
```python
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_msg = update.message.text
    chat_id = update.message.chat_id
    db_helpers.log_message('user', user_msg)
    await context.bot.send_chat_action(chat_id=chat_id, action='typing')

    try:
        ai_reply = brain.generate_reply(user_msg)
    except Exception as e:
        _log.error(f"brain.generate_reply failed: {e}", exc_info=True)
        ai_reply = "brain hiccup, try again in a sec"

    if not ai_reply or not ai_reply.strip():
        _log.error("generate_reply returned empty; using last-resort fallback")
        from persona import IN_CHARACTER_FALLBACKS
        import random
        ai_reply = random.choice(IN_CHARACTER_FALLBACKS)

    db_helpers.log_message('ai', ai_reply)

    try:
        await update.message.reply_text(ai_reply)
    except Exception as e:
        _log.error(f"reply_text failed: {e}", exc_info=True)

    for fact in regex_facts.extract_facts(user_msg):
        with db_helpers.get_conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO user_facts (fact_key, fact_value, source, confidence) VALUES (?,?,?,?)",
                (fact["key"], fact["value"], fact["source"], fact["confidence"])
            )
```

Also raise the bot logger to INFO so the empty-reply error actually gets written; change line 16 from `level=logging.ERROR` to `level=logging.INFO`.

- [ ] **Step 4: Run tests, confirm they pass**

Run: `cd /home/pi/pi-ai && /home/pi/pi-ai/venv/bin/pytest tests/test_bot_handler.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/pi/pi-ai
git add bot.py tests/test_bot_handler.py
git commit -m "fix(bot): never send empty payload, log reply_text failures"
```

---

## Task 5: Autonomy Phrasing Uses PERSONA + retry pipeline

**Files:**
- Modify: `/home/pi/pi-ai/autonomy.py`
- Create: `/home/pi/pi-ai/tests/test_autonomy.py`

- [ ] **Step 1: Write the failing test**

Create `/home/pi/pi-ai/tests/test_autonomy.py`:
```python
from unittest.mock import patch
import autonomy


def test_phrasing_call_includes_persona_system_prompt(fake_db):
    """The proactive phrasing call must put PERSONA in a system message —
    that's the bug behind the 10:42 'masterpiece' message."""
    captured = {}

    def fake_chat_with_retry(messages, options=None, timeout=60, retry_hint=None):
        captured["messages"] = messages
        return "yo, first time hearing architects in a while", True

    with patch("autonomy.ALL_TRIGGERS", [
        ("new_artist",
         lambda: (True, "first time hearing Architects in a while, what made you put it on?"))
    ]), patch("autonomy.chat_with_retry", fake_chat_with_retry), \
         patch("autonomy.send_telegram_message"), \
         patch("autonomy.db_helpers.was_recently_active", return_value=False):
        autonomy.heartbeat()

    msgs = captured["messages"]
    assert msgs[0]["role"] == "system"
    assert "Lache" in msgs[0]["content"]
    assert "no poetry" in msgs[0]["content"].lower() or "casual" in msgs[0]["content"].lower()
```

- [ ] **Step 2: Run, confirm it fails**

Run: `cd /home/pi/pi-ai && /home/pi/pi-ai/venv/bin/pytest tests/test_autonomy.py -v`
Expected: FAIL — current code passes a single user-role message and uses `chat`, not `chat_with_retry`.

- [ ] **Step 3: Patch `autonomy.heartbeat`**

In `/home/pi/pi-ai/autonomy.py`:

a) Add this import at the top:
```python
from llm import chat_with_retry
from persona import PERSONA, IN_CHARACTER_FALLBACKS
```
(remove the existing `from llm import chat` import — it's no longer used here).

b) Replace the LLM phrasing block (currently lines 53–58) with:
```python
    phrasing_messages = [
        {"role": "system", "content": (
            f"{PERSONA}\n\n"
            "You will be given a one-line idea. Rephrase it in Lache's voice. "
            "Output ONE casual lowercase sentence, max 20 words. No emojis, "
            "no metaphors, no compliments, no follow-up explanation. If the "
            "idea is empty, reply with the literal word SILENCE."
        )},
        {"role": "user", "content": fired_context},
    ]
    try:
        message, ok = chat_with_retry(
            phrasing_messages,
            {"temperature": 0.7, "num_predict": 60},
            timeout=60,
        )
    except Exception as e:
        logging.error(f"LLM phrasing failed for trigger {fired_type}: {e}")
        return

    if not ok or not message or message.strip().upper() == "SILENCE":
        latency = int((_time.time() - t0) * 1000)
        logging.info(f"tick: trigger={fired_type} returned silence latency_ms={latency}")
        # IMPORTANT: still mark the trigger attempted so it cools down — Task 6
        db_helpers.mark_proactive_attempted(fired_type, fired_context[:100])
        return
```

- [ ] **Step 4: Re-run the test**

Run: `cd /home/pi/pi-ai && /home/pi/pi-ai/venv/bin/pytest tests/test_autonomy.py -v`
Expected: 1 passed. (The `mark_proactive_attempted` call will fail at import time until Task 6 lands — that's fine, this test patches around it. If the test runner complains about the missing function, add a temporary `def mark_proactive_attempted(*a, **kw): pass` stub to `db_helpers.py` and remove it in Task 6.)

- [ ] **Step 5: Commit**

```bash
cd /home/pi/pi-ai
git add autonomy.py tests/test_autonomy.py
git commit -m "fix(autonomy): phrasing call uses PERSONA + chat_with_retry"
```

---

## Task 6: Proactive Trigger Dedup Uses `proactive_state`, Not `proactive_log`

**Files:**
- Modify: `/home/pi/pi-ai/db_helpers.py`
- Modify: `/home/pi/pi-ai/triggers.py`
- Modify: `/home/pi/pi-ai/autonomy.py`

- [ ] **Step 1: Write the failing test**

Append to `/home/pi/pi-ai/tests/test_autonomy.py`:
```python
import db_helpers


def test_new_artist_trigger_does_not_refire_after_silence(fake_db):
    """If autonomy attempts a trigger and the LLM returns SILENCE, the
    trigger must NOT fire again on the next tick — even though no message
    was logged to proactive_log."""
    db_helpers.set_proactive_state("last_artist", "Architects")

    # First attempt: LLM returns SILENCE.
    with patch("autonomy.chat_with_retry", return_value=("SILENCE", False)), \
         patch("autonomy.send_telegram_message"), \
         patch("autonomy.db_helpers.was_recently_active", return_value=False), \
         patch("triggers.spotify_sync.get_recent_tracks", return_value="Recent tracks: Architects - x"):
        autonomy.heartbeat()

    # Second attempt: must NOT call chat_with_retry at all because the
    # trigger should already be marked attempted today.
    with patch("autonomy.chat_with_retry") as second_call, \
         patch("autonomy.send_telegram_message"), \
         patch("autonomy.db_helpers.was_recently_active", return_value=False), \
         patch("triggers.spotify_sync.get_recent_tracks", return_value="Recent tracks: Architects - x"):
        autonomy.heartbeat()

    assert second_call.call_count == 0
```

- [ ] **Step 2: Run, confirm it fails**

Run: `cd /home/pi/pi-ai && /home/pi/pi-ai/venv/bin/pytest tests/test_autonomy.py::test_new_artist_trigger_does_not_refire_after_silence -v`
Expected: FAIL — second tick re-fires the trigger.

- [ ] **Step 3: Add helpers to `db_helpers.py`**

Append to `/home/pi/pi-ai/db_helpers.py`:
```python
from datetime import datetime


def mark_proactive_attempted(trigger_type, trigger_key):
    """Record that a proactive trigger was attempted today, regardless of
    whether the LLM produced a sendable message. Used for dedup so a
    SILENCE response still cools the trigger down for the rest of the day."""
    state_key = f"attempted:{trigger_type}:{trigger_key}"
    today = datetime.now().strftime("%Y-%m-%d")
    set_proactive_state(state_key, today)


def was_proactive_attempted_today(trigger_type, trigger_key):
    state_key = f"attempted:{trigger_type}:{trigger_key}"
    today = datetime.now().strftime("%Y-%m-%d")
    val = get_proactive_state(state_key)
    return val == today
```

(If `set_proactive_state` / `get_proactive_state` don't already exist in the file, also add them — they're trivial UPSERTs against `proactive_state`. The doc says they're already present; verify by `grep -n proactive_state db_helpers.py` first and only add what's missing.)

- [ ] **Step 4: Update `triggers.py:new_artist_trigger`**

Replace the body of `new_artist_trigger` in `/home/pi/pi-ai/triggers.py` with:
```python
def new_artist_trigger():
    try:
        current_raw = spotify_sync.get_recent_tracks()
        if not current_raw or "unavailable" in current_raw.lower():
            return False, ""
        last_artist = db_helpers.get_proactive_state('last_artist')
        if not last_artist:
            return False, ""
        if db_helpers.was_proactive_attempted_today('new_artist', last_artist):
            return False, ""
        # 7-day "have we already mentioned them recently" guard, kept from before.
        cutoff = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
        with db_helpers.get_conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM proactive_log WHERE trigger_type='new_artist' AND trigger_key=? AND timestamp > ?",
                (last_artist, cutoff)
            ).fetchone()[0]
        if count > 0:
            return False, ""
        return True, f"first time hearing {last_artist} in a while, what made you put it on?"
    except Exception:
        return False, ""
```

- [ ] **Step 5: Update `autonomy.py` send-success path**

In `/home/pi/pi-ai/autonomy.py`, in the success path (where `db_helpers.log_proactive` is called, around line 67), add the attempt-mark right before it:
```python
    db_helpers.log_message('ai', message)
    db_helpers.mark_proactive_attempted(fired_type, fired_context[:100])
    db_helpers.log_proactive(fired_type, fired_context[:100], message)
    send_telegram_message(message)
```

(The Task-5 SILENCE path already calls `mark_proactive_attempted`; this ensures the success path does too.)

- [ ] **Step 6: Run tests**

Run: `cd /home/pi/pi-ai && /home/pi/pi-ai/venv/bin/pytest tests/test_autonomy.py -v`
Expected: all pass.

- [ ] **Step 7: One-time cleanup of the live runaway loop**

Run on the Pi (this is a manual operational step, not a code change):
```bash
/home/pi/pi-ai/venv/bin/python -c "
import db_helpers
db_helpers.mark_proactive_attempted('new_artist', 'Architects')
print('cooled down new_artist trigger for today')
"
```
This stops the every-10-minutes loop from continuing while the rest of the plan rolls out.

- [ ] **Step 8: Commit**

```bash
cd /home/pi/pi-ai
git add db_helpers.py triggers.py autonomy.py tests/test_autonomy.py
git commit -m "fix(triggers): dedup new_artist via proactive_state, cool down on SILENCE"
```

---

## Task 7: Harden `_clean` So Whitespace-Only Output Is Detected

**Files:**
- Modify: `/home/pi/pi-ai/llm.py`
- Modify: `/home/pi/pi-ai/tests/test_persona_filter.py`

- [ ] **Step 1: Write the failing test**

Append to `/home/pi/pi-ai/tests/test_persona_filter.py`:
```python
from llm import _clean


def test_clean_collapses_thinking_only_output_to_empty():
    """When Qwen3 emits only think tags (despite /no_think), _clean must
    return an empty string so chat_with_retry's validator catches it."""
    raw = "<think>let me think about this carefully...</think>\n   \n  "
    assert _clean(raw) == ""


def test_clean_strips_lache_prefix_case_insensitive():
    assert _clean("Lache: hey") == "hey"
    assert _clean("LACHE: yo") == "yo"
```

- [ ] **Step 2: Run, confirm pass/fail**

Run: `cd /home/pi/pi-ai && /home/pi/pi-ai/venv/bin/pytest tests/test_persona_filter.py -v`
Expected: the first test passes (current `_clean` already handles this), the second probably passes too — but if either fails, fix `_clean` until they do. The current `_clean` already lowercases the prefix match; this test simply locks in that behaviour.

- [ ] **Step 3: Commit (regression coverage only — likely no code change)**

```bash
cd /home/pi/pi-ai
git add tests/test_persona_filter.py
git commit -m "test(llm): pin _clean behaviour on think-only and prefix output"
```

---

## Task 8: Quality Telemetry Table

**Files:**
- Modify: `/home/pi/pi-ai/init_db.py`
- Modify: `/home/pi/pi-ai/db_helpers.py`
- Modify: `/home/pi/pi-ai/llm.py`

- [ ] **Step 1: Add `quality_log` table to schema**

In `/home/pi/pi-ai/init_db.py`, inside whichever function creates the other tables, add:
```python
    c.execute("""
        CREATE TABLE IF NOT EXISTS quality_log (
            id INTEGER PRIMARY KEY,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            event_type TEXT,
            detail TEXT
        )
    """)
```

- [ ] **Step 2: Add helper to `db_helpers.py`**

Append:
```python
def log_quality_event(event_type, detail=""):
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO quality_log (event_type, detail) VALUES (?, ?)",
                (event_type, str(detail)[:500])
            )
    except Exception:
        # Telemetry is best-effort; never let it break the main path.
        pass
```

- [ ] **Step 3: Wire telemetry into `chat_with_retry`**

In `/home/pi/pi-ai/llm.py`, modify `chat_with_retry` to call `db_helpers.log_quality_event` at three points: when the first attempt fails validation (`event_type='retry_triggered'`, detail = first 200 chars of `first`); when retry succeeds (`event_type='retry_succeeded'`); when retry also fails (`event_type='retry_failed'`, detail = first 200 chars of `second`). Import `db_helpers` lazily inside the function to avoid circular imports.

- [ ] **Step 4: Run the schema migration on the live DB**

Run: `cd /home/pi/pi-ai && /home/pi/pi-ai/venv/bin/python init_db.py`
Expected: prints whatever it prints today; `quality_log` table now exists. Confirm with:
```bash
/home/pi/pi-ai/venv/bin/python -c "
import sqlite3
con = sqlite3.connect('/home/pi/pi-ai/memory.db')
print([r[0] for r in con.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")])
"
```
Expected output includes `'quality_log'`.

- [ ] **Step 5: Commit**

```bash
cd /home/pi/pi-ai
git add init_db.py db_helpers.py llm.py
git commit -m "feat(telemetry): log retry/fallback events to quality_log"
```

---

## Task 9: Detect User Re-send Within 5 Minutes

**Files:**
- Modify: `/home/pi/pi-ai/bot.py`
- Modify: `/home/pi/pi-ai/tests/test_bot_handler.py`

- [ ] **Step 1: Write the failing test**

Append to `/home/pi/pi-ai/tests/test_bot_handler.py`:
```python
@pytest.mark.asyncio
async def test_repeated_user_message_logs_quality_event(fake_db):
    """When the user sends nearly the same text within 5 minutes, log a
    'user_repeated' quality event — that's our signal the previous reply
    failed (e.g. the 4:44 vs 4:46 'going out' duplicate)."""
    import db_helpers
    db_helpers.log_message('user', 'yeah i m going out')
    db_helpers.log_message('ai', '...')

    update = MagicMock()
    update.message.text = "i m gonna go out"
    update.message.chat_id = 123
    update.message.reply_text = AsyncMock()

    ctx = MagicMock()
    ctx.bot.send_chat_action = AsyncMock()

    with patch("bot.brain.generate_reply", return_value="bars or cruising?"):
        await bot.handle_message(update, ctx)

    with db_helpers.get_conn() as conn:
        events = conn.execute(
            "SELECT event_type FROM quality_log"
        ).fetchall()
    assert any(e[0] == "user_repeated" for e in events)
```

- [ ] **Step 2: Run, confirm fail**

Run: `cd /home/pi/pi-ai && /home/pi/pi-ai/venv/bin/pytest tests/test_bot_handler.py -v`
Expected: this test fails.

- [ ] **Step 3: Implement repetition detection**

In `/home/pi/pi-ai/bot.py`, add a helper above `handle_message`:
```python
def _user_recently_repeated(current_text):
    """True if the user sent a near-duplicate of `current_text` within the
    last 5 minutes. Cheap fuzzy match: same prefix or same set of content
    words, ignoring whitespace and punctuation."""
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')
    with db_helpers.get_conn() as conn:
        rows = conn.execute(
            "SELECT message FROM conversations "
            "WHERE sender='user' AND timestamp > ? "
            "ORDER BY timestamp DESC LIMIT 3",
            (cutoff,)
        ).fetchall()
    cur_words = {w for w in current_text.lower().split() if len(w) > 2}
    for (prev,) in rows:
        prev_words = {w for w in prev.lower().split() if len(w) > 2}
        if cur_words and prev_words and len(cur_words & prev_words) / max(len(cur_words), len(prev_words)) > 0.6:
            return True
    return False
```

In `handle_message`, right after `db_helpers.log_message('user', user_msg)`, add:
```python
    if _user_recently_repeated(user_msg):
        db_helpers.log_quality_event("user_repeated", user_msg[:200])
```

- [ ] **Step 4: Run, confirm pass**

Run: `cd /home/pi/pi-ai && /home/pi/pi-ai/venv/bin/pytest tests/test_bot_handler.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd /home/pi/pi-ai
git add bot.py tests/test_bot_handler.py
git commit -m "feat(bot): tag near-duplicate user messages as quality signal"
```

---

## Task 10: Live Smoke Test on the Pi

**Files:** None (operational verification).

- [ ] **Step 1: Run the full test suite**

Run: `cd /home/pi/pi-ai && /home/pi/pi-ai/venv/bin/pytest -v`
Expected: all tests pass.

- [ ] **Step 2: Restart services**

Run:
```bash
sudo systemctl restart piai.service piaibot.service
sudo systemctl status piai.service piaibot.service --no-pager | head -20
```
Expected: both services `active (running)`.

- [ ] **Step 3: Tail the logs in one window**

Run: `tail -f /home/pi/pi-ai/llm.log /home/pi/pi-ai/autonomy.log /home/pi/pi-ai/bot.log`

- [ ] **Step 4: Manual reactive test from Telegram**

From the Telegram chat with Lache, send these in order, with ~30s between each:
1. `how are you today`  → expected: short lowercase casual reply, no poetry, no "the air is crisp"
2. `yeah i m going out` → expected: short relevant follow-up, never "..."
3. `i m gonna go out`   → expected: a different, non-empty reply (this used to vanish)

After each, confirm in `bot.log` that no `reply_text failed` errors appear and no `using last-resort fallback` warnings appear (the fallback is allowed to fire occasionally — but if it fires every time, the persona prompt needs more tuning).

- [ ] **Step 5: Confirm proactive loop is no longer firing every 10 minutes**

Watch `autonomy.log`. The next tick should either fire `new_artist` *exactly once* (and write to `proactive_log` and `proactive_state.attempted:new_artist:Architects`) or skip the trigger because Task 6's manual cool-down already marked it attempted today. Either way, the every-10-minutes `tick: trigger=new_artist but LLM returned silence` pattern must stop.

Verify with:
```bash
/home/pi/pi-ai/venv/bin/python -c "
import sqlite3
con = sqlite3.connect('/home/pi/pi-ai/memory.db')
for row in con.execute(\"SELECT key, value FROM proactive_state WHERE key LIKE 'attempted:%'\"):
    print(row)
"
```
Expected: at least one row like `('attempted:new_artist:Architects', '2026-04-26')`.

- [ ] **Step 6: Inspect quality_log**

```bash
/home/pi/pi-ai/venv/bin/python -c "
import sqlite3
con = sqlite3.connect('/home/pi/pi-ai/memory.db')
for row in con.execute('SELECT timestamp, event_type, substr(detail,1,80) FROM quality_log ORDER BY timestamp DESC LIMIT 20'):
    print(row)
"
```
Use this to gauge how often retry / fallback is firing in real use. If `retry_triggered` >> `retry_succeeded`, the persona prompt or the structural filter needs tuning — that's a follow-up, not a blocker.

- [ ] **Step 7: Push**

```bash
cd /home/pi/pi-ai
git push origin master
```

---

## Out of Scope (Deliberately)

These came up during analysis but should NOT be done in this plan — they're either premature optimisation or independent features:

- **Switching to Qwen3-2B** — listed as "what's left" in the briefing. Do this only if, after Task 10, the persona is still drifting *despite* `chat_with_retry` and `is_in_character`. Don't bundle it.
- **`/facts` Telegram command** — separate feature, listed in the briefing.
- **Restructuring proactive_log / migrating historical data** — current empty state is fine; don't touch it.
- **Cleaning up `BANNED_PHRASES` into a regex-based system** — the structural filter (`is_in_character`) is the real defence; the blocklist is just a cheap supplement. Don't over-engineer it.
- **A `/quality` Telegram command to read `quality_log`** — nice-to-have, not needed for this plan.

---

## Self-Review

| Spec requirement | Task that addresses it |
|---|---|
| 4:46 / 7:45 empty replies | Task 1 (test), Task 3 (brain fix), Task 4 (bot guard) |
| 4:44 "..." reply | Task 1 (test), Task 3 (in-character fallback) |
| 10:42 "masterpiece" sycophancy | Task 5 (PERSONA in autonomy phrasing) |
| 4:42 "the air is crisp" persona drift | Task 2 (`is_in_character` + expanded BANNED_PHRASES) |
| Infinite proactive loop (every 10 min) | Task 6 (proactive_state-based dedup) + Task 6 Step 7 (one-time cool-down) |
| User repetition signal | Task 9 |
| Future drift visibility | Task 8 (`quality_log`) |
