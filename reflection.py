from datetime import datetime
import db_helpers
from llm import chat_json

MAX_LOG_CHARS = 6000

def get_weekly_logs():
    with db_helpers.get_conn() as conn:
        rows = conn.execute(
            "SELECT timestamp, sender, message FROM conversations "
            "WHERE timestamp >= datetime('now', '-7 days') "
            "ORDER BY timestamp DESC LIMIT 200"
        ).fetchall()[::-1]
    if not rows:
        return None
    text = "".join(f"[{row[0]}] {row[1].upper()}: {row[2]}\n" for row in rows)
    return text[-MAX_LOG_CHARS:] if len(text) > MAX_LOG_CHARS else text

def save_reflection(profile_text, patterns):
    with db_helpers.get_conn() as conn:
        conn.execute("INSERT INTO weekly_profile (profile_text) VALUES (?)", (profile_text,))
        existing = {r[0] for r in conn.execute("SELECT pattern_description FROM pattern_log").fetchall()}
        for pattern in patterns:
            if pattern not in existing:
                conn.execute("INSERT INTO pattern_log (pattern_description) VALUES (?)", (pattern,))

def run_reflection():
    logs = get_weekly_logs()
    if not logs:
        print("No logs this week. Skipping reflection.")
        return

    current_profile = db_helpers.get_latest_profile()

    prompt = f"""You are a personal AI analyzing your interaction logs from the past week.

[CURRENT BASELINE PROFILE]
{current_profile}

[NEW WEEKLY LOGS]
{logs}

TASK:
1. Rewrite the baseline profile incorporating any new overarching habits, mood shifts, or routine changes observed in the logs.
2. Identify 1-3 specific recurring behavioral patterns (e.g., "Always texts after midnight", "Plays League on Thursdays").

Output strictly as a JSON object with this exact format, and nothing else:
{{
    "updated_profile": "Third-person observational log...",
    "patterns": ["pattern 1", "pattern 2"]
}}"""

    messages = [
        {"role": "system", "content": "/no_think\nYou are a precise JSON extractor. Output only valid JSON."},
        {"role": "user", "content": prompt}
    ]
    data = chat_json(messages, {"temperature": 0.3, "format": "json"}, schema_keys=["updated_profile", "patterns"], timeout=180)
    if data is None:
        print("Reflection LLM call failed. Skipping.")
        return

    save_reflection(data.get("updated_profile", current_profile), data.get("patterns", []))
    print("Reflection and patterns saved successfully.")

if __name__ == '__main__':
    run_reflection()
