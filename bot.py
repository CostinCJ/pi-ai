import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes
import db_helpers
import brain
import reflection
import consolidation
import regex_facts
import weather_sync
import spotify_sync
import schedule as uni_schedule
from datetime import datetime
from config import TELEGRAM_TOKEN

_log = logging.getLogger('bot')
logging.basicConfig(filename='/home/pi/pi-ai/bot.log', level=logging.ERROR,
                    format='%(asctime)s %(name)s %(levelname)s %(message)s')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_msg = update.message.text
    chat_id = update.message.chat_id
    db_helpers.log_message('user', user_msg)
    await context.bot.send_chat_action(chat_id=chat_id, action='typing')
    try:
        ai_reply = brain.generate_reply(user_msg)
    except Exception as e:
        _log.error(f"brain.generate_reply failed: {e}", exc_info=True)
        ai_reply = "brain hiccup, try again in a sec"
    db_helpers.log_message('ai', ai_reply)
    await update.message.reply_text(ai_reply)

    for fact in regex_facts.extract_facts(user_msg):
        with db_helpers.get_conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO user_facts (fact_key, fact_value, source, confidence) VALUES (?,?,?,?)",
                (fact["key"], fact["value"], fact["source"], fact["confidence"])
            )

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    weather = weather_sync.get_current_weather()
    spotify = spotify_sync.get_recent_tracks()
    classes = uni_schedule.get_todays_classes()
    now = datetime.now().strftime("%A %H:%M")
    msg = f"alive. {now}\n{weather}\n{classes}\n{spotify}"
    await update.message.reply_text(msg)

async def cmd_reflect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("running reflection...")
    try:
        reflection.run_reflection()
        await update.message.reply_text("done. profile updated.")
    except Exception as e:
        await update.message.reply_text(f"failed: {e}")

if __name__ == '__main__':
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("reflect", cmd_reflect))
    app.run_polling()
