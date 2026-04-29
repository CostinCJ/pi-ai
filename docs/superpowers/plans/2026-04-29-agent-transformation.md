# Agent Transformation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform Lache from a reactive bot into a lightweight agent with web search, reminders, photo perception, and smarter proactive reasoning — while preserving every behaviour that currently works.

**Architecture:** Surgical additions only — new `tools.py`, `chat_with_tools()` in `llm.py`, `generate_agentic_reply()` in `brain.py`, photo handler + `/remind` command in `bot.py`, `free_reasoning_trigger()` replacing `pattern_surface` + `open_thread` in `triggers.py`, and a reminder delivery job in `autonomy.py`. The existing `generate_reply()` stays as a fallback throughout.

**Tech Stack:** Python 3, Groq API (function-calling + vision), duckduckgo-search, SQLite, APScheduler, python-telegram-bot.

---

## Task 0: Commit all pending changes and push to remote

**Files:** (git operations only)

- [ ] **Step 1: Check current git status**

```bash
cd /home/pi/pi-ai && git status --short
```

- [ ] **Step 2: Stage all modified tracked files and safe untracked files**

```bash
cd /home/pi/pi-ai && git add \
  .gitignore autonomy.py bot.py brain.py config.py consolidation.py \
  db_helpers.py init_db.py llm.py network_radar.py persona.py \
  reflection.py regex_facts.py requirements-dev.txt schedule.py \
  session_daemon.py session_server.py triggers.py weather_sync.py \
  tests/conftest.py tests/test_autonomy.py tests/test_bot_handler.py \
  tests/test_network_radar.py tests/test_presence.py tests/test_session.py \
  .env.example .github/ llm_facts.py piai.service piaibot.service scripts/ \
  tests/test_regex_facts.py tests/test_triggers.py tests/test_user_repeat.py \
  docs/superpowers/plans/2026-04-26-fix-conversational-failures.md \
  piaisession.service 2>/dev/null; echo "staged"
```

- [ ] **Step 3: Commit**

```bash
cd /home/pi/pi-ai && git commit -m "$(cat <<'EOF'
chore: sync all in-flight changes before agent transformation

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4: Push to remote**

```bash
cd /home/pi/pi-ai && git push origin master
```

Expected: push succeeds, remote is now up to date.

---

## Task 1: Config + dependency setup

**Files:**
- Modify: `config.py`
- Modify: `requirements-dev.txt`
- Modify: `.env.example`

- [ ] **Step 1: Install duckduckgo-search into the project venv**

```bash
/home/pi/pi-ai/venv/bin/pip install "duckduckgo-search>=6.0.0"
```

Expected output: `Successfully installed duckduckgo-search-...`

- [ ] **Step 2: Verify the import works**

```bash
/home/pi/pi-ai/venv/bin/python -c "from duckduckgo_search import DDGS; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Add GROQ_VISION_MODEL and SEARCH_MAX_RESULTS to config.py**

Open `/home/pi/pi-ai/config.py`. After the `GROQ_MODEL` line (line 33), add:

```python
GROQ_VISION_MODEL  = _opt("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
SEARCH_MAX_RESULTS = int(_opt("SEARCH_MAX_RESULTS", "3"))
```

- [ ] **Step 4: Add to requirements-dev.txt**

Open `/home/pi/pi-ai/requirements-dev.txt`. Add at the end:

```
duckduckgo-search>=6.0.0
```

- [ ] **Step 5: Add to .env.example**

Open `/home/pi/pi-ai/.env.example`. Add at the end:

```
GROQ_VISION_MODEL=meta-llama/llama-4-scout-17b-16e-instruct
SEARCH_MAX_RESULTS=3
```

- [ ] **Step 6: Verify config loads without error**

```bash
cd /home/pi/pi-ai && venv/bin/python -c "import config; print(config.GROQ_VISION_MODEL, config.SEARCH_MAX_RESULTS)"
```

Expected: `meta-llama/llama-4-scout-17b-16e-instruct 3`

- [ ] **Step 7: Commit**

```bash
cd /home/pi/pi-ai && git add config.py requirements-dev.txt .env.example && git commit -m "$(cat <<'EOF'
feat: add GROQ_VISION_MODEL, SEARCH_MAX_RESULTS config; install duckduckgo-search

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: DB layer — reminders table + helpers

**Files:**
- Modify: `init_db.py`
- Modify: `db_helpers.py`
- Create: `tests/test_reminders.py`

- [ ] **Step 1: Write failing tests**

Create `/home/pi/pi-ai/tests/test_reminders.py`:

```python
from datetime import datetime, timedelta
import db_helpers


def test_add_and_get_due_reminder(fake_db):
    fire_at = (datetime.now() - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    db_helpers.add_reminder("call mom", fire_at)
    due = db_helpers.get_due_reminders()
    assert len(due) == 1
    assert due[0]["text"] == "call mom"
    assert due[0]["id"] > 0


def test_future_reminder_not_due(fake_db):
    fire_at = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    db_helpers.add_reminder("future task", fire_at)
    due = db_helpers.get_due_reminders()
    assert len(due) == 0


def test_mark_reminder_delivered(fake_db):
    fire_at = (datetime.now() - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    db_helpers.add_reminder("test", fire_at)
    due = db_helpers.get_due_reminders()
    db_helpers.mark_reminder_delivered(due[0]["id"])
    assert len(db_helpers.get_due_reminders()) == 0


def test_delivered_reminder_not_returned(fake_db):
    fire_at = (datetime.now() - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    db_helpers.add_reminder("already done", fire_at)
    due = db_helpers.get_due_reminders()
    db_helpers.mark_reminder_delivered(due[0]["id"])
    assert db_helpers.get_due_reminders() == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/test_reminders.py -v
```

Expected: all 4 tests FAIL with `AttributeError: module 'db_helpers' has no attribute 'add_reminder'`

- [ ] **Step 3: Add reminders table to init_db.py**

Open `/home/pi/pi-ai/init_db.py`. After the session_snapshot block (before the migrations section), add:

```python
    # 13. Reminders
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            text       TEXT NOT NULL,
            fire_at    TEXT NOT NULL,
            delivered  INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
```

- [ ] **Step 4: Add three helpers to db_helpers.py**

Open `/home/pi/pi-ai/db_helpers.py`. At the end of the file, add:

```python
def add_reminder(text, fire_at):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO reminders (text, fire_at) VALUES (?, ?)",
            (text, fire_at)
        )

def get_due_reminders():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, text, fire_at FROM reminders "
            "WHERE delivered=0 AND fire_at <= datetime('now') "
            "ORDER BY fire_at ASC"
        ).fetchall()
    return [{"id": r[0], "text": r[1], "fire_at": r[2]} for r in rows]

def mark_reminder_delivered(reminder_id):
    with get_conn() as conn:
        conn.execute(
            "UPDATE reminders SET delivered=1 WHERE id=?",
            (reminder_id,)
        )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/test_reminders.py -v
```

Expected: all 4 tests PASS

- [ ] **Step 6: Commit**

```bash
cd /home/pi/pi-ai && git add init_db.py db_helpers.py tests/test_reminders.py && git commit -m "$(cat <<'EOF'
feat: add reminders table and db helpers (add/get_due/mark_delivered)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: tools.py — web_search()

**Files:**
- Create: `tools.py`
- Create: `tests/test_tools.py`

- [ ] **Step 1: Write failing tests**

Create `/home/pi/pi-ai/tests/test_tools.py`:

```python
import pytest


def test_web_search_returns_formatted_results(monkeypatch):
    import tools

    fake_results = [
        {"title": "Cluj Weather", "body": "Sunny and 22°C", "href": "https://example.com/weather"},
        {"title": "Another Result", "body": "Some snippet", "href": "https://example.com/two"},
    ]

    class FakeDDGS:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def text(self, query, max_results): return iter(fake_results)

    monkeypatch.setattr(tools, "DDGS", FakeDDGS)
    result = tools.web_search("weather in cluj")

    assert "Cluj Weather" in result
    assert "Sunny and 22°C" in result
    assert "https://example.com/weather" in result


def test_web_search_empty_results(monkeypatch):
    import tools

    class EmptyDDGS:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def text(self, query, max_results): return iter([])

    monkeypatch.setattr(tools, "DDGS", EmptyDDGS)
    result = tools.web_search("nothing found")
    assert "no results" in result


def test_web_search_handles_exception(monkeypatch):
    import tools

    class BrokenDDGS:
        def __enter__(self): raise RuntimeError("network error")
        def __exit__(self, *a): pass

    monkeypatch.setattr(tools, "DDGS", BrokenDDGS)
    result = tools.web_search("anything")
    assert "failed" in result.lower()


def test_web_search_truncates_long_snippets(monkeypatch):
    import tools

    fake_results = [{"title": "T", "body": "x" * 500, "href": "https://example.com"}]

    class FakeDDGS:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def text(self, query, max_results): return iter(fake_results)

    monkeypatch.setattr(tools, "DDGS", FakeDDGS)
    result = tools.web_search("test")
    # body is truncated to 200 chars in format string
    assert len(result) < 1000
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/test_tools.py -v 2>&1 | head -20
```

Expected: FAIL with `ModuleNotFoundError: No module named 'tools'`

- [ ] **Step 3: Create tools.py with web_search()**

Create `/home/pi/pi-ai/tools.py`:

```python
from duckduckgo_search import DDGS
from config import SEARCH_MAX_RESULTS


def web_search(query: str) -> str:
    """Search the web via DuckDuckGo. Returns formatted results or an error string."""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=SEARCH_MAX_RESULTS))
        if not results:
            return "no results found"
        lines = []
        for r in results:
            title = r.get("title", "")
            snippet = r.get("body", "")[:200]
            url = r.get("href", "")
            lines.append(f"{title} — {snippet}\n{url}")
        return "\n\n".join(lines)
    except Exception as e:
        return f"search failed: {type(e).__name__}: {e}"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/test_tools.py::test_web_search_returns_formatted_results tests/test_tools.py::test_web_search_empty_results tests/test_tools.py::test_web_search_handles_exception tests/test_tools.py::test_web_search_truncates_long_snippets -v
```

Expected: all 4 PASS

- [ ] **Step 5: Commit**

```bash
cd /home/pi/pi-ai && git add tools.py tests/test_tools.py && git commit -m "$(cat <<'EOF'
feat: add tools.py with web_search() via DuckDuckGo

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: tools.py — set_reminder()

**Files:**
- Modify: `tools.py`
- Modify: `tests/test_tools.py`

- [ ] **Step 1: Write failing tests**

Append to `/home/pi/pi-ai/tests/test_tools.py`:

```python
def test_set_reminder_returns_confirmation(fake_db):
    import tools
    from datetime import datetime, timedelta
    fire_at = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    result = tools.set_reminder("call mom", fire_at)
    assert "reminder set" in result


def test_set_reminder_stores_in_db(fake_db):
    import tools, db_helpers
    from datetime import datetime, timedelta
    fire_at = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    tools.set_reminder("dentist appointment", fire_at)
    # It's in the future, so not in get_due_reminders — check raw
    with db_helpers.get_conn() as conn:
        rows = conn.execute("SELECT text FROM reminders").fetchall()
    assert any("dentist" in r[0] for r in rows)


def test_set_reminder_invalid_datetime(fake_db):
    import tools
    result = tools.set_reminder("test", "not-a-datetime")
    assert "failed" in result.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/test_tools.py::test_set_reminder_returns_confirmation tests/test_tools.py::test_set_reminder_stores_in_db tests/test_tools.py::test_set_reminder_invalid_datetime -v
```

Expected: FAIL with `AttributeError: module 'tools' has no attribute 'set_reminder'`

- [ ] **Step 3: Add set_reminder() to tools.py**

Open `/home/pi/pi-ai/tools.py`. Add at the end:

```python
import db_helpers as _db


def set_reminder(text: str, fire_at: str) -> str:
    """Store a reminder in the DB. fire_at must be an ISO/SQLite datetime string."""
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(fire_at)
        _db.add_reminder(text, dt.strftime("%Y-%m-%d %H:%M:%S"))
        return f"reminder set for {dt.strftime('%H:%M')}"
    except Exception as e:
        return f"reminder failed: {type(e).__name__}: {e}"
```

- [ ] **Step 4: Run all tool tests**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/test_tools.py -v
```

Expected: all 7 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /home/pi/pi-ai && git add tools.py tests/test_tools.py && git commit -m "$(cat <<'EOF'
feat: add set_reminder() to tools.py

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: llm.py — chat_with_tools() and model param on chat()

**Files:**
- Modify: `llm.py`
- Create: `tests/test_llm_tools.py`

- [ ] **Step 1: Write failing tests**

Create `/home/pi/pi-ai/tests/test_llm_tools.py`:

```python
import json
import pytest
from unittest.mock import MagicMock


def _make_text_completion(content):
    """Build a mock Groq completion that returns a direct text reply."""
    choice = MagicMock()
    choice.finish_reason = "stop"
    choice.message.content = content
    choice.message.tool_calls = None
    completion = MagicMock()
    completion.choices = [choice]
    return completion


def _make_tool_completion(tool_name, args_dict, call_id="call_abc"):
    """Build a mock Groq completion that returns a tool call."""
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = tool_name
    tc.function.arguments = json.dumps(args_dict)

    choice = MagicMock()
    choice.finish_reason = "tool_calls"
    choice.message.content = None
    choice.message.tool_calls = [tc]

    completion = MagicMock()
    completion.choices = [choice]
    return completion


def test_chat_with_tools_text_response(monkeypatch):
    import llm
    monkeypatch.setattr(
        llm._client.chat.completions, "create",
        lambda **kw: _make_text_completion("yeah sounds good")
    )
    text, tool_name, tool_args, tool_call_id = llm.chat_with_tools(
        [{"role": "user", "content": "hey"}], tools=[]
    )
    assert text == "yeah sounds good"
    assert tool_name is None
    assert tool_args is None
    assert tool_call_id is None


def test_chat_with_tools_tool_call_response(monkeypatch):
    import llm
    monkeypatch.setattr(
        llm._client.chat.completions, "create",
        lambda **kw: _make_tool_completion("web_search", {"query": "weather cluj"}, "call_x1")
    )
    text, tool_name, tool_args, tool_call_id = llm.chat_with_tools(
        [{"role": "user", "content": "weather?"}], tools=[]
    )
    assert text is None
    assert tool_name == "web_search"
    assert tool_args == {"query": "weather cluj"}
    assert tool_call_id == "call_x1"


def test_chat_with_tools_returns_none_tuple_on_error(monkeypatch):
    import llm

    def raise_err(**kw):
        raise RuntimeError("api down")

    monkeypatch.setattr(llm._client.chat.completions, "create", raise_err)
    text, tool_name, tool_args, tool_call_id = llm.chat_with_tools(
        [{"role": "user", "content": "test"}], tools=[]
    )
    assert text is None
    assert tool_name is None
    assert tool_args is None
    assert tool_call_id is None


def test_chat_with_tools_uses_model_override(monkeypatch):
    import llm

    captured = {}

    def fake_create(**kw):
        captured["model"] = kw.get("model")
        return _make_text_completion("ok")

    monkeypatch.setattr(llm._client.chat.completions, "create", fake_create)
    llm.chat_with_tools(
        [{"role": "user", "content": "test"}],
        tools=[],
        model="meta-llama/llama-4-scout-17b-16e-instruct"
    )
    assert captured["model"] == "meta-llama/llama-4-scout-17b-16e-instruct"


def test_chat_model_override(monkeypatch):
    import llm

    captured = {}

    def fake_create(**kw):
        captured["model"] = kw.get("model")
        choice = MagicMock()
        choice.message.content = "ok"
        comp = MagicMock()
        comp.choices = [choice]
        return comp

    monkeypatch.setattr(llm._client.chat.completions, "create", fake_create)
    llm.chat([{"role": "user", "content": "test"}], model="special-model")
    assert captured["model"] == "special-model"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/test_llm_tools.py -v
```

Expected: FAIL with `AttributeError: module 'llm' has no attribute 'chat_with_tools'`

- [ ] **Step 3: Add model param to chat() and add chat_with_tools() to llm.py**

Open `/home/pi/pi-ai/llm.py`.

**3a.** Change the `chat()` signature on line 95 from:
```python
def chat(messages, options=None, timeout=60):
```
to:
```python
def chat(messages, options=None, timeout=60, model=None):
```

**3b.** Inside `chat()`, change the `_client.chat.completions.create()` call to use `model or GROQ_MODEL`:
```python
            completion = _client.chat.completions.create(
                model=model or GROQ_MODEL,
                messages=messages,
                timeout=timeout,
                **kwargs,
            )
```

**3c.** At the end of `llm.py`, add:

```python
def chat_with_tools(messages, tools, options=None, timeout=60, model=None):
    """Call Groq with function-calling tools.

    Returns a 4-tuple:
      (text, None, None, None)          — LLM replied directly
      (None, tool_name, args, call_id)  — LLM wants to call a tool
      (None, None, None, None)          — error (caller should fall back)
    """
    caller = inspect.stack()[1].function
    if options is None:
        options = {}
    t0 = time.time()

    kwargs = {}
    if "temperature" in options:
        kwargs["temperature"] = options["temperature"]
    kwargs["max_tokens"] = options.get("num_predict") or options.get("max_tokens") or 150

    try:
        completion = _client.chat.completions.create(
            model=model or GROQ_MODEL,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            timeout=timeout,
            **kwargs,
        )
        choice = completion.choices[0]
        _log(caller, (time.time() - t0) * 1000, True)

        if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
            tc = choice.message.tool_calls[0]
            args = json.loads(tc.function.arguments)
            return None, tc.function.name, args, tc.id

        content = choice.message.content or ""
        return _clean(content), None, None, None

    except Exception as e:
        _log(caller, (time.time() - t0) * 1000, False, f"err={type(e).__name__}")
        return None, None, None, None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/test_llm_tools.py -v
```

Expected: all 5 tests PASS

- [ ] **Step 5: Run the existing test suite to check nothing broke**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/ -v --ignore=tests/test_llm_tools.py 2>&1 | tail -20
```

Expected: same number of passes as before (no regressions)

- [ ] **Step 6: Commit**

```bash
cd /home/pi/pi-ai && git add llm.py tests/test_llm_tools.py && git commit -m "$(cat <<'EOF'
feat: add chat_with_tools() to llm.py; add model= param to chat()

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: brain.py — generate_agentic_reply()

**Files:**
- Modify: `brain.py`
- Create: `tests/test_brain_agent.py`

- [ ] **Step 1: Write failing tests**

Create `/home/pi/pi-ai/tests/test_brain_agent.py`:

```python
import pytest
from unittest.mock import patch


def _stub_externals(monkeypatch):
    """Silence spotify/weather/schedule/db calls so tests stay focused."""
    import brain, db_helpers
    monkeypatch.setattr(brain.spotify_sync, "get_recent_tracks", lambda: "")
    monkeypatch.setattr(brain.weather_sync, "get_current_weather", lambda: "")
    monkeypatch.setattr(brain.uni_schedule, "get_todays_classes", lambda: "no classes today")
    monkeypatch.setattr(brain.uni_schedule, "has_class_soon", lambda: None)
    monkeypatch.setattr(db_helpers, "get_rolling_summary", lambda: None)
    monkeypatch.setattr(db_helpers, "get_recent_history_messages", lambda limit=8: [])
    monkeypatch.setattr(db_helpers, "get_user_facts", lambda limit=None: "(no specific facts stored yet)")
    monkeypatch.setattr(db_helpers, "get_latest_session_snapshot", lambda: None)
    monkeypatch.setattr(db_helpers, "get_recent_patterns", lambda: "(no new patterns observed)")


def test_generate_agentic_reply_direct_text(fake_db, monkeypatch):
    import brain
    _stub_externals(monkeypatch)
    # brain.py does `from llm import chat_with_tools` — patch at brain module level
    monkeypatch.setattr(brain, "chat_with_tools",
        lambda messages, tools, options=None, timeout=60, model=None:
            ("yeah cool", None, None, None)
    )
    result = brain.generate_agentic_reply("hey what's up")
    assert result == "yeah cool"


def test_generate_agentic_reply_tool_call_then_reply(fake_db, monkeypatch):
    import brain, tools as _tools
    _stub_externals(monkeypatch)

    monkeypatch.setattr(brain, "chat_with_tools",
        lambda messages, tools, options=None, timeout=60, model=None:
            (None, "web_search", {"query": "weather in cluj"}, "call_123")
    )
    # _tools IS the tools module — patching it patches what brain._execute_tool calls
    monkeypatch.setattr(_tools, "web_search", lambda q: "sunny 20C")
    # brain.py does `from llm import chat` — patch at brain module level
    monkeypatch.setattr(brain, "chat",
        lambda messages, options=None, timeout=60, model=None: "looks nice out"
    )
    result = brain.generate_agentic_reply("what's the weather like?")
    assert result == "looks nice out"


def test_generate_agentic_reply_falls_back_on_chat_with_tools_error(fake_db, monkeypatch):
    import brain
    _stub_externals(monkeypatch)

    monkeypatch.setattr(brain, "chat_with_tools",
        lambda messages, tools, options=None, timeout=60, model=None:
            (None, None, None, None)   # error tuple — triggers fallback
    )
    monkeypatch.setattr(brain, "generate_reply", lambda msg: "yeah?")
    result = brain.generate_agentic_reply("test")
    assert result == "yeah?"


def test_generate_agentic_reply_falls_back_on_exception(fake_db, monkeypatch):
    import brain
    _stub_externals(monkeypatch)

    def raise_err(*a, **kw):
        raise RuntimeError("groq exploded")

    monkeypatch.setattr(brain, "chat_with_tools", raise_err)
    monkeypatch.setattr(brain, "generate_reply", lambda msg: "brain hiccup")
    result = brain.generate_agentic_reply("test")
    assert result == "brain hiccup"


def test_generate_agentic_reply_vision_path(fake_db, monkeypatch):
    import brain
    _stub_externals(monkeypatch)

    captured = {}

    def fake_chat(messages, options=None, timeout=60, model=None):
        captured["model"] = model
        return "looks like a pizza lol"

    # brain.py does `from llm import chat` — patch at brain module level
    monkeypatch.setattr(brain, "chat", fake_chat)
    result = brain.generate_agentic_reply("what's this?", image_data="base64encodedstuff")
    assert result == "looks like a pizza lol"
    from config import GROQ_VISION_MODEL
    assert captured.get("model") == GROQ_VISION_MODEL
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/test_brain_agent.py -v
```

Expected: FAIL with `AttributeError: module 'brain' has no attribute 'generate_agentic_reply'`

- [ ] **Step 3: Add imports and TOOL_SCHEMAS to brain.py**

Open `/home/pi/pi-ai/brain.py`.

**3a.** Replace the existing llm import line in `brain.py` with:
```python
from llm import chat, chat_with_retry, is_acceptable, chat_with_tools, is_in_character
```

**3b.** Add `import tools as _tools` after the existing `import db_helpers` line. Then update the existing `from config import (...)` block to also include `GROQ_VISION_MODEL`:
```python
import tools as _tools
```
And the config import becomes:
```python
from config import (
    LONG_USER_MESSAGE_THRESHOLD, IN_CHARACTER_MAX_CHARS_LONG,
    GROQ_VISION_MODEL,
)
```

**3c.** Add the TOOL_SCHEMAS constant after the LLM_OPTIONS constants:

```python
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web for current information. Use when the user asks "
                "about news, facts, or anything that needs up-to-date info."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_reminder",
            "description": (
                "Set a reminder for the user. Use when they ask to be reminded "
                "of something at a specific time. Resolve natural language times "
                "(e.g. 'tonight at 10') to an ISO datetime before calling."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "What to remind the user about"},
                    "fire_at": {
                        "type": "string",
                        "description": "ISO datetime string, e.g. '2026-04-29T22:00:00'",
                    },
                },
                "required": ["text", "fire_at"],
            },
        },
    },
]
```

- [ ] **Step 4: Add the three new functions to brain.py**

Add after the `think_and_decide` function and before `generate_reply`:

```python
def _execute_tool(tool_name, tool_args):
    if tool_name == "web_search":
        return _tools.web_search(tool_args.get("query", ""))
    if tool_name == "set_reminder":
        return _tools.set_reminder(
            tool_args.get("text", ""), tool_args.get("fire_at", "")
        )
    return f"unknown tool: {tool_name}"


def _generate_vision_reply(user_message, image_data):
    system = (
        f"{PERSONA}\n\n"
        f"The user sent you an image. "
        "Describe what you see in your casual voice (one or two sentences). "
        "If the image contains something worth remembering — a schedule, a note, "
        "a place, a person — mention it naturally so it can be logged.\n"
        f"Time: {datetime.now().strftime('%A, %H:%M')} | Vibe: {get_vibe()}"
    )
    user_content = [
        {"type": "text", "text": user_message or "what's in this?"},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}},
    ]
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]
    return chat(
        messages,
        {"temperature": 0.7, "num_predict": 200},
        timeout=90,
        model=GROQ_VISION_MODEL,
    )


def _generate_tool_reply(user_message):
    current_time = datetime.now().strftime("%A, %H:%M")
    spotify_clean = _spotify_clean(spotify_sync.get_recent_tracks())
    context = _build_context_line(user_message, spotify_clean)
    classes = uni_schedule.get_todays_classes()
    upcoming = uni_schedule.has_class_soon()
    music_keywords = ["song", "music", "listening", "track", "playlist", "playing", "hear"]
    is_music = any(k in user_message.lower() for k in music_keywords)
    music_note = " Use the music data from context to answer specifically." if is_music else ""
    rolling = db_helpers.get_rolling_summary()
    is_long = len(user_message) > LONG_USER_MESSAGE_THRESHOLD
    earlier = f"\nEarlier: {rolling[:300]}" if rolling and is_long else ""
    cap = IN_CHARACTER_MAX_CHARS_LONG if is_long else None

    system = (
        f"{PERSONA}\n\n"
        f"Time: {current_time} | {classes}"
        f"{f' | {upcoming} soon' if upcoming else ''}\n"
        f"{context}{music_note}{earlier}\n"
        f"Vibe: {get_vibe()}"
    )
    history_messages = db_helpers.get_recent_history_messages(limit=8)
    messages = [{"role": "system", "content": system}]
    messages.extend(history_messages)
    messages.append({"role": "user", "content": user_message})

    text, tool_name, tool_args, tool_call_id = chat_with_tools(
        messages, TOOL_SCHEMAS, LLM_OPTIONS_CHAT, timeout=90
    )

    if tool_name:
        result = _execute_tool(tool_name, tool_args)
        messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": tool_call_id,
                "type": "function",
                "function": {"name": tool_name, "arguments": json.dumps(tool_args)},
            }],
        })
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": str(result),
        })
        text = chat(messages, LLM_OPTIONS_CHAT, timeout=90)

    if text and is_in_character(text, max_chars=cap):
        return text
    return None


def generate_agentic_reply(user_message, image_data=None):
    try:
        if image_data:
            reply = _generate_vision_reply(user_message, image_data)
        else:
            reply = _generate_tool_reply(user_message)
        if reply:
            return reply
    except Exception as e:
        _log.error(f"generate_agentic_reply failed: {type(e).__name__}: {e}", exc_info=True)
    return generate_reply(user_message)
```

- [ ] **Step 5: Add `import json` to brain.py imports** (needed for `json.dumps` in tool call injection)

At the top of `/home/pi/pi-ai/brain.py`, add `import json` after `import random`:

```python
import json
import random
```

- [ ] **Step 6: Run the new tests**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/test_brain_agent.py -v
```

Expected: all 5 tests PASS

- [ ] **Step 7: Run the full suite to check for regressions**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/ -v 2>&1 | tail -20
```

Expected: no new failures

- [ ] **Step 8: Commit**

```bash
cd /home/pi/pi-ai && git add brain.py tests/test_brain_agent.py && git commit -m "$(cat <<'EOF'
feat: add generate_agentic_reply() with tool-calling and vision paths

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: bot.py — handle_photo() and wire generate_agentic_reply

**Files:**
- Modify: `bot.py`
- Modify: `tests/test_bot_handler.py`
- Create: `tests/test_photo_handler.py`

- [ ] **Step 1: Write failing photo handler tests**

Create `/home/pi/pi-ai/tests/test_photo_handler.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_handle_photo_calls_vision_reply(fake_db, monkeypatch):
    import bot, brain

    photo_mock = MagicMock()
    photo_mock.file_id = "file123"

    update = MagicMock()
    update.message.chat_id = 123
    update.message.photo = [photo_mock]
    update.message.caption = "what's this?"
    update.message.reply_text = AsyncMock()

    ctx = MagicMock()
    mock_file = MagicMock()
    mock_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"fakeimgbytes"))
    ctx.bot.get_file = AsyncMock(return_value=mock_file)
    ctx.bot.send_chat_action = AsyncMock()

    captured = {}

    def fake_agentic(user_message, image_data=None):
        captured["msg"] = user_message
        captured["has_image"] = image_data is not None
        return "looks like a pizza lol"

    monkeypatch.setattr(brain, "generate_agentic_reply", fake_agentic)
    monkeypatch.setattr(bot, "_ALLOWED_CHAT_ID", 123)

    await bot.handle_photo(update, ctx)

    assert captured.get("has_image") is True
    assert captured.get("msg") == "what's this?"
    update.message.reply_text.assert_called_once_with("looks like a pizza lol")


@pytest.mark.asyncio
async def test_handle_photo_uses_fallback_on_download_error(fake_db, monkeypatch):
    import bot

    photo_mock = MagicMock()
    photo_mock.file_id = "file999"

    update = MagicMock()
    update.message.chat_id = 123
    update.message.photo = [photo_mock]
    update.message.caption = ""
    update.message.reply_text = AsyncMock()

    ctx = MagicMock()
    ctx.bot.get_file = AsyncMock(side_effect=RuntimeError("download failed"))
    ctx.bot.send_chat_action = AsyncMock()

    monkeypatch.setattr(bot, "_ALLOWED_CHAT_ID", 123)

    await bot.handle_photo(update, ctx)

    # Must still reply with something (fallback)
    update.message.reply_text.assert_called_once()
    reply = update.message.reply_text.call_args[0][0]
    assert reply and reply.strip()


@pytest.mark.asyncio
async def test_handle_photo_rejected_from_wrong_chat(fake_db, monkeypatch):
    import bot

    update = MagicMock()
    update.message.chat_id = 999
    update.message.reply_text = AsyncMock()

    ctx = MagicMock()
    monkeypatch.setattr(bot, "_ALLOWED_CHAT_ID", 123)

    await bot.handle_photo(update, ctx)
    update.message.reply_text.assert_not_called()
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/test_photo_handler.py -v
```

Expected: FAIL with `AttributeError: module 'bot' has no attribute 'handle_photo'`

- [ ] **Step 3: Add handle_photo() to bot.py**

Open `/home/pi/pi-ai/bot.py`. Add `import base64` at the top (after existing imports).

Then add the `handle_photo` function after `handle_message`:

```python
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    chat_id = update.message.chat_id
    caption = update.message.caption or ""
    await context.bot.send_chat_action(chat_id=chat_id, action='typing')

    try:
        file = await context.bot.get_file(update.message.photo[-1].file_id)
        image_bytes = await file.download_as_bytearray()
        image_data = base64.b64encode(bytes(image_bytes)).decode('utf-8')
    except Exception as e:
        _log.error(f"photo download failed: {e}")
        await update.message.reply_text(random.choice(IN_CHARACTER_FALLBACKS))
        return

    db_helpers.log_message('user', f"[photo]{': ' + caption if caption else ''}")

    try:
        ai_reply = brain.generate_agentic_reply(caption, image_data=image_data)
    except Exception as e:
        _log.error(f"vision reply failed: {e}", exc_info=True)
        ai_reply = random.choice(IN_CHARACTER_FALLBACKS)

    if not ai_reply or not ai_reply.strip():
        ai_reply = random.choice(IN_CHARACTER_FALLBACKS)

    db_helpers.log_message('ai', ai_reply)
    try:
        await update.message.reply_text(ai_reply)
    except Exception as e:
        _log.error(f"reply_text failed: {e}", exc_info=True)

    threading.Thread(target=llm_facts.extract_and_store_facts, daemon=True).start()
```

- [ ] **Step 4: Switch handle_message to call generate_agentic_reply**

In `/home/pi/pi-ai/bot.py`, find `handle_message`. Change:

```python
        ai_reply = brain.generate_reply(user_msg)
    except Exception as e:
        _log.error(f"brain.generate_reply failed: {e}", exc_info=True)
        ai_reply = "brain hiccup, try again in a sec"
```

To:

```python
        ai_reply = brain.generate_agentic_reply(user_msg)
    except Exception as e:
        _log.error(f"brain.generate_agentic_reply failed: {e}", exc_info=True)
        ai_reply = "brain hiccup, try again in a sec"
```

Also update the log message on the empty-reply guard from `"generate_reply returned empty"` to `"generate_agentic_reply returned empty"`.

- [ ] **Step 5: Register handle_photo in the app builder at the bottom of bot.py**

Find the `app.add_handler(MessageHandler(...))` line in `bot.py` and add the photo handler after it:

```python
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))
```

- [ ] **Step 6: Update test_bot_handler.py to patch generate_agentic_reply**

Open `/home/pi/pi-ai/tests/test_bot_handler.py`. Replace all occurrences of:
- `"bot.brain.generate_reply"` → `"bot.brain.generate_agentic_reply"`

(Three patches need updating across the three async tests.)

- [ ] **Step 7: Run all bot-related tests**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/test_bot_handler.py tests/test_photo_handler.py -v
```

Expected: all tests PASS

- [ ] **Step 8: Run full suite**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/ -v 2>&1 | tail -20
```

Expected: no new failures

- [ ] **Step 9: Commit**

```bash
cd /home/pi/pi-ai && git add bot.py tests/test_bot_handler.py tests/test_photo_handler.py && git commit -m "$(cat <<'EOF'
feat: add handle_photo(), wire generate_agentic_reply in handle_message

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: bot.py — /remind command

**Files:**
- Modify: `bot.py`
- Create: `tests/test_remind_command.py`

- [ ] **Step 1: Write failing tests**

Create `/home/pi/pi-ai/tests/test_remind_command.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_cmd_remind_valid_time_sets_reminder(fake_db, monkeypatch):
    import bot, db_helpers

    update = MagicMock()
    update.message.chat_id = 123
    update.message.reply_text = AsyncMock()

    ctx = MagicMock()
    ctx.args = ["22:00", "call", "mom"]

    monkeypatch.setattr(bot, "_ALLOWED_CHAT_ID", 123)
    await bot.cmd_remind(update, ctx)

    reply = update.message.reply_text.call_args[0][0]
    assert "reminder set" in reply


@pytest.mark.asyncio
async def test_cmd_remind_past_time_schedules_tomorrow(fake_db, monkeypatch):
    import bot, db_helpers
    from datetime import datetime

    # Use 00:01 — guaranteed to have passed today
    update = MagicMock()
    update.message.chat_id = 123
    update.message.reply_text = AsyncMock()

    ctx = MagicMock()
    ctx.args = ["00:01", "early", "bird"]

    monkeypatch.setattr(bot, "_ALLOWED_CHAT_ID", 123)
    await bot.cmd_remind(update, ctx)

    with db_helpers.get_conn() as conn:
        rows = conn.execute("SELECT fire_at FROM reminders").fetchall()
    assert len(rows) == 1
    from datetime import datetime
    fire = datetime.fromisoformat(rows[0][0])
    assert fire > datetime.now()


@pytest.mark.asyncio
async def test_cmd_remind_bad_format_returns_usage(fake_db, monkeypatch):
    import bot

    update = MagicMock()
    update.message.chat_id = 123
    update.message.reply_text = AsyncMock()

    ctx = MagicMock()
    ctx.args = ["tenpm", "do something"]

    monkeypatch.setattr(bot, "_ALLOWED_CHAT_ID", 123)
    await bot.cmd_remind(update, ctx)

    reply = update.message.reply_text.call_args[0][0]
    assert "HH:MM" in reply


@pytest.mark.asyncio
async def test_cmd_remind_no_args_returns_usage(fake_db, monkeypatch):
    import bot

    update = MagicMock()
    update.message.chat_id = 123
    update.message.reply_text = AsyncMock()

    ctx = MagicMock()
    ctx.args = []

    monkeypatch.setattr(bot, "_ALLOWED_CHAT_ID", 123)
    await bot.cmd_remind(update, ctx)

    reply = update.message.reply_text.call_args[0][0]
    assert "usage" in reply.lower()
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/test_remind_command.py -v
```

Expected: FAIL with `AttributeError: module 'bot' has no attribute 'cmd_remind'`

- [ ] **Step 3: Add cmd_remind() to bot.py**

Open `/home/pi/pi-ai/bot.py`. Add after `cmd_note`:

```python
async def cmd_remind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text("usage: /remind HH:MM <text>")
        return
    time_str = args[0]
    text = " ".join(args[1:]).strip()
    from datetime import datetime, timedelta
    from tools import set_reminder
    try:
        hour, minute = map(int, time_str.split(":"))
        now = datetime.now()
        fire_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if fire_at <= now:
            fire_at += timedelta(days=1)
        result = set_reminder(text, fire_at.isoformat())
        await update.message.reply_text(result)
    except (ValueError, AttributeError):
        await update.message.reply_text(
            "couldn't parse time — use HH:MM format, e.g. /remind 22:00 call mom"
        )
```

- [ ] **Step 4: Register the command in the app builder**

In the app builder section at the bottom of `bot.py`, add:

```python
    app.add_handler(CommandHandler("remind", cmd_remind))
```

Also add `/remind HH:MM <text> — set a reminder` to the `cmd_help` message body.

- [ ] **Step 5: Run all remind tests**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/test_remind_command.py -v
```

Expected: all 4 PASS

- [ ] **Step 6: Run full suite**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/ -v 2>&1 | tail -20
```

Expected: no new failures

- [ ] **Step 7: Commit**

```bash
cd /home/pi/pi-ai && git add bot.py tests/test_remind_command.py && git commit -m "$(cat <<'EOF'
feat: add /remind HH:MM command to bot.py

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: triggers.py — free_reasoning_trigger() replacing pattern_surface and open_thread

**Files:**
- Modify: `triggers.py`
- Modify: `tests/test_triggers.py`

- [ ] **Step 1: Write failing tests for free_reasoning_trigger**

Open `/home/pi/pi-ai/tests/test_triggers.py`. Append the following (do not remove existing tests yet):

```python
def test_free_reasoning_trigger_skipped_by_probability(fake_db, monkeypatch):
    import triggers
    monkeypatch.setattr(triggers.random, "random", lambda: 0.99)
    ok, _ = triggers.free_reasoning_trigger()
    assert ok is False


def test_free_reasoning_trigger_returns_silence(fake_db, monkeypatch):
    import triggers, llm
    monkeypatch.setattr(triggers.random, "random", lambda: 0.0)
    monkeypatch.setattr(llm, "chat", lambda messages, options=None, timeout=60: "SILENCE")
    result = triggers.free_reasoning_trigger()
    assert result[0] is False


def test_free_reasoning_trigger_returns_context_string(fake_db, monkeypatch):
    import triggers, llm
    monkeypatch.setattr(triggers.random, "random", lambda: 0.0)
    monkeypatch.setattr(
        llm, "chat",
        lambda messages, options=None, timeout=60: "user mentioned guitar 3 days ago"
    )
    result = triggers.free_reasoning_trigger()
    assert result[0] is True
    assert result[1] == "user mentioned guitar 3 days ago"
    assert result[2].startswith("free_reasoning_")


def test_free_reasoning_trigger_dedup(fake_db, monkeypatch):
    import triggers, llm, db_helpers
    from datetime import datetime
    monkeypatch.setattr(triggers.random, "random", lambda: 0.0)
    trigger_key = f"free_reasoning_{datetime.now().strftime('%Y-%m-%d')}"
    db_helpers.mark_proactive_attempted("free_reasoning", trigger_key)
    monkeypatch.setattr(
        llm, "chat",
        lambda messages, options=None, timeout=60: "something interesting"
    )
    result = triggers.free_reasoning_trigger()
    assert result[0] is False


def test_free_reasoning_trigger_handles_llm_exception(fake_db, monkeypatch):
    import triggers, llm
    monkeypatch.setattr(triggers.random, "random", lambda: 0.0)

    def raise_err(*a, **kw):
        raise RuntimeError("groq down")

    monkeypatch.setattr(llm, "chat", raise_err)
    result = triggers.free_reasoning_trigger()
    assert result[0] is False
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/test_triggers.py::test_free_reasoning_trigger_skipped_by_probability tests/test_triggers.py::test_free_reasoning_trigger_returns_silence tests/test_triggers.py::test_free_reasoning_trigger_returns_context_string -v
```

Expected: FAIL with `AttributeError: module 'triggers' has no attribute 'free_reasoning_trigger'`

- [ ] **Step 3: Add free_reasoning_trigger() to triggers.py**

Open `/home/pi/pi-ai/triggers.py`. Add the following after `open_thread_trigger` and before `ALL_TRIGGERS`:

```python
def free_reasoning_trigger():
    """LLM-driven proactive: survey the user's recent week and decide what to surface.
    Replaces pattern_surface + open_thread with a single context-aware judgment."""
    if random.random() > PATTERN_TRIGGER_PROBABILITY:
        return False, ""

    trigger_key = f"free_reasoning_{datetime.now().strftime('%Y-%m-%d')}"
    if db_helpers.was_proactive_attempted_today('free_reasoning', trigger_key):
        return False, ""

    signals = db_helpers.get_daily_signals(days=7)
    signal_text = "\n".join(
        f"{s['date']}: mood={s['mood'] or '?'} energy={s['energy'] or '?'} topics={s['main_topics'] or '?'}"
        for s in signals
    ) if signals else "(no daily signals yet)"

    patterns = db_helpers.get_recent_patterns(limit=3)

    threads = db_helpers.get_open_threads(status='open')
    thread_text = "\n".join(
        f"- {t['description']} (last ref: {t['last_referenced'] or 'never'})"
        for t in threads[:3]
    ) if threads else "(no open threads)"

    summary = db_helpers.get_rolling_summary() or "(no summary)"
    last = db_helpers.get_last_ai_message()
    last_text = f"{last['text']} ({last['timestamp']})" if last else "(none)"

    from llm import chat
    from persona import get_vibe

    messages = [
        {"role": "system", "content": (
            f"Time: {datetime.now().strftime('%A %H:%M')} | Vibe: {get_vibe()}\n\n"
            f"Daily signals (last 7 days):\n{signal_text}\n\n"
            f"Recent patterns:\n{patterns}\n\n"
            f"Open threads:\n{thread_text}\n\n"
            f"Rolling summary: {summary[:300]}\n\n"
            f"Last message you sent: {last_text}\n\n"
            "You are Lache. Given the above context about the user's recent week, "
            "do you notice something specific and genuine worth bringing up right now? "
            "If yes, write a short context string (e.g. 'user mentioned wanting to "
            "learn guitar 3 days ago, hasn't brought it up since'). "
            "If there's nothing genuine to surface, reply with the single word SILENCE."
        )},
        {"role": "user", "content": "what do you notice?"},
    ]

    try:
        result = chat(messages, {"temperature": 0.7, "num_predict": 80}, timeout=60)
    except Exception:
        return False, ""

    if not result or result.strip().upper() == "SILENCE":
        return False, ""

    return True, result.strip(), trigger_key
```

- [ ] **Step 4: Update ALL_TRIGGERS — remove pattern_surface and open_thread, add free_reasoning**

In `triggers.py`, replace:

```python
ALL_TRIGGERS = [
    ('class_soon',      has_class_soon_trigger),
    ('new_artist',      new_artist_trigger),
    ('session',         session_trigger),
    ('weather_flip',    weather_flip_trigger),
    ('late_night',      late_night_trigger),
    ('pattern_surface', pattern_surface_trigger),
    ('open_thread',     open_thread_trigger),
]
```

With:

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

- [ ] **Step 5: Remove the tests for pattern_surface_trigger and open_thread_trigger from test_triggers.py**

Open `/home/pi/pi-ai/tests/test_triggers.py`. Delete these four test functions (they test functions that no longer exist in ALL_TRIGGERS and will now cause confusion):
- `test_pattern_surface_picks_recent`
- `test_pattern_surface_skipped_by_random`
- `test_open_thread_returns_thread_id_for_deferred_update`

(The functions `pattern_surface_trigger` and `open_thread_trigger` still exist in `triggers.py` — they're just no longer in `ALL_TRIGGERS`. You can leave them there or delete them; leaving them avoids breaking any external callers.)

- [ ] **Step 6: Run all trigger tests**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/test_triggers.py -v
```

Expected: all remaining tests PASS (no failures)

- [ ] **Step 7: Run full suite**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/ -v 2>&1 | tail -20
```

Expected: no failures

- [ ] **Step 8: Commit**

```bash
cd /home/pi/pi-ai && git add triggers.py tests/test_triggers.py && git commit -m "$(cat <<'EOF'
feat: add free_reasoning_trigger(); replace pattern_surface+open_thread in ALL_TRIGGERS

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: autonomy.py — reminder delivery job

**Files:**
- Modify: `autonomy.py`
- Modify: `tests/test_autonomy.py`

- [ ] **Step 1: Write failing tests**

Open `/home/pi/pi-ai/tests/test_autonomy.py`. Append:

```python
def test_deliver_reminders_sends_due_and_marks_delivered(fake_db, monkeypatch):
    from datetime import datetime, timedelta
    import db_helpers, autonomy

    fire_at = (datetime.now() - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    db_helpers.add_reminder("call mom", fire_at)

    sent_msgs = []

    def fake_send(text):
        sent_msgs.append(text)
        return True

    monkeypatch.setattr(autonomy, "send_telegram_message", fake_send)
    autonomy.deliver_reminders()

    assert len(sent_msgs) == 1
    assert "call mom" in sent_msgs[0]
    assert db_helpers.get_due_reminders() == []


def test_deliver_reminders_skips_future(fake_db, monkeypatch):
    from datetime import datetime, timedelta
    import db_helpers, autonomy

    fire_at = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    db_helpers.add_reminder("future task", fire_at)

    sent_msgs = []
    monkeypatch.setattr(autonomy, "send_telegram_message", lambda t: sent_msgs.append(t) or True)
    autonomy.deliver_reminders()

    assert len(sent_msgs) == 0


def test_deliver_reminders_caps_at_10(fake_db, monkeypatch):
    from datetime import datetime, timedelta
    import db_helpers, autonomy

    fire_at = (datetime.now() - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    for i in range(15):
        db_helpers.add_reminder(f"reminder {i}", fire_at)

    sent_msgs = []
    monkeypatch.setattr(autonomy, "send_telegram_message", lambda t: sent_msgs.append(t) or True)
    autonomy.deliver_reminders()

    assert len(sent_msgs) == 10
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/test_autonomy.py::test_deliver_reminders_sends_due_and_marks_delivered tests/test_autonomy.py::test_deliver_reminders_skips_future tests/test_autonomy.py::test_deliver_reminders_caps_at_10 -v
```

Expected: FAIL with `AttributeError: module 'autonomy' has no attribute 'deliver_reminders'`

- [ ] **Step 3: Add deliver_reminders() to autonomy.py**

Open `/home/pi/pi-ai/autonomy.py`. After the `retry_undelivered` function, add:

```python
def deliver_reminders():
    """Fire any due reminders via Telegram and mark them delivered."""
    due = db_helpers.get_due_reminders()
    for row in due[:10]:
        sent = send_telegram_message(f"reminder: {row['text']}")
        if sent:
            db_helpers.mark_reminder_delivered(row['id'])
            logging.info(f"deliver_reminders: sent id={row['id']}")
        else:
            logging.warning(f"deliver_reminders: send failed id={row['id']}")
```

- [ ] **Step 4: Register deliver_reminders in the APScheduler**

In `autonomy.py`, find the scheduler setup block (`if __name__ == '__main__':`) and add:

```python
    _scheduler.add_job(deliver_reminders, 'interval', minutes=1)
```

alongside the existing `heartbeat`, `presence_check`, and `retry_undelivered` jobs.

- [ ] **Step 5: Run the new tests**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/test_autonomy.py -v
```

Expected: all tests PASS

- [ ] **Step 6: Run full suite**

```bash
cd /home/pi/pi-ai && venv/bin/pytest tests/ -v 2>&1 | tail -20
```

Expected: all tests PASS, no failures

- [ ] **Step 7: Commit**

```bash
cd /home/pi/pi-ai && git add autonomy.py tests/test_autonomy.py && git commit -m "$(cat <<'EOF'
feat: add deliver_reminders() APScheduler job to autonomy.py

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Deploy — restart services and smoke test

**Files:** (no code changes)

- [ ] **Step 1: Push all commits to remote**

```bash
cd /home/pi/pi-ai && git push origin master
```

- [ ] **Step 2: Run init_db to create the reminders table on the live DB**

```bash
cd /home/pi/pi-ai && venv/bin/python init_db.py
```

Expected: `Brain initialized. Memory structure created at: /home/pi/pi-ai/memory.db`

- [ ] **Step 3: Restart all three services**

```bash
sudo systemctl restart piai piaibot piaisession
```

- [ ] **Step 4: Check services are running**

```bash
sudo systemctl status piai piaibot piaisession --no-pager
```

Expected: all three show `Active: active (running)`

- [ ] **Step 5: Tail the bot log to verify clean startup**

```bash
tail -30 /home/pi/pi-ai/bot.log
```

Expected: no tracebacks, normal startup messages

- [ ] **Step 6: Smoke test — web search**

Send to Lache on Telegram: `what's the weather like in Tokyo right now?`

Expected: Lache searches and replies with something factual, not just a guess.

- [ ] **Step 7: Smoke test — reminder**

Send: `/remind 00:01 test reminder`

Expected: reply of `reminder set for 00:01` (or similar).

- [ ] **Step 8: Smoke test — photo**

Send any photo to Lache on Telegram.

Expected: Lache describes what it sees in a casual sentence.

- [ ] **Step 9: Check autonomy log for clean heartbeat**

```bash
tail -20 /home/pi/pi-ai/autonomy.log
```

Expected: heartbeat ticks with no tracebacks. If `free_reasoning` fires, it should log normally.
