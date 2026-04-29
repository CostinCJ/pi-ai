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
