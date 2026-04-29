import os
import pytest

# Provide dummy env BEFORE config.py is imported so its required-env asserts
# don't blow up tests. Real values come from .env on the Pi.
_TEST_ENV = {
    "GROQ_API_KEY": "test",
    "TELEGRAM_TOKEN": "test",
    "CHAT_ID": "123",
    "OWM_API_KEY": "test",
    "SPOTIFY_CLIENT_ID": "test",
    "SPOTIFY_CLIENT_SECRET": "test",
    "SAPT1_ANCHOR": "2026-04-27",
}
for k, v in _TEST_ENV.items():
    os.environ.setdefault(k, v)


@pytest.fixture
def fake_db(tmp_path, monkeypatch):
    """Replace DB_PATH and the schema-creation flow with an empty in-memory-style file."""
    import init_db
    import db_helpers
    import config
    db_file = tmp_path / "test.db"
    monkeypatch.setattr(config, "DB_PATH", str(db_file))
    monkeypatch.setattr(db_helpers, "DB_PATH", str(db_file), raising=False)
    monkeypatch.setattr(init_db, "DB_PATH", str(db_file))
    init_db.setup_database()
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
