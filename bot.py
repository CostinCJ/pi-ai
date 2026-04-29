import logging
import os
import random
import time as _time
from logging.handlers import RotatingFileHandler
from config import (
    TELEGRAM_TOKEN, CHAT_ID, LAPTOP_MAC, LAPTOP_TAILSCALE_IP,
    SHUTDOWN_PORT, SESSION_SHARED_SECRET, LOG_DIR,
    APP_LOG_MAX_BYTES, APP_LOG_BACKUPS,
    ECHO_OVERLAP_THRESHOLD, ECHO_MIN_USER_WORDS,
)

_log = logging.getLogger('bot')
_handler = RotatingFileHandler(
    os.path.join(str(LOG_DIR), 'bot.log'),
    maxBytes=APP_LOG_MAX_BYTES, backupCount=APP_LOG_BACKUPS,
)
_handler.setFormatter(logging.Formatter('%(asctime)s %(name)s %(levelname)s %(message)s'))
logging.basicConfig(level=logging.INFO, handlers=[_handler])
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes
import db_helpers
import brain
import threading
import reflection
import consolidation
import llm_facts
import weather_sync
import spotify_sync
import schedule as uni_schedule
from datetime import datetime, timedelta
from persona import IN_CHARACTER_FALLBACKS
from wakeonlan import send_magic_packet

_ALLOWED_CHAT_ID = int(CHAT_ID)


def _is_allowed(update: Update) -> bool:
    """Reject any chat_id outside the whitelist. Logs the rejected id once."""
    try:
        chat_id = update.message.chat_id
    except Exception:
        return False
    if chat_id != _ALLOWED_CHAT_ID:
        _log.warning(f"rejected message from unauthorized chat_id={chat_id}")
        return False
    return True


def _is_echo(ai_reply, user_msg):
    """True if the AI response is a near-copy of what the user just said.
    Skipped for short user messages where high overlap is natural."""
    user_words = {w for w in user_msg.lower().split() if len(w) > 2}
    if len(user_words) < ECHO_MIN_USER_WORDS:
        return False
    ai_words = {w for w in ai_reply.lower().split() if len(w) > 2}
    if not ai_words or not user_words:
        return False
    overlap = len(ai_words & user_words) / max(len(ai_words), len(user_words))
    return overlap > ECHO_OVERLAP_THRESHOLD


def _user_recently_repeated(current_text):
    """True if the user sent a near-duplicate of `current_text` within the
    last 5 minutes. Called AFTER the current message is logged, so skips
    the most recent row (itself). Uses id DESC for deterministic ordering."""
    with db_helpers.get_conn() as conn:
        cutoff_row = conn.execute(
            "SELECT datetime(datetime('now'), '-5 minutes')"
        ).fetchone()
        cutoff = cutoff_row[0] if cutoff_row else None
        if not cutoff:
            return False
        rows = conn.execute(
            "SELECT message FROM conversations "
            "WHERE sender='user' AND timestamp > ? "
            "ORDER BY id DESC LIMIT 4",
            (cutoff,)
        ).fetchall()
    if rows:
        rows = rows[1:]
    cur_words = {w for w in current_text.lower().split() if len(w) > 2}
    for (prev,) in rows:
        prev_words = {w for w in prev.lower().split() if len(w) > 2}
        if cur_words and prev_words and len(cur_words & prev_words) / max(len(cur_words), len(prev_words)) > 0.6:
            return True
    return False


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    user_msg = update.message.text
    chat_id = update.message.chat_id
    db_helpers.log_message('user', user_msg)
    if _user_recently_repeated(user_msg):
        db_helpers.log_quality_event("user_repeated", user_msg[:200])
    await context.bot.send_chat_action(chat_id=chat_id, action='typing')

    try:
        ai_reply = brain.generate_reply(user_msg)
    except Exception as e:
        _log.error(f"brain.generate_reply failed: {e}", exc_info=True)
        ai_reply = "brain hiccup, try again in a sec"

    if not ai_reply or not ai_reply.strip():
        _log.error("generate_reply returned empty; using last-resort fallback")
        ai_reply = random.choice(IN_CHARACTER_FALLBACKS)
    elif _is_echo(ai_reply, user_msg):
        _log.warning(f"echo detected, using fallback. ai={ai_reply!r}")
        db_helpers.log_quality_event("echo_detected", ai_reply[:200])
        ai_reply = random.choice(IN_CHARACTER_FALLBACKS)

    db_helpers.log_message('ai', ai_reply)
    db_helpers.mark_user_response_received()

    try:
        await update.message.reply_text(ai_reply)
    except Exception as e:
        _log.error(f"reply_text failed: {e}", exc_info=True)

    threading.Thread(target=llm_facts.extract_and_store_facts, daemon=True).start()


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    weather = weather_sync.get_current_weather()
    spotify = spotify_sync.get_recent_tracks()
    classes = uni_schedule.get_todays_classes()
    now = datetime.now().strftime("%A %H:%M")
    quota = _today_groq_request_count()
    daemon = _daemon_last_seen()
    msg = f"alive. {now}\n{weather}\n{classes}\n{spotify}\ngroq today: {quota} reqs\nlaptop daemon: {daemon}"
    await update.message.reply_text(msg)


async def cmd_reflect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    await update.message.reply_text("running reflection...")
    try:
        reflection.run_reflection()
        await update.message.reply_text("done. profile updated.")
    except Exception as e:
        await update.message.reply_text(f"failed: {e}")


async def cmd_consolidate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    await update.message.reply_text("running consolidation...")
    try:
        consolidation.extract_facts_and_summarize()
        await update.message.reply_text("done. facts and summary updated.")
    except Exception as e:
        await update.message.reply_text(f"failed: {e}")


async def cmd_forget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    args = context.args
    if not args:
        await update.message.reply_text("usage: /forget <key-or-substring>")
        return
    needle = " ".join(args).strip()
    with db_helpers.get_conn() as conn:
        rows = conn.execute(
            "SELECT fact_key, fact_value FROM user_facts "
            "WHERE fact_key LIKE ? OR fact_value LIKE ?",
            (f"%{needle}%", f"%{needle}%")
        ).fetchall()
    if not rows:
        await update.message.reply_text(f"no fact matches: {needle}")
        return
    if len(rows) > 1:
        listing = "\n".join(f"- {k}: {v}" for k, v in rows[:10])
        await update.message.reply_text(
            f"matches multiple keys, run /forget with the exact key:\n{listing}"
        )
        return
    key = rows[0][0]
    with db_helpers.get_conn() as conn:
        conn.execute("DELETE FROM user_facts WHERE fact_key=?", (key,))
    await update.message.reply_text(f"forgot: {key}")


async def cmd_facts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    with db_helpers.get_conn() as conn:
        rows = conn.execute(
            "SELECT fact_key, fact_value, confidence, source, last_updated "
            "FROM user_facts ORDER BY last_updated DESC"
        ).fetchall()
    if not rows:
        await update.message.reply_text("no facts stored yet.")
        return
    lines = [f"[{r[3]}:{r[2]:.0%}] {r[1]} ({r[4][:10]})" for r in rows]
    await update.message.reply_text("\n".join(lines))


async def cmd_threads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    threads = db_helpers.get_open_threads(status='open')
    if not threads:
        await update.message.reply_text("no open threads.")
        return
    lines = [
        f"[{t['id']}] {t['description']} (last ref: {t['last_referenced'] or 'never'})"
        for t in threads
    ]
    await update.message.reply_text("\n".join(lines))


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    msg = (
        "/status — current time, weather, classes, spotify, quota\n"
        "/ping — quick health probe\n"
        "/today — day summary: time, weather, classes, music, open topics\n"
        "/next — next class today with time remaining\n"
        "/week — this week's schedule (current parity)\n"
        "/laptop — what's running on your laptop right now\n"
        "/mood — last 7 days of mood/energy\n"
        "/note <text> — save a manual fact\n"
        "/export — dump everything lache knows about you\n"
        "/facts — full fact list with source and confidence\n"
        "/threads — open topics lache is tracking\n"
        "/forget <key-or-substring> — delete a stored fact\n"
        "/reflect — run weekly reflection now\n"
        "/consolidate — run daily fact extraction now\n"
        "/poweron — wake up your laptop via WoL\n"
        "/poweroff — shut down your laptop (30s grace period)\n"
        "/help — this list"
    )
    await update.message.reply_text(msg)


async def cmd_poweroff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    if not LAPTOP_TAILSCALE_IP:
        await update.message.reply_text("LAPTOP_TAILSCALE_IP not set in .env")
        return
    url = f"http://{LAPTOP_TAILSCALE_IP}:{SHUTDOWN_PORT}/shutdown"
    headers = {}
    if SESSION_SHARED_SECRET:
        headers['X-Session-Token'] = SESSION_SHARED_SECRET
    try:
        import requests as _req
        r = _req.post(url, headers=headers, timeout=8)
        if r.status_code == 200:
            await update.message.reply_text("shutdown command sent. rig going down in 30s.")
        elif r.status_code == 401:
            await update.message.reply_text("rejected — token mismatch. check SESSION_SHARED_SECRET.")
        else:
            await update.message.reply_text(f"unexpected response: {r.status_code}")
    except Exception as e:
        await update.message.reply_text(f"failed to reach laptop: {e}")


async def cmd_poweron(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    await update.message.reply_text("sending ignition sequence...")
    try:
        send_magic_packet(LAPTOP_MAC)
        await update.message.reply_text("packet sent. rig should be waking up.")
    except Exception as e:
        await update.message.reply_text(f"failed to send packet: {e}")


def _ping_groq():
    try:
        import llm
        t0 = _time.time()
        out = llm.chat(
            [{"role": "user", "content": "say 'ok'"}],
            {"temperature": 0, "num_predict": 4}, timeout=10
        )
        return f"ok ({int((_time.time()-t0)*1000)}ms)" if out else "fail"
    except Exception as e:
        return f"fail ({type(e).__name__})"


def _ping_db():
    try:
        with db_helpers.get_conn() as conn:
            conn.execute("SELECT 1").fetchone()
        return "ok"
    except Exception as e:
        return f"fail ({type(e).__name__})"


def _today_groq_request_count():
    """Counts ok/fail lines in llm.log for today. Cheap, file-only."""
    path = os.path.join(str(LOG_DIR), "llm.log")
    today = datetime.now().strftime("%Y-%m-%d")
    n = 0
    try:
        with open(path, "r") as f:
            for line in f:
                if line.startswith(today):
                    n += 1
    except FileNotFoundError:
        return 0
    except Exception:
        return -1
    return n


def _external_ok(value):
    if not value:
        return False
    return "unavailable" not in value.lower()


def _daemon_last_seen():
    snap = db_helpers.get_latest_session_snapshot_meta()
    if not snap:
        return "no data"
    age_min = int(snap["age_sec"] // 60)
    return f"{age_min}m ago" if age_min < 60 else f"{age_min // 60}h ago"


async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    groq = _ping_groq()
    db = _ping_db()
    weather = "ok" if _external_ok(weather_sync.get_current_weather()) else "fail"
    spotify = "ok" if _external_ok(spotify_sync.get_recent_tracks()) else "fail"
    daemon = _daemon_last_seen()
    await update.message.reply_text(
        f"groq: {groq}\ndb: {db}\nweather: {weather}\nspotify: {spotify}\ndaemon: {daemon}"
    )


async def cmd_mood(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    rows = db_helpers.get_daily_signals(days=7)
    if not rows:
        await update.message.reply_text("no mood data yet.")
        return
    lines = [
        f"{r['date']}: {r['mood'] or '?'} | energy {r['energy'] if r['energy'] is not None else '?'}"
        f" | {(r['main_topics'] or '')[:60]}"
        for r in rows
    ]
    moods = [r['mood'] for r in rows if r['mood']]
    drift = ""
    if moods:
        low_count = sum(1 for m in moods if m and m.lower() in ('low', 'down', 'sad', 'tired'))
        if low_count >= 4:
            drift = f"\n(heads up: {low_count}/{len(moods)} days flagged low)"
    await update.message.reply_text("\n".join(lines) + drift)


async def cmd_next(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    nxt = uni_schedule.get_next_class()
    if not nxt:
        await update.message.reply_text("no more classes today.")
        return
    now = datetime.now()
    slot_dt = now.replace(hour=nxt["start"], minute=0, second=0, microsecond=0)
    delta = slot_dt - now
    total_min = int(delta.total_seconds() // 60)
    if total_min < 60:
        when = f"{total_min}min"
    else:
        h = total_min // 60
        m = total_min % 60
        when = f"{h}h {m}min" if m else f"{h}h"
    await update.message.reply_text(
        f"{nxt['subject']} at {nxt['start']}:00 ({nxt['room']}) — in {when}"
    )


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    now = datetime.now().strftime("%A %H:%M")
    weather = weather_sync.get_current_weather()
    classes = uni_schedule.get_todays_classes()
    spotify = spotify_sync.get_recent_tracks()
    threads = db_helpers.get_open_threads(status='open')
    thread_line = ""
    if threads:
        thread_line = "\nopen topics: " + ", ".join(t['description'][:30] for t in threads[:3])
    msg = f"{now}\n{weather}\n{classes}\n{spotify}{thread_line}"
    await update.message.reply_text(msg)


async def cmd_week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    sapt1 = uni_schedule.is_sapt1()
    week_label = "săpt 1" if sapt1 else "săpt 2"
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    lines = [f"Schedule ({week_label}):"]
    for day_idx in range(5):
        slots = uni_schedule.TIMETABLE.get(day_idx, [])
        active = [s for s in slots if uni_schedule._slot_active(s, sapt1)]
        if not active:
            continue
        day_line = f"{day_names[day_idx]}: " + ", ".join(
            f"{s['subject']} {s['start']}:00 ({s['room']})" for s in active
        )
        lines.append(day_line)
    if len(lines) == 1:
        lines.append("no classes this week.")
    await update.message.reply_text("\n".join(lines))


async def cmd_laptop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    snap = db_helpers.get_latest_session_snapshot()
    meta = db_helpers.get_latest_session_snapshot_meta()
    if not snap or not meta:
        await update.message.reply_text("no session data — laptop daemon hasn't reported in.")
        return
    age_min = int(meta["age_sec"] // 60)
    age_str = f"{age_min}m ago" if age_min < 60 else f"{age_min // 60}h ago"
    lines = [f"laptop snapshot ({age_str}):"]
    for app in snap:
        lines.append(f"  {app['name']} — {app['ram_mb']}MB")
    await update.message.reply_text("\n".join(lines))


async def cmd_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    args = context.args
    if not args:
        await update.message.reply_text("usage: /note <text>")
        return
    text = " ".join(args).strip()
    key = "manual_" + text[:30].replace(" ", "_").lower()
    with db_helpers.get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_facts (fact_key, fact_value, source, confidence) "
            "VALUES (?,?,?,?)",
            (key, text, "manual", 1.0)
        )
    await update.message.reply_text(f"noted: {text}")


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    sections = []
    with db_helpers.get_conn() as conn:
        fact_rows = conn.execute(
            "SELECT fact_key, fact_value, source FROM user_facts ORDER BY last_updated DESC"
        ).fetchall()
        profile_row = conn.execute(
            "SELECT profile_text FROM weekly_profile ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    if fact_rows:
        sections.append("FACTS\n" + "\n".join(f"{r[0]}: {r[1]} [{r[2]}]" for r in fact_rows))
    patterns = db_helpers.get_recent_patterns()
    if patterns and "no new" not in patterns:
        sections.append(f"PATTERNS\n{patterns}")
    summary = db_helpers.get_rolling_summary()
    if summary:
        sections.append(f"SUMMARY\n{summary}")
    threads = db_helpers.get_open_threads(status='open')
    if threads:
        sections.append("OPEN THREADS\n" + "\n".join(f"[{t['id']}] {t['description']}" for t in threads))
    if profile_row:
        sections.append(f"WEEKLY PROFILE\n{profile_row[0]}")
    if not sections:
        await update.message.reply_text("nothing to export yet.")
        return
    export = "\n\n".join(sections)
    if len(export) > 4000:
        export = export[:4000] + "\n...(truncated)"
    await update.message.reply_text(export)


def _shutdown(signum, frame):
    _log.info(f"received signal {signum}, shutting down")
    raise SystemExit(0)


if __name__ == '__main__':
    import signal
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CommandHandler("mood", cmd_mood))
    app.add_handler(CommandHandler("reflect", cmd_reflect))
    app.add_handler(CommandHandler("consolidate", cmd_consolidate))
    app.add_handler(CommandHandler("forget", cmd_forget))
    app.add_handler(CommandHandler("facts", cmd_facts))
    app.add_handler(CommandHandler("threads", cmd_threads))
    app.add_handler(CommandHandler("next", cmd_next))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("week", cmd_week))
    app.add_handler(CommandHandler("laptop", cmd_laptop))
    app.add_handler(CommandHandler("note", cmd_note))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("poweron", cmd_poweron))
    app.add_handler(CommandHandler("poweroff", cmd_poweroff))
    app.run_polling()
