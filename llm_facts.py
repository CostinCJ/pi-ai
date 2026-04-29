import logging
import db_helpers
from llm import chat_json

_log = logging.getLogger('llm_facts')

_PROMPT = """\
Extract personal facts about the USER from this conversation excerpt.

Rules:
- Only extract facts about the USER, never about Lache (the AI)
- Only lasting facts — things that will still be true next week
- Reject anything temporary: "is tired", "went out today", "is coding right now"
- Be conservative: no fact is better than a wrong or vague one
- Keys: short snake_case, under 40 chars
- Values: concise, under 80 chars

Good examples: plays guitar, studies CS at UBB Cluj, plays League of Legends, owns a guitar amp
Bad examples: is tired, went out today, had a long day, is coding, is bored

Conversation:
{convo}

Reply as JSON only:
{{"facts": [{{"key": "example_key", "value": "example value", "confidence": 0.85}}]}}
If nothing worth keeping: {{"facts": []}}"""


def extract_and_store_facts():
    """LLM-based fact extraction over the last 15 messages. Fire-and-forget — never raises."""
    try:
        rows = db_helpers.get_recent_history_messages(limit=15)
        if len(rows) < 2:
            return

        convo = "\n".join(
            f"{'USER' if m['role'] == 'user' else 'LACHE'}: {m['content']}"
            for m in rows
        )

        messages = [
            {"role": "system", "content": "You are a precise JSON extractor. Output only valid JSON, nothing else."},
            {"role": "user", "content": _PROMPT.format(convo=convo)},
        ]

        data = chat_json(messages, {"temperature": 0.1, "max_tokens": 250}, schema_keys=["facts"])
        if not data:
            return

        facts = data.get("facts", [])
        if not facts:
            return

        stored = 0
        with db_helpers.get_conn() as conn:
            for fact in facts:
                key = str(fact.get("key", "")).strip()[:50]
                value = str(fact.get("value", "")).strip()[:150]
                confidence = float(fact.get("confidence", 0.75))
                if len(key) < 2 or not value:
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO user_facts "
                    "(fact_key, fact_value, source, confidence) VALUES (?,?,?,?)",
                    (key, value, "llm_realtime", confidence)
                )
                stored += 1

        if stored:
            _log.info(f"llm_facts: stored {stored} new fact(s)")

    except Exception as e:
        _log.warning(f"llm_facts: {type(e).__name__}: {e}")
