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
