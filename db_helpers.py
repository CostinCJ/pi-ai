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

def get_user_facts():
    with get_conn() as conn:
        rows = conn.execute("SELECT fact_key, fact_value FROM user_facts").fetchall()
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
