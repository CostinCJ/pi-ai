import sqlite3
from datetime import datetime, timedelta
from config import DB_PATH

SEED_PROFILE = "The user is a university student in Cluj-Napoca, Romania (EEST timezone)..."

# Added timeout=10 to handle concurrent writes gracefully
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
    cutoff = (datetime.now() - timedelta(minutes=minutes)).strftime('%Y-%m-%d %H:%M:%S')
    with get_conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE sender='ai' AND timestamp > ?",
            (cutoff,)
        ).fetchone()[0]
    return count > 0

# --- NEW FUNCTIONS FOR BRAIN.PY ---

def get_user_facts(limit=None):
    with get_conn() as conn:
        if limit:
            rows = conn.execute(
                "SELECT fact_key, fact_value FROM user_facts ORDER BY last_updated DESC LIMIT ?",
                (limit,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT fact_key, fact_value FROM user_facts ORDER BY last_updated DESC"
            ).fetchall()
    if not rows:
        return "(no specific facts stored yet)"
    return "\n".join(f"- {row[1]}" for row in rows)

def get_recent_history_messages(limit=8):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT sender, message FROM conversations ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        ).fetchall()[::-1]
    messages = []
    for sender, message in rows:
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

# --- NEW FUNCTIONS FOR DAILY_SIGNAL, ROLLING_SUMMARY, OPEN_THREADS, PROACTIVE ---

def get_rolling_summary():
    with get_conn() as conn:
        row = conn.execute("SELECT summary FROM rolling_summary ORDER BY generated_at DESC LIMIT 1").fetchone()
    return row[0] if row else None

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

def log_proactive(trigger_type, trigger_key, message_sent):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO proactive_log (trigger_type, trigger_key, message_sent) VALUES (?,?,?)",
            (trigger_type, trigger_key, message_sent)
        )

def was_trigger_fired_today(trigger_type, trigger_key):
    with get_conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM proactive_log WHERE trigger_type=? AND trigger_key=? AND timestamp >= date('now')",
            (trigger_type, trigger_key)
        ).fetchone()[0]
    return count > 0


def mark_proactive_attempted(trigger_type, trigger_key):
    """Record that a proactive trigger was attempted today, regardless of
    whether the LLM produced a sendable message. Used for dedup so a
    SILENCE response still cools the trigger down for the rest of the day."""
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
