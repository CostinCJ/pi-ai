import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def fake_db(tmp_path, monkeypatch):
    """Replace DB_PATH and the schema-creation flow with an empty in-memory-style file."""
    import init_db
    import db_helpers
    import config
    db_file = tmp_path / "test.db"
    monkeypatch.setattr(config, "DB_PATH", str(db_file))
    monkeypatch.setattr(db_helpers, "DB_PATH", str(db_file), raising=False)
    init_db.setup_database()  # creates all tables in db_file
    return str(db_file)


@pytest.fixture
def fake_ollama(monkeypatch):
    """Patch llm.chat to return scripted responses in order."""
    import llm
    calls = []
    queue = []

    def fake_chat(messages, options=None, timeout=60):
        calls.append({"messages": messages, "options": options})
        if not queue:
            return ""
        return queue.pop(0)

    monkeypatch.setattr(llm, "chat", fake_chat)
    return {"calls": calls, "queue": queue}
