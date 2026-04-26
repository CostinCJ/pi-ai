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


def test_generate_reply_passes_through_good_output(fake_db):
    with patch("brain.chat_with_retry", return_value=("yeah, going where?", True)):
        reply = brain.generate_reply("yeah i m going out")
    assert reply == "yeah, going where?"
