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
