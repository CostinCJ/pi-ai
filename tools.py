from duckduckgo_search import DDGS
from config import SEARCH_MAX_RESULTS
import db_helpers as _db


def web_search(query: str) -> str:
    """Search the web via DuckDuckGo. Returns formatted results or an error string."""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=SEARCH_MAX_RESULTS))
        if not results:
            return "no results found"
        lines = []
        for r in results:
            title = r.get("title", "")
            snippet = r.get("body", "")[:200]
            url = r.get("href", "")
            lines.append(f"{title} — {snippet}\n{url}")
        return "\n\n".join(lines)
    except Exception as e:
        return f"search failed: {type(e).__name__}: {e}"


def set_reminder(text: str, fire_at: str) -> str:
    """Store a reminder in the DB. fire_at must be an ISO/SQLite datetime string."""
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(fire_at)
        _db.add_reminder(text, dt.strftime("%Y-%m-%d %H:%M:%S"))
        return f"reminder set for {dt.strftime('%H:%M')}"
    except Exception as e:
        return f"reminder failed: {type(e).__name__}: {e}"
