import sqlite3
import os

DB_PATH = '/home/pi/pi-ai/memory.db'

def setup_database():
    # Connect to SQLite (creates the file if it doesn't exist)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. Conversations: The raw dialogue history
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        sender TEXT NOT NULL, -- 'user' or 'ai'
        message TEXT NOT NULL
    )
    ''')

    # 2. User Facts: Concrete things it knows about you (Key/Value store)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_facts (
        fact_key TEXT PRIMARY KEY,
        fact_value TEXT NOT NULL,
        last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # 3. Pattern Log: Inferred habits and behavioral drifts
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS pattern_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        pattern_description TEXT NOT NULL
    )
    ''')

    # 4. Weekly Profile: The AI's synthesized understanding of you
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS weekly_profile (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        profile_text TEXT NOT NULL
    )
    ''')

    # 5. Daily Signal: Mood, energy, topics, and summary for each day
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS daily_signal (
        date TEXT PRIMARY KEY,
        mood TEXT,
        energy INTEGER,
        main_topics TEXT,
        summary TEXT,
        message_count INTEGER
    )
    ''')

    # 6. Rolling Summary: Latest synthesized summary of ongoing interests
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS rolling_summary (
        id INTEGER PRIMARY KEY,
        generated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        summary TEXT
    )
    ''')

    # 7. Open Threads: Unresolved topics or questions to follow up on
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS open_threads (
        id INTEGER PRIMARY KEY,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        description TEXT,
        status TEXT DEFAULT 'open',
        last_referenced DATETIME
    )
    ''')

    # 8. Proactive State: Key-value store for proactive engagement state
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS proactive_state (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # 9. Proactive Log: History of proactive messages and their triggers
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS proactive_log (
        id INTEGER PRIMARY KEY,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        trigger_type TEXT,
        trigger_key TEXT,
        message_sent TEXT
    )
    ''')

    # 10. Quality Log: Telemetry for retry/fallback events
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS quality_log (
            id INTEGER PRIMARY KEY,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            event_type TEXT,
            detail TEXT
        )
    """)

    # Add column migrations for user_facts
    for sql in [
        "ALTER TABLE user_facts ADD COLUMN source TEXT DEFAULT 'unknown'",
        "ALTER TABLE user_facts ADD COLUMN confidence REAL DEFAULT 1.0",
        "ALTER TABLE user_facts ADD COLUMN times_referenced INTEGER DEFAULT 0",
    ]:
        try:
            cursor.execute(sql)
        except sqlite3.OperationalError:
            pass  # column already exists

    conn.commit()
    conn.close()
    print(f"Brain initialized. Memory structure created at: {os.path.abspath(DB_PATH)}")

if __name__ == '__main__':
    setup_database()
