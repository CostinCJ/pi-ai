import html
import logging
import re

import requests

from config import BRAVE_API_KEY, SEARCH_MAX_RESULTS
import db_helpers as _db

try:
    from ddgs import DDGS
except ImportError:  # pragma: no cover - compatibility for older installs
    from duckduckgo_search import DDGS

_log = logging.getLogger("tools")

SEARCH_TIMEOUT_SEC = 5


def _format_results(results):
    if not results:
        return "no results found"
    lines = []
    for title, snippet, url in results:
        lines.append(f"{title} — {snippet[:200]}\n{url}")
    return "\n\n".join(lines)


def _web_search_brave(query: str):
    """Search via Brave Search API. Raises on any failure — caller falls back to ddgs."""
    r = requests.get(
        "https://api.search.brave.com/res/v1/web/search",
        headers={"Accept": "application/json", "X-Subscription-Token": BRAVE_API_KEY},
        params={"q": query, "count": SEARCH_MAX_RESULTS},
        timeout=SEARCH_TIMEOUT_SEC,
    )
    r.raise_for_status()
    results = r.json().get("web", {}).get("results", [])
    return [
        (
            item.get("title", ""),
            html.unescape(re.sub("<[^<]+?>", "", item.get("description", ""))),
            item.get("url", ""),
        )
        for item in results
    ]


def _web_search_ddgs(query: str):
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=SEARCH_MAX_RESULTS, timeout=SEARCH_TIMEOUT_SEC))
    return [(r.get("title", ""), r.get("body", ""), r.get("href", "")) for r in results]


def web_search(query: str) -> str:
    """Search the web. Brave Search API if BRAVE_API_KEY is set, falling back to
    DuckDuckGo (ddgs) on missing key or any Brave failure."""
    if BRAVE_API_KEY:
        try:
            return _format_results(_web_search_brave(query))
        except Exception as e:
            _log.warning(f"brave search failed, falling back to ddgs: {type(e).__name__}: {e}")
    try:
        return _format_results(_web_search_ddgs(query))
    except Exception as e:
        return f"search failed: {type(e).__name__}: {e}"


def set_reminder(text: str, fire_at: str) -> str:
    """Store a reminder in the DB. fire_at must be an ISO/SQLite datetime
    string; aware datetimes (e.g. a trailing Z from the LLM) are converted to
    naive localtime, the reminders-table convention."""
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(fire_at)
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        _db.add_reminder(text, dt.strftime("%Y-%m-%d %H:%M:%S"))
        when = dt.strftime("%H:%M") if dt.date() == datetime.now().date() \
            else dt.strftime("%d %b %H:%M")
        return f"reminder set for {when}"
    except Exception as e:
        return f"reminder failed: {type(e).__name__}: {e}"
