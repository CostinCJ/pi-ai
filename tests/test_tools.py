import pytest
import requests


def _fake_ddgs(fake_results):
    class FakeDDGS:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def text(self, query, max_results, timeout=None): return iter(fake_results)
    return FakeDDGS


def _fake_brave_response(results, status=200):
    class FakeResponse:
        status_code = status
        def raise_for_status(self):
            if status >= 400:
                raise requests.HTTPError(f"{status} error")
        def json(self):
            return {"web": {"results": results}}
    return FakeResponse()


def test_web_search_no_key_uses_ddgs_directly(monkeypatch):
    import tools

    monkeypatch.setattr(tools, "BRAVE_API_KEY", "")
    fake_results = [
        {"title": "Cluj Weather", "body": "Sunny and 22°C", "href": "https://example.com/weather"},
    ]
    monkeypatch.setattr(tools, "DDGS", _fake_ddgs(fake_results))
    result = tools.web_search("weather in cluj")

    assert "Cluj Weather" in result
    assert "Sunny and 22°C" in result
    assert "https://example.com/weather" in result


def test_web_search_empty_results(monkeypatch):
    import tools

    monkeypatch.setattr(tools, "BRAVE_API_KEY", "")
    monkeypatch.setattr(tools, "DDGS", _fake_ddgs([]))
    result = tools.web_search("nothing found")
    assert "no results" in result


def test_web_search_handles_exception(monkeypatch):
    import tools

    class BrokenDDGS:
        def __enter__(self): raise RuntimeError("network error")
        def __exit__(self, *a): pass

    monkeypatch.setattr(tools, "BRAVE_API_KEY", "")
    monkeypatch.setattr(tools, "DDGS", BrokenDDGS)
    result = tools.web_search("anything")
    assert "failed" in result.lower()


def test_web_search_truncates_long_snippets(monkeypatch):
    import tools

    fake_results = [{"title": "T", "body": "x" * 500, "href": "https://example.com"}]
    monkeypatch.setattr(tools, "BRAVE_API_KEY", "")
    monkeypatch.setattr(tools, "DDGS", _fake_ddgs(fake_results))
    result = tools.web_search("test")
    # body is truncated to 200 chars in format string
    assert len(result) < 1000


def test_web_search_uses_brave_when_key_set(monkeypatch):
    import tools

    monkeypatch.setattr(tools, "BRAVE_API_KEY", "fake-key")
    fake_results = [
        {"title": "Cluj Weather", "description": "Sunny and <strong>22°C</strong>", "url": "https://example.com/weather"},
    ]
    monkeypatch.setattr(requests, "get", lambda *a, **kw: _fake_brave_response(fake_results))
    result = tools.web_search("weather in cluj")

    assert "Cluj Weather" in result
    # HTML tags stripped from Brave's highlighted snippet
    assert "<strong>" not in result
    assert "Sunny and 22°C" in result
    assert "https://example.com/weather" in result


def test_web_search_falls_back_to_ddgs_on_brave_error(monkeypatch):
    import tools

    monkeypatch.setattr(tools, "BRAVE_API_KEY", "fake-key")
    monkeypatch.setattr(requests, "get", lambda *a, **kw: _fake_brave_response([], status=500))
    fake_results = [{"title": "Fallback", "body": "from ddgs", "href": "https://example.com"}]
    monkeypatch.setattr(tools, "DDGS", _fake_ddgs(fake_results))

    result = tools.web_search("weather in cluj")
    assert "Fallback" in result
    assert "from ddgs" in result


def test_web_search_falls_back_to_ddgs_on_brave_timeout(monkeypatch):
    import tools

    def raise_timeout(*a, **kw):
        raise requests.Timeout("timed out")

    monkeypatch.setattr(tools, "BRAVE_API_KEY", "fake-key")
    monkeypatch.setattr(requests, "get", raise_timeout)
    fake_results = [{"title": "Fallback", "body": "from ddgs", "href": "https://example.com"}]
    monkeypatch.setattr(tools, "DDGS", _fake_ddgs(fake_results))

    result = tools.web_search("weather in cluj")
    assert "Fallback" in result


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


def test_set_reminder_converts_aware_datetime_to_local(fake_db):
    import tools, db_helpers
    from datetime import datetime, timedelta, timezone
    utc_dt = (datetime.now(timezone.utc) + timedelta(hours=2)).replace(microsecond=0)
    tools.set_reminder("tz test", utc_dt.isoformat())
    with db_helpers.get_conn() as conn:
        row = conn.execute(
            "SELECT fire_at FROM reminders WHERE text='tz test'"
        ).fetchone()
    expected = utc_dt.astimezone().replace(tzinfo=None)
    assert row[0] == expected.strftime("%Y-%m-%d %H:%M:%S")


def test_set_reminder_confirmation_includes_date_when_not_today(fake_db):
    import tools
    from datetime import datetime, timedelta
    tomorrow = (datetime.now() + timedelta(days=1)).replace(microsecond=0)
    result = tools.set_reminder("call mom", tomorrow.isoformat())
    assert tomorrow.strftime("%d") in result, f"no date hint in: {result}"
