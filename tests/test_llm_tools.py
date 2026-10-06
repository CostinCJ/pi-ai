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


def test_chat_with_tools_passes_tool_choice(monkeypatch):
    import llm
    captured = {}
    monkeypatch.setattr(
        llm._client.chat.completions, "create",
        lambda **kw: captured.update(kw) or _make_text_completion("ok")
    )
    forced = {"type": "function", "function": {"name": "set_reminder"}}
    llm.chat_with_tools([{"role": "user", "content": "x"}], [], tool_choice=forced)
    assert captured["tool_choice"] == forced
