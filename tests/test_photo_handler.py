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
