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

    conn.commit()
    conn.close()
    print(f"Brain initialized. Memory structure created at: {os.path.abspath(DB_PATH)}")

if __name__ == '__main__':
    setup_database()
