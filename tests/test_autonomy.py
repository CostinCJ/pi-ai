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
    assert "casual" in msgs[0]["content"].lower()
    assert "no metaphors" in msgs[0]["content"].lower() or "no poetry" in msgs[0]["content"].lower()
    assert msgs[1]["role"] == "user"
    assert "Architects" in msgs[1]["content"]
