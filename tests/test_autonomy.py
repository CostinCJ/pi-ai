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
