from unittest.mock import patch
import consolidation
import db_helpers


def test_extract_facts_includes_patterns(fake_db, monkeypatch):
    # Seed enough messages to pass the min-4 gate
    with db_helpers.get_conn() as conn:
        for sender, msg in [
            ("user", "am stat pana la 3 dimineata sa codez"),
            ("lache", "ar trebui sa dormi mai mult"),
            ("user", "stiu dar am proiect la OS"),
            ("lache", "inteleg, keep going"),
        ]:
            conn.execute(
                "INSERT INTO conversations (sender, message) VALUES (?, ?)",
                (sender, msg),
            )

    import llm
    monkeypatch.setattr(
        consolidation, "chat_json",
        lambda messages, options=None, schema_keys=None, timeout=60: {
            "facts": {},
            "summary": "user coded late.",
            "mood": "neutral",
            "energy": 3,
            "main_topics": ["coding"],
            "open_threads": [],
            "rolling_summary": "coded late.",
            "patterns": ["user codes late at night"],
        },
    )
    monkeypatch.setattr(consolidation, "_validate_realtime_facts", lambda: None)
    monkeypatch.setattr(db_helpers, "decay_realtime_facts", lambda: None)
    monkeypatch.setattr(db_helpers, "prune_long_lived_tables", lambda: None)

    consolidation.extract_facts_and_summarize()

    patterns = db_helpers.get_recent_patterns(limit=20)
    assert "user codes late at night" in patterns
