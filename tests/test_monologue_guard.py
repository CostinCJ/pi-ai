import db_helpers
import consolidation
import reflection


def test_consolidation_skips_ai_only_days(fake_db, fake_ollama):
    for i in range(8):
        db_helpers.log_message("ai", f"proactive ping {i}")

    consolidation.extract_facts_and_summarize()

    # No LLM call happened, no fiction was written.
    assert fake_ollama["calls"] == []
    with db_helpers.get_conn() as conn:
        memory_rows = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE sender='memory'"
        ).fetchone()[0]
        signals = conn.execute("SELECT COUNT(*) FROM daily_signal").fetchone()[0]
        ai_rows = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE sender='ai'"
        ).fetchone()[0]
    assert memory_rows == 0
    assert signals == 0
    assert ai_rows == 5  # compacted to the last 5 for last-sent context


def test_consolidation_runs_when_user_spoke(fake_db, fake_ollama):
    db_helpers.log_message("user", "finished the OOP lab, went well")
    for i in range(4):
        db_helpers.log_message("ai", f"reply {i}")
    fake_ollama["queue"].append(
        '{"facts": {}, "summary": "s", "mood": "neutral", "energy": 3,'
        ' "main_topics": [], "open_threads": [], "rolling_summary": "", "patterns": []}'
    )

    consolidation.extract_facts_and_summarize()

    assert len(fake_ollama["calls"]) >= 1


def test_retry_retries_on_none_result(monkeypatch):
    monkeypatch.setattr(reflection.time, "sleep", lambda s: None)
    attempts = []

    def flaky():
        attempts.append(1)
        return {"ok": True} if len(attempts) == 2 else None

    assert reflection._retry(flaky, attempts=3, label="test") == {"ok": True}
    assert len(attempts) == 2


def test_retry_gives_up_after_attempts(monkeypatch):
    monkeypatch.setattr(reflection.time, "sleep", lambda s: None)
    assert reflection._retry(lambda: None, attempts=3, label="test") is None
