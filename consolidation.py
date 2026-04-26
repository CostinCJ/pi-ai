import sqlite3
import requests
import json
from datetime import datetime
from config import DB_PATH, OLLAMA_URL, MODEL
import db_helpers

def extract_facts_and_summarize():
    with db_helpers.get_conn() as conn:
        # Get messages from the last 24 hours that haven't been summarized
        rows = conn.execute(
            "SELECT id, sender, message FROM conversations WHERE timestamp >= datetime('now', '-1 day') AND sender != 'memory'"
        ).fetchall()
        
    if len(rows) < 4:
        print("Not enough messages to consolidate. Skipping.")
        return

    log_text = "".join(f"{r[1].upper()}: {r[2]}\n" for r in rows)
    row_ids = [r[0] for r in rows]

    prompt = f"""Analyze today's conversation between the User and AI (Lache).

[TODAY'S CONVERSATION]
{log_text}

TASK:
1. Extract permanent facts the user stated about themselves. Be specific and concrete.
   Good facts: "owns a Fender Stratocaster", "hates the OS lab professor", "quit vaping in March", "plays jungle main in League"
   Bad facts: "was tired today", "seemed stressed", "talked about music" — too vague or temporary
   If no clear permanent facts were stated, return empty object.
2. Write a 2-3 sentence summary capturing the mood and main topics — not just what was said but how the conversation felt.

Output strictly as a JSON object with this exact format:
{{
    "facts": {{"short_key_name": "Specific fact description"}},
    "summary": "Summary including mood and topics discussed."
}}"""

    try:
        response = requests.post(OLLAMA_URL, json={
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.2}
        })
        
        data = json.loads(response.json().get("response", "").strip())
        
        with db_helpers.get_conn() as conn:
            # 1. Insert Facts
            for key, val in data.get("facts", {}).items():
                conn.execute(
                    "INSERT OR REPLACE INTO user_facts (fact_key, fact_value) VALUES (?, ?)", 
                    (key, val)
                )
            
            # 2. Insert Summary as a 'memory' message
            conn.execute(
                "INSERT INTO conversations (sender, message) VALUES ('memory', ?)",
                (f"[PREVIOUSLY CONTEXT] {data.get('summary', '')}",)
            )
            
            # 3. Delete the raw messages to keep DB lean
            conn.execute(f"DELETE FROM conversations WHERE id IN ({','.join('?' * len(row_ids))})", row_ids)
            
        print("Daily consolidation complete.")
    except Exception as e:
        print(f"Consolidation failed: {e}")

if __name__ == '__main__':
    extract_facts_and_summarize()
