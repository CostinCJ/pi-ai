import logging
from datetime import datetime
from config import DB_PATH
import db_helpers
from llm import chat_json

logging.basicConfig(filename='/home/pi/pi-ai/consolidation.log', level=logging.INFO,
                    format='%(asctime)s %(message)s')


def _validate_realtime_facts():
    with db_helpers.get_conn() as conn:
        candidates = conn.execute(
            "SELECT fact_key, fact_value FROM user_facts "
            "WHERE source='realtime' AND confidence=0.6 "
            "AND last_updated >= datetime('now', '-1 day')"
        ).fetchall()
    if not candidates:
        return
    candidate_text = "\n".join(f"- {r[1]}" for r in candidates)
    messages = [
        {"role": "system", "content": "/no_think\nYou are a precise JSON validator. Output only valid JSON."},
        {"role": "user", "content": f"""Review these candidate facts extracted from conversation.
Keep only clear, permanent personal facts. Reject anything vague or temporary.

Candidates:
{candidate_text}

Reply as JSON: {{"keep": ["fact1", "fact2"], "reject": ["fact3"]}}"""}
    ]
    data = chat_json(messages, {"temperature": 0.1}, schema_keys=["keep"], timeout=60)
    if not data:
        return
    keep_set = set(data.get("keep", []))
    with db_helpers.get_conn() as conn:
        for key, val in candidates:
            if val in keep_set or any(val in k for k in keep_set):
                conn.execute(
                    "UPDATE user_facts SET confidence=0.95, source='consolidation' WHERE fact_key=?",
                    (key,)
                )
            else:
                conn.execute("DELETE FROM user_facts WHERE fact_key=? AND confidence=0.6", (key,))


def extract_facts_and_summarize():
    with db_helpers.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, sender, message FROM conversations "
            "WHERE timestamp >= datetime('now', '-1 day') AND sender != 'memory'"
        ).fetchall()

    if len(rows) < 4:
        logging.info("Not enough messages to consolidate. Skipping.")
        return

    log_text = "".join(f"{r[1].upper()}: {r[2]}\n" for r in rows)
    row_ids = [r[0] for r in rows]
    message_count = len(rows)

    prompt = f"""Analyze today's conversation between the User and AI (Lache).

[TODAY'S CONVERSATION]
{log_text}

TASK:
1. Extract permanent facts the user stated about themselves (owns items, preferences, identity).
   Good: "owns a Fender Stratocaster", "hates the OS lab professor", "plays jungle main in League"
   Bad: "was tired today", "seemed stressed" — too vague or temporary
2. Write a 2-sentence summary capturing mood and main topics.
3. Pick the overall mood: low / neutral / up / wired / social
4. Rate energy level 1-5 (1=exhausted, 5=very energetic)
5. List up to 3 main topics discussed.
6. List any open threads (things user expressed intent about that weren't resolved).
7. Write a ~250 char rolling summary of the full conversation arc for future context.

Output strictly as JSON:
{{
    "facts": {{"short_key": "Specific fact description"}},
    "summary": "2-sentence mood and topic summary.",
    "mood": "neutral",
    "energy": 3,
    "main_topics": ["topic1", "topic2"],
    "open_threads": ["wants to fix the guitar amp"],
    "rolling_summary": "Short rolling summary of what was discussed today."
}}"""

    messages = [
        {"role": "system", "content": "/no_think\nYou are a precise JSON extractor. Output only valid JSON."},
        {"role": "user", "content": prompt}
    ]
    data = chat_json(messages, {"temperature": 0.2, "format": "json"},
                     schema_keys=["facts", "summary"], timeout=120)
    if data is None:
        logging.error("Consolidation LLM call failed or returned invalid JSON. Skipping.")
        return

    today = datetime.now().strftime('%Y-%m-%d')
    try:
        with db_helpers.get_conn() as conn:
            for key, val in data.get("facts", {}).items():
                conn.execute(
                    "INSERT OR REPLACE INTO user_facts (fact_key, fact_value, source, confidence) VALUES (?,?,?,?)",
                    (key, val, 'consolidation', 0.95)
                )
            conn.execute(
                "INSERT INTO conversations (sender, message) VALUES ('memory', ?)",
                (f"[PREVIOUSLY CONTEXT] {data.get('summary', '')}",)
            )
            conn.execute(
                f"DELETE FROM conversations WHERE id IN ({','.join('?' * len(row_ids))})",
                row_ids
            )

        topics_csv = ",".join(data.get("main_topics", []))
        db_helpers.insert_daily_signal(
            today,
            data.get("mood", "neutral"),
            data.get("energy", 3),
            topics_csv,
            data.get("summary", ""),
            message_count
        )

        for thread_desc in data.get("open_threads", []):
            if thread_desc:
                db_helpers.add_open_thread(thread_desc)

        rolling = data.get("rolling_summary", "")
        if rolling:
            db_helpers.set_rolling_summary(rolling)

        logging.info(f"Daily consolidation complete. Facts: {len(data.get('facts', {}))} Mood: {data.get('mood')}")
    except Exception as e:
        logging.error(f"Consolidation DB write failed: {e}", exc_info=True)

    _validate_realtime_facts()


if __name__ == '__main__':
    extract_facts_and_summarize()
