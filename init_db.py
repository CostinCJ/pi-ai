import sqlite3
import os
from config import DB_PATH


def setup_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Concurrency: WAL allows multiple readers + one writer without
    # journal-rollback contention. Set once; persists per-database.
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.OperationalError:
        pass

    # 1. Conversations
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        sender TEXT NOT NULL,
        message TEXT NOT NULL
    )
    ''')

    # 2. User Facts
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_facts (
        fact_key TEXT PRIMARY KEY,
        fact_value TEXT NOT NULL,
        last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # 3. Pattern Log
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS pattern_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        pattern_description TEXT NOT NULL
    )
    ''')

    # 4. Weekly Profile
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS weekly_profile (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        profile_text TEXT NOT NULL
    )
    ''')

    # 5. Daily Signal
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

    # 6. Rolling Summary
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS rolling_summary (
        id INTEGER PRIMARY KEY,
        generated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        summary TEXT
    )
    ''')

    # 7. Open Threads
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS open_threads (
        id INTEGER PRIMARY KEY,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        description TEXT,
        status TEXT DEFAULT 'open',
        last_referenced DATETIME
    )
    ''')

    # 8. Proactive State
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS proactive_state (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # 9. Proactive Log
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS proactive_log (
        id INTEGER PRIMARY KEY,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        trigger_type TEXT,
        trigger_key TEXT,
        message_sent TEXT,
        delivered INTEGER DEFAULT 1,
        attempts INTEGER DEFAULT 1,
        user_responded INTEGER DEFAULT 0
    )
    ''')

    # 10. Quality Log
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS quality_log (
            id INTEGER PRIMARY KEY,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            event_type TEXT,
            detail TEXT
        )
    """)

    # 11. Presence Log
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS presence_log (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            event     TEXT NOT NULL
        )
    """)

    # 12. Session Snapshot
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS session_snapshot (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            apps      TEXT NOT NULL
        )
    """)

    # 13. Spotify Tracks
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS spotify_tracks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        artist TEXT NOT NULL,
        title TEXT NOT NULL,
        played_at TEXT NOT NULL UNIQUE,
        logged_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    cursor.execute('''
    CREATE INDEX IF NOT EXISTS idx_spotify_tracks_played_at
    ON spotify_tracks(played_at DESC)
    ''')

    # 14. Reminders
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            text       TEXT NOT NULL,
            fire_at    TEXT NOT NULL,
            delivered  INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # Migrations on user_facts
    for sql in [
        "ALTER TABLE user_facts ADD COLUMN source TEXT DEFAULT 'unknown'",
        "ALTER TABLE user_facts ADD COLUMN confidence REAL DEFAULT 1.0",
        "ALTER TABLE user_facts ADD COLUMN times_referenced INTEGER DEFAULT 0",
    ]:
        try:
            cursor.execute(sql)
        except sqlite3.OperationalError:
            pass

    # Migrations on proactive_log (delivered/attempts/user_responded for retry+telemetry)
    for sql in [
        "ALTER TABLE proactive_log ADD COLUMN delivered INTEGER DEFAULT 1",
        "ALTER TABLE proactive_log ADD COLUMN attempts INTEGER DEFAULT 1",
        "ALTER TABLE proactive_log ADD COLUMN user_responded INTEGER DEFAULT 0",
    ]:
        try:
            cursor.execute(sql)
        except sqlite3.OperationalError:
            pass

    conn.commit()
    conn.close()
    print(f"Brain initialized. Memory structure created at: {os.path.abspath(DB_PATH)}")


if __name__ == '__main__':
    setup_database()
