import pytest
from unittest.mock import patch


def _stub_externals(monkeypatch):
    """Silence spotify/weather/schedule/db calls so tests stay focused."""
    import brain, db_helpers
    monkeypatch.setattr(db_helpers, "get_recent_spotify", lambda limit=10: None)
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


def test_tool_reply_chains_search_then_reminder(fake_db, monkeypatch):
    import brain, db_helpers
    _stub_externals(monkeypatch)
    steps = iter([
        (None, "web_search", {"query": "current date"}, "c1"),
        (None, "set_reminder", {"text": "renew gemini", "fire_at": "2099-10-12T10:00:00"}, "c2"),
        ("ok, pinging you on the 12th", None, None, None),
    ])
    monkeypatch.setattr(brain, "chat_with_tools",
        lambda messages, tools, options=None, timeout=60, model=None: next(steps))
    monkeypatch.setattr(brain._tools, "web_search", lambda q: "6 oct 2026")
    result = brain.generate_agentic_reply("remind me on 12 october to renew gemini")
    assert result == "ok, pinging you on the 12th"
    with db_helpers.get_conn() as conn:
        rows = conn.execute("SELECT text, fire_at FROM reminders").fetchall()
    assert rows == [("renew gemini", "2099-10-12 10:00:00")]


def test_reminder_request_without_set_reminder_reports_failure(fake_db, monkeypatch):
    import brain
    _stub_externals(monkeypatch)
    monkeypatch.setattr(brain, "chat_with_tools",
        lambda messages, tools, options=None, timeout=60, model=None, tool_choice="auto":
            ("got it, i'll ping you on the 12th", None, None, None))
    result = brain.generate_agentic_reply(
        "could you remember me on 12 october to renew my gemini subscription?")
    assert "couldn't save" in result


def test_reminder_request_with_failed_set_reminder_reports_failure(fake_db, monkeypatch):
    import brain
    _stub_externals(monkeypatch)
    steps = iter([
        (None, "set_reminder", {"text": "x", "fire_at": "not a date"}, "c1"),
        ("done!", None, None, None),
    ])
    monkeypatch.setattr(brain, "chat_with_tools",
        lambda messages, tools, options=None, timeout=60, model=None: next(steps))
    result = brain.generate_agentic_reply("remind me tomorrow to call mom")
    assert "couldn't save" in result


def test_tool_reply_time_line_includes_year(fake_db, monkeypatch):
    import brain
    from datetime import datetime
    _stub_externals(monkeypatch)
    captured = {}

    def fake(messages, tools, options=None, timeout=60, model=None):
        captured["system"] = messages[0]["content"]
        return ("sure", None, None, None)

    monkeypatch.setattr(brain, "chat_with_tools", fake)
    brain.generate_agentic_reply("hey")
    assert str(datetime.now().year) in captured["system"]


def test_reminder_request_retries_with_forced_tool(fake_db, monkeypatch):
    import brain, db_helpers
    _stub_externals(monkeypatch)
    seen = []

    def fake(messages, tools, options=None, timeout=60, model=None, tool_choice="auto"):
        seen.append(tool_choice)
        if tool_choice == "auto":
            return ("got it, i'll ping you", None, None, None)
        return (None, "set_reminder", {"text": "renew gemini", "fire_at": "2099-10-12T10:00:00"}, "c1")

    monkeypatch.setattr(brain, "chat_with_tools", fake)
    monkeypatch.setattr(brain, "chat",
        lambda messages, options=None, timeout=60, model=None: "set for the 12th")
    result = brain.generate_agentic_reply("remind me on 12 october to renew gemini")
    assert result == "set for the 12th"
    assert seen[-1] == {"type": "function", "function": {"name": "set_reminder"}}
    with db_helpers.get_conn() as conn:
        assert conn.execute("SELECT count(*) FROM reminders").fetchone()[0] == 1
