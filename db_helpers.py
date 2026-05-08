import json
import sqlite3
from datetime import datetime, timedelta
from config import (
    DB_PATH, SESSION_KEEP_ROWS, SESSION_STALE_SEC,
    PATTERN_LOG_MAX_ROWS, WEEKLY_PROFILE_MAX_ROWS,
    FACT_DECAY_DAYS, FACT_DECAY_FLOOR,
)

SEED_PROFILE = "The user is a university student in Cluj-Napoca, Romania (EEST timezone)..."


def get_conn():
    return sqlite3.connect(DB_PATH, timeout=10)


def log_message(sender, message):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO conversations (sender, message) VALUES (?, ?)",
            (sender, message)
        )


def get_latest_profile():
    with get_conn() as conn:
        row = conn.execute(
            "SELECT profile_text FROM weekly_profile ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    if row:
        return row[0]
    return SEED_PROFILE


def get_last_ai_message():
    with get_conn() as conn:
        row = conn.execute(
            "SELECT message, timestamp FROM conversations WHERE sender='ai' ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
    if row:
        return {"text": row[0], "timestamp": row[1]}
    return None


def was_recently_active(minutes=90):
    with get_conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE sender='ai' AND timestamp > datetime('now', ?)",
            (f'-{int(minutes)} minutes',)
        ).fetchone()[0]
    return count > 0


def _utc_age_label(ts_str):
    try:
        ts = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")
        days = (datetime.utcnow() - ts).days
        if days == 0:
            return "today"
        if days < 7:
            return f"{days}d ago"
        if days < 30:
            return f"{days // 7}w ago"
        return f"{days // 30}mo ago"
    except Exception:
        return ""


def get_user_facts(limit=None):
    with get_conn() as conn:
        if limit:
            rows = conn.execute(
                "SELECT fact_key, fact_value, last_updated FROM user_facts ORDER BY last_updated DESC LIMIT ?",
                (limit,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT fact_key, fact_value, last_updated FROM user_facts ORDER BY last_updated DESC"
            ).fetchall()
    if not rows:
        return "(no specific facts stored yet)"
    parts = []
    for key, value, ts in rows:
        age = _utc_age_label(ts)
        parts.append(f"- {value} [{age}]" if age else f"- {value}")
    return "\n".join(parts)


def get_recent_history_messages(limit=8):
    import re
    from persona import IN_CHARACTER_FALLBACKS
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT sender, message FROM conversations ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        ).fetchall()[::-1]
    messages = []
    for sender, message in rows:
        message = re.sub(r"</?think>", "", message).strip()
        if not message:
            continue
        if sender == 'ai' and message in IN_CHARACTER_FALLBACKS:
            continue
        if sender == 'user':
            messages.append({"role": "user", "content": message})
        elif sender == 'ai':
            messages.append({"role": "assistant", "content": message})
        elif sender == 'memory':
            messages.append({"role": "user", "content": f"[context note: {message}]"})
    return messages


def get_recent_patterns(limit=3):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT pattern_description FROM pattern_log ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        ).fetchall()
    if not rows:
        return "(no new patterns observed)"
    return "\n".join(f"- {row[0]}" for row in rows)


def get_rolling_summary():
    with get_conn() as conn:
        row = conn.execute("SELECT summary FROM rolling_summary ORDER BY generated_at DESC LIMIT 1").fetchone()
    return row[0] if row else None


def get_rolling_summary_meta():
    """Returns (summary_text, generated_at_utc_str) or (None, None)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT summary, generated_at FROM rolling_summary ORDER BY generated_at DESC LIMIT 1"
        ).fetchone()
    return (row[0], row[1]) if row else (None, None)


def set_rolling_summary(text):
    with get_conn() as conn:
        conn.execute("DELETE FROM rolling_summary")
        conn.execute("INSERT INTO rolling_summary (summary) VALUES (?)", (text,))


def get_open_threads(status='open'):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, description, status, last_referenced FROM open_threads WHERE status=? ORDER BY created_at DESC",
            (status,)
        ).fetchall()
    return [{"id": r[0], "description": r[1], "status": r[2], "last_referenced": r[3]} for r in rows]


def add_open_thread(description):
    with get_conn() as conn:
        conn.execute("INSERT INTO open_threads (description) VALUES (?)", (description,))


def close_thread(thread_id):
    with get_conn() as conn:
        conn.execute("UPDATE open_threads SET status='closed' WHERE id=?", (thread_id,))


def update_thread_referenced(thread_id):
    with get_conn() as conn:
        conn.execute(
            "UPDATE open_threads SET last_referenced=datetime('now') WHERE id=?",
            (thread_id,)
        )


def get_daily_signals(days=3):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT date, mood, energy, main_topics, summary, message_count FROM daily_signal ORDER BY date DESC LIMIT ?",
            (days,)
        ).fetchall()
    return [{"date": r[0], "mood": r[1], "energy": r[2], "main_topics": r[3], "summary": r[4], "message_count": r[5]} for r in rows]


def insert_daily_signal(date, mood, energy, main_topics, summary, message_count):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO daily_signal (date, mood, energy, main_topics, summary, message_count) VALUES (?,?,?,?,?,?)",
            (date, mood, energy, main_topics, summary, message_count)
        )


def get_proactive_state(key):
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM proactive_state WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def set_proactive_state(key, value):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO proactive_state (key, value, updated_at) VALUES (?, ?, datetime('now'))",
            (key, value)
        )


def log_proactive(trigger_type, trigger_key, message_sent, delivered=1):
    """Returns the inserted row id so callers can update delivered/user_responded later."""
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO proactive_log (trigger_type, trigger_key, message_sent, delivered, attempts) VALUES (?,?,?,?,1)",
            (trigger_type, trigger_key, message_sent, delivered)
        )
        return cur.lastrowid


def update_proactive_delivered(row_id, delivered, attempts=None):
    with get_conn() as conn:
        if attempts is None:
            conn.execute(
                "UPDATE proactive_log SET delivered=? WHERE id=?",
                (delivered, row_id)
            )
        else:
            conn.execute(
                "UPDATE proactive_log SET delivered=?, attempts=? WHERE id=?",
                (delivered, attempts, row_id)
            )


def get_undelivered_proactive(limit=10):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, message_sent, attempts FROM proactive_log "
            "WHERE delivered=0 ORDER BY id ASC LIMIT ?",
            (limit,)
        ).fetchall()
    return [{"id": r[0], "message_sent": r[1], "attempts": r[2]} for r in rows]


def mark_user_response_received():
    """Called when the user sends a message. Marks any proactive sent in the
    last hour as having received a user reply. Best-effort telemetry — must
    never block the reply path, so we swallow errors (e.g. missing column on
    a DB that hasn't been re-migrated)."""
    try:
        with get_conn() as conn:
            conn.execute(
                "UPDATE proactive_log SET user_responded=1 "
                "WHERE user_responded=0 AND delivered=1 "
                "AND timestamp > datetime('now', '-1 hour')"
            )
    except Exception:
        pass


def was_trigger_fired_today(trigger_type, trigger_key):
    with get_conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM proactive_log WHERE trigger_type=? AND trigger_key=? AND timestamp >= date('now')",
            (trigger_type, trigger_key)
        ).fetchone()[0]
    return count > 0


def mark_proactive_attempted(trigger_type, trigger_key):
    """Record that a proactive trigger was attempted today, regardless of
    whether the LLM produced a sendable message."""
    state_key = f"attempted:{trigger_type}:{trigger_key}"
    today = datetime.now().strftime("%Y-%m-%d")
    set_proactive_state(state_key, today)


def was_proactive_attempted_today(trigger_type, trigger_key):
    state_key = f"attempted:{trigger_type}:{trigger_key}"
    today = datetime.now().strftime("%Y-%m-%d")
    val = get_proactive_state(state_key)
    return val == today


def log_quality_event(event_type, detail=""):
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO quality_log (event_type, detail) VALUES (?, ?)",
                (event_type, str(detail)[:500])
            )
    except Exception:
        pass


def log_presence_event(event):
    with get_conn() as conn:
        conn.execute("INSERT INTO presence_log (event) VALUES (?)", (event,))


def get_last_presence_event():
    with get_conn() as conn:
        row = conn.execute(
            "SELECT event, timestamp FROM presence_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return {"event": row[0], "timestamp": row[1]} if row else None


def log_session_snapshot(apps):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO session_snapshot (timestamp, apps) VALUES (?, ?)",
            (ts, json.dumps(apps))
        )
        conn.execute(
            "DELETE FROM session_snapshot WHERE id NOT IN "
            "(SELECT id FROM session_snapshot ORDER BY id DESC LIMIT ?)",
            (SESSION_KEEP_ROWS,)
        )


def get_latest_session_snapshot():
    with get_conn() as conn:
        row = conn.execute(
            "SELECT apps, timestamp FROM session_snapshot ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if not row:
        return None
    ts = datetime.strptime(row[1], "%Y-%m-%d %H:%M:%S")
    if (datetime.now() - ts).total_seconds() > SESSION_STALE_SEC:
        return None
    return json.loads(row[0])


def get_latest_session_snapshot_meta():
    """Returns row regardless of staleness, with age in seconds. None if empty."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT apps, timestamp FROM session_snapshot ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if not row:
        return None
    ts = datetime.strptime(row[1], "%Y-%m-%d %H:%M:%S")
    return {
        "apps": json.loads(row[0]),
        "timestamp": row[1],
        "age_sec": (datetime.now() - ts).total_seconds(),
    }


# --- Maintenance helpers ---

def decay_realtime_facts():
    """Linearly decay confidence on realtime facts older than FACT_DECAY_DAYS,
    clamped to FACT_DECAY_FLOOR. Promoted (source != 'realtime') facts are
    untouched. Run from cron / consolidation."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT fact_key, confidence, last_updated FROM user_facts "
            "WHERE source='realtime'"
        ).fetchall()
        for key, conf, last_updated in rows:
            try:
                ts = datetime.strptime(last_updated[:19], "%Y-%m-%d %H:%M:%S")
            except Exception:
                continue
            age_days = (datetime.now() - ts).days
            if age_days < FACT_DECAY_DAYS:
                continue
            # Linear decay: every FACT_DECAY_DAYS halves the distance to floor.
            steps = age_days // FACT_DECAY_DAYS
            new_conf = max(FACT_DECAY_FLOOR, conf * (0.5 ** steps))
            if abs(new_conf - conf) > 0.01:
                conn.execute(
                    "UPDATE user_facts SET confidence=? WHERE fact_key=?",
                    (new_conf, key)
                )


def prune_long_lived_tables():
    """Trim pattern_log and weekly_profile to configured caps."""
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM pattern_log WHERE id NOT IN "
            "(SELECT id FROM pattern_log ORDER BY id DESC LIMIT ?)",
            (PATTERN_LOG_MAX_ROWS,)
        )
        conn.execute(
            "DELETE FROM weekly_profile WHERE id NOT IN "
            "(SELECT id FROM weekly_profile ORDER BY id DESC LIMIT ?)",
            (WEEKLY_PROFILE_MAX_ROWS,)
        )


def add_reminder(text, fire_at):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO reminders (text, fire_at) VALUES (?, ?)",
            (text, fire_at)
        )


def get_due_reminders():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, text, fire_at FROM reminders "
            "WHERE delivered=0 AND fire_at <= datetime('now', 'localtime') "
            "ORDER BY fire_at ASC"
        ).fetchall()
    return [{"id": r[0], "text": r[1], "fire_at": r[2]} for r in rows]


def mark_reminder_delivered(reminder_id):
    with get_conn() as conn:
        conn.execute(
            "UPDATE reminders SET delivered=1 WHERE id=?",
            (reminder_id,)
        )


def log_spotify_track(artist, title, played_at):
    """Insert a track if played_at is new (dedup by timestamp). Returns True if inserted."""
    try:
        with get_conn() as conn:
            cur = conn.execute("SELECT 1 FROM spotify_tracks WHERE played_at=?", (played_at,))
            if cur.fetchone():
                return False
            conn.execute(
                "INSERT INTO spotify_tracks (artist, title, played_at) VALUES (?, ?, ?)",
                (artist, title, played_at)
            )
            return True
    except Exception:
        return False


def get_recent_spotify(limit=10):
    """Compact string of recent tracks with relative times, or None if empty."""
    try:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT artist, title, played_at FROM spotify_tracks ORDER BY played_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
        if not rows:
            return None
        parts = []
        for artist, title, played_at in rows:
            try:
                ts = datetime.strptime(played_at[:19], "%Y-%m-%d %H:%M:%S")
                mins = int((datetime.now() - ts).total_seconds() / 60)
                if mins < 60:
                    age = f"{mins}m ago"
                elif mins < 1440:
                    age = f"{mins // 60}h ago"
                else:
                    age = f"{mins // 1440}d ago"
            except Exception:
                age = ""
            parts.append(f"{artist} - {title} ({age})" if age else f"{artist} - {title}")
        return ", ".join(parts)
    except Exception:
        return None


def prune_spotify_tracks(days=30):
    """Remove tracks older than N days."""
    try:
        with get_conn() as conn:
            conn.execute(
                "DELETE FROM spotify_tracks WHERE played_at < datetime('now', ?)",
                (f'-{int(days)} days',)
        )
    except Exception:
        pass
