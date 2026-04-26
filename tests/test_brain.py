from unittest.mock import patch
import brain


def test_generate_reply_never_returns_empty(fake_db):
    """If chat_with_retry fails validation (whitespace), generate_reply must
    produce a non-empty in-character fallback string."""
    with patch("brain.chat_with_retry", return_value=("   ", False)):
        reply = brain.generate_reply("how are you")
    assert reply.strip() != ""
    assert reply != "..."


def test_generate_reply_never_returns_three_dots(fake_db):
    """If chat_with_retry fails validation (sycophantic), generate_reply must
    return an in-character fallback — never the literal '...'."""
    with patch("brain.chat_with_retry", return_value=("your playlist is a masterpiece", False)):
        reply = brain.generate_reply("how are you")
    assert reply != "..."
    assert reply.strip() != ""


def test_generate_reply_passes_through_good_output(fake_db):
    with patch("brain.chat_with_retry", return_value=("yeah, going where?", True)):
        reply = brain.generate_reply("yeah i m going out")
    assert reply == "yeah, going where?"
