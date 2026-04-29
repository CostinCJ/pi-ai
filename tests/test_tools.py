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
