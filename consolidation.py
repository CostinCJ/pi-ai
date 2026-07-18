import logging
import os
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
import db_helpers
from llm import chat_json
from config import LOG_DIR, APP_LOG_MAX_BYTES, APP_LOG_BACKUPS

_handler = RotatingFileHandler(
    os.path.join(str(LOG_DIR), 'consolidation.log'),
    maxBytes=APP_LOG_MAX_BYTES, backupCount=APP_LOG_BACKUPS,
)
_handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
logging.basicConfig(level=logging.INFO, handlers=[_handler])


def _retry(fn, attempts=3, base_delay=10, label="op"):
    """Retry with exponential backoff on exception OR None result (chat_json
    signals failure by returning None, it never raises)."""
    for i in range(attempts):
        try:
            result = fn()
            if result is not None:
                return result
            err = "returned None (LLM call or JSON parse failed — see llm.log)"
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
        wait = base_delay * (2 ** i)
        logging.error(f"{label} attempt {i+1}/{attempts} failed: {err}; sleeping {wait}s")
        if i + 1 < attempts:
            time.sleep(wait)
    return None


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
        {"role": "system", "content": "You are a precise JSON validator. Output only valid JSON."},
        {"role": "user", "content": f"""Review these candidate facts extracted from conversation.
Keep only clear, permanent personal facts. Reject anything vague or temporary.

Candidates:
{candidate_text}

Reply as JSON: {{"keep": ["fact1", "fact2"], "reject": ["fact3"]}}"""}
    ]
    data = _retry(
        lambda: chat_json(messages, {"temperature": 0.1, "num_predict": 400}, schema_keys=["keep"], timeout=60),
        label="validate_realtime_facts"
    )
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

    # Days where only Lache spoke are a monologue, not a conversation.
    # Summarizing them produced fiction ("AI mentioned a recent meeting") that
    # fed back into rolling_summary and made Lache hallucinate a human life.
    # Compact the AI rows (keep the last few for last-sent context) and stop.
    user_count = sum(1 for r in rows if r[1] == 'user')
    if user_count == 0:
        keep_ids = {r[0] for r in rows if r[1] == 'ai'}
        keep_ids = set(sorted(keep_ids)[-5:])
        drop_ids = [r[0] for r in rows if r[0] not in keep_ids]
        if drop_ids:
            with db_helpers.get_conn() as conn:
                conn.execute(
                    f"DELETE FROM conversations WHERE id IN ({','.join('?' * len(drop_ids))})",
                    drop_ids
                )
        logging.info(f"No user messages today — AI monologue compacted ({len(drop_ids)} rows), no summarization.")
        db_helpers.decay_realtime_facts()
        db_helpers.prune_long_lived_tables()
        return

    log_text = "".join(f"{r[1].upper()}: {r[2]}\n" for r in rows)
    row_ids = [r[0] for r in rows]
    message_count = len(rows)

    prompt = f"""Analyze today's conversation between the User and AI (Lache).

Lines starting with AI are Lache's own outgoing messages — never treat them as
events in anyone's life or as things the user said. Only USER lines carry facts.

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
8. Note 0-2 recurring behavioral patterns visible today (e.g. "user messages at night", "user codes before exams"). Empty list if none.

Output strictly as JSON:
{{
    "facts": {{"short_key": "Specific fact description"}},
    "summary": "2-sentence mood and topic summary.",
    "mood": "neutral",
    "energy": 3,
    "main_topics": ["topic1", "topic2"],
    "open_threads": ["wants to fix the guitar amp"],
    "rolling_summary": "Short rolling summary of what was discussed today.",
    "patterns": ["short behavioral pattern or empty list"]
}}"""

    messages = [
        {"role": "system", "content": "You are a precise JSON extractor. Output only valid JSON."},
        {"role": "user", "content": prompt}
    ]
    # num_predict required: llm.chat() defaults to max_tokens=150, which risks
    # truncating this multi-key JSON (it's what silently killed reflection.py).
    data = _retry(
        lambda: chat_json(messages, {"temperature": 0.2, "format": "json", "num_predict": 900},
                          schema_keys=["facts", "summary", "patterns"], timeout=120),
        label="consolidation_main"
    )
    if data is None:
        logging.error("Consolidation LLM call failed after retries. Skipping.")
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

        with db_helpers.get_conn() as conn:
            rows = conn.execute(
                "SELECT pattern_description FROM pattern_log ORDER BY id DESC LIMIT 20"
            ).fetchall()
            existing = {r[0] for r in rows}
            new_count = 0
            for pattern in data.get("patterns", []):
                if pattern and pattern.strip() and pattern.strip() not in existing:
                    conn.execute(
                        "INSERT INTO pattern_log (pattern_description) VALUES (?)",
                        (pattern.strip(),),
                    )
                    existing.add(pattern.strip())
                    new_count += 1

        logging.info(f"Daily consolidation complete. Facts: {len(data.get('facts', {}))} Mood: {data.get('mood')} Patterns: {new_count}")
    except Exception as e:
        logging.error(f"Consolidation DB write failed: {e}", exc_info=True)

    _validate_realtime_facts()
    db_helpers.decay_realtime_facts()
    db_helpers.prune_long_lived_tables()

    # Keep the WAL from growing unbounded (it was 5x the DB size at one point).
    try:
        with db_helpers.get_conn() as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception as e:
        logging.warning(f"WAL checkpoint failed: {e}")


if __name__ == '__main__':
    extract_facts_and_summarize()
