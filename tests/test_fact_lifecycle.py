"""Realtime-fact lifecycle: llm_facts writes source='llm_realtime', and the
consolidation validate/promote/decay pipeline must operate on that source —
it was silently filtering on the retired regex-extractor format
(source='realtime' AND confidence=0.6) and touching nothing."""
import db_helpers
import consolidation
import llm_facts


def _seed_fact(key, value, source, conf, age_days=0):
    with db_helpers.get_conn() as conn:
        conn.execute(
            "INSERT INTO user_facts (fact_key, fact_value, source, confidence, last_updated) "
            "VALUES (?,?,?,?, datetime('now', ?))",
            (key, value, source, conf, f"-{age_days} days"),
        )


def _fact(key):
    with db_helpers.get_conn() as conn:
        row = conn.execute(
            "SELECT fact_value, source, confidence FROM user_facts WHERE fact_key=?",
            (key,),
        ).fetchone()
    return row


def test_validate_promotes_kept_llm_realtime_fact(fake_db, monkeypatch):
    _seed_fact("games", "plays League of Legends", "llm_realtime", 0.8)
    monkeypatch.setattr(
        consolidation, "chat_json",
        lambda *a, **k: {"keep": ["plays League of Legends"], "reject": []},
    )
    consolidation._validate_realtime_facts()
    value, source, conf = _fact("games")
    assert source == "consolidation"
    assert conf == 0.95


def test_validate_deletes_rejected_llm_realtime_fact(fake_db, monkeypatch):
    _seed_fact("mood_now", "was tired today", "llm_realtime", 0.75)
    monkeypatch.setattr(
        consolidation, "chat_json",
        lambda *a, **k: {"keep": [], "reject": ["was tired today"]},
    )
    consolidation._validate_realtime_facts()
    assert _fact("mood_now") is None


def test_llm_facts_updates_existing_realtime_fact(fake_db, monkeypatch):
    _seed_fact("relationship", "single", "llm_realtime", 0.8)
    monkeypatch.setattr(
        db_helpers, "get_recent_history_messages",
        lambda limit=15: [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}],
    )
    monkeypatch.setattr(
        llm_facts, "chat_json",
        lambda *a, **k: {"facts": [{"key": "relationship", "value": "dating maria", "confidence": 0.9}]},
    )
    llm_facts.extract_and_store_facts()
    value, source, conf = _fact("relationship")
    assert value == "dating maria"


def test_llm_facts_never_overwrites_promoted_fact(fake_db, monkeypatch):
    _seed_fact("studies", "CS at UBB Cluj", "consolidation", 0.95)
    monkeypatch.setattr(
        db_helpers, "get_recent_history_messages",
        lambda limit=15: [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}],
    )
    monkeypatch.setattr(
        llm_facts, "chat_json",
        lambda *a, **k: {"facts": [{"key": "studies", "value": "dropped out", "confidence": 0.9}]},
    )
    llm_facts.extract_and_store_facts()
    value, source, conf = _fact("studies")
    assert value == "CS at UBB Cluj"
    assert source == "consolidation"


def test_decay_applies_to_llm_realtime_source(fake_db):
    _seed_fact("old_fact", "owns a bike", "llm_realtime", 0.8, age_days=35)
    db_helpers.decay_realtime_facts()
    _, _, conf = _fact("old_fact")
    assert conf == 0.4


def test_decay_does_not_compound_on_repeated_runs(fake_db):
    _seed_fact("old_fact", "owns a bike", "llm_realtime", 0.8, age_days=35)
    db_helpers.decay_realtime_facts()
    db_helpers.decay_realtime_facts()
    db_helpers.decay_realtime_facts()
    _, _, conf = _fact("old_fact")
    assert conf == 0.4, "each run must halve per elapsed period, not per invocation"


def test_decay_leaves_promoted_facts_alone(fake_db):
    _seed_fact("studies", "CS at UBB Cluj", "consolidation", 0.95, age_days=90)
    db_helpers.decay_realtime_facts()
    _, _, conf = _fact("studies")
    assert conf == 0.95
