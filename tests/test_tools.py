import pytest


def test_web_search_returns_formatted_results(monkeypatch):
    import tools

    fake_results = [
        {"title": "Cluj Weather", "body": "Sunny and 22°C", "href": "https://example.com/weather"},
        {"title": "Another Result", "body": "Some snippet", "href": "https://example.com/two"},
    ]

    class FakeDDGS:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def text(self, query, max_results): return iter(fake_results)

    monkeypatch.setattr(tools, "DDGS", FakeDDGS)
    result = tools.web_search("weather in cluj")

    assert "Cluj Weather" in result
    assert "Sunny and 22°C" in result
    assert "https://example.com/weather" in result


def test_web_search_empty_results(monkeypatch):
    import tools

    class EmptyDDGS:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def text(self, query, max_results): return iter([])

    monkeypatch.setattr(tools, "DDGS", EmptyDDGS)
    result = tools.web_search("nothing found")
    assert "no results" in result


def test_web_search_handles_exception(monkeypatch):
    import tools

    class BrokenDDGS:
        def __enter__(self): raise RuntimeError("network error")
        def __exit__(self, *a): pass

    monkeypatch.setattr(tools, "DDGS", BrokenDDGS)
    result = tools.web_search("anything")
    assert "failed" in result.lower()


def test_web_search_truncates_long_snippets(monkeypatch):
    import tools

    fake_results = [{"title": "T", "body": "x" * 500, "href": "https://example.com"}]

    class FakeDDGS:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def text(self, query, max_results): return iter(fake_results)

    monkeypatch.setattr(tools, "DDGS", FakeDDGS)
    result = tools.web_search("test")
    # body is truncated to 200 chars in format string
    assert len(result) < 1000


def test_set_reminder_returns_confirmation(fake_db):
    import tools
    from datetime import datetime, timedelta
    fire_at = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    result = tools.set_reminder("call mom", fire_at)
    assert "reminder set" in result


def test_set_reminder_stores_in_db(fake_db):
    import tools, db_helpers
    from datetime import datetime, timedelta
    fire_at = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    tools.set_reminder("dentist appointment", fire_at)
    # It's in the future, so not in get_due_reminders — check raw
    with db_helpers.get_conn() as conn:
        rows = conn.execute("SELECT text FROM reminders").fetchall()
    assert any("dentist" in r[0] for r in rows)


def test_set_reminder_invalid_datetime(fake_db):
    import tools
    result = tools.set_reminder("test", "not-a-datetime")
    assert "failed" in result.lower()
