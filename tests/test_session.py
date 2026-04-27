import sqlite3
import json
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Table existence
# ---------------------------------------------------------------------------

def test_session_snapshot_table_exists(fake_db):
    with __import__('db_helpers').get_conn() as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
    assert 'session_snapshot' in tables


# ---------------------------------------------------------------------------
# db_helpers — log_session_snapshot / get_latest_session_snapshot
# ---------------------------------------------------------------------------

import db_helpers


SAMPLE_APPS = [
    {"name": "League of Legends", "ram_mb": 823},
    {"name": "Discord",           "ram_mb": 347},
    {"name": "Spotify",           "ram_mb": 241},
]


def test_get_latest_session_snapshot_returns_none_when_empty(fake_db):
    assert db_helpers.get_latest_session_snapshot() is None


def test_log_and_get_session_snapshot(fake_db):
    db_helpers.log_session_snapshot(SAMPLE_APPS)
    result = db_helpers.get_latest_session_snapshot()
    assert result is not None
    assert result[0]["name"] == "League of Legends"
    assert result[0]["ram_mb"] == 823
    assert len(result) == 3


def test_get_latest_session_snapshot_returns_none_when_stale(fake_db):
    stale_ts = (datetime.now() - timedelta(minutes=6)).strftime("%Y-%m-%d %H:%M:%S")
    with db_helpers.get_conn() as conn:
        conn.execute(
            "INSERT INTO session_snapshot (timestamp, apps) VALUES (?, ?)",
            (stale_ts, json.dumps(SAMPLE_APPS))
        )
    assert db_helpers.get_latest_session_snapshot() is None


def test_log_session_snapshot_trims_to_50_rows(fake_db):
    for i in range(55):
        db_helpers.log_session_snapshot([{"name": f"App{i}", "ram_mb": i}])
    with db_helpers.get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM session_snapshot").fetchone()[0]
    assert count == 50


# ---------------------------------------------------------------------------
# session_trigger
# ---------------------------------------------------------------------------

from triggers import session_trigger


def test_session_trigger_no_fire_when_no_snapshot(fake_db):
    with patch("triggers.db_helpers.get_latest_session_snapshot", return_value=None):
        fired, ctx = session_trigger()
    assert fired is False
    assert ctx == ""


def test_session_trigger_no_fire_when_no_game(fake_db):
    apps = [
        {"name": "Discord",  "ram_mb": 347},
        {"name": "Spotify",  "ram_mb": 241},
        {"name": "chrome",   "ram_mb": 198},
    ]
    with patch("triggers.db_helpers.get_latest_session_snapshot", return_value=apps):
        fired, ctx = session_trigger()
    assert fired is False


def test_session_trigger_fires_when_league_detected(fake_db):
    apps = [
        {"name": "League of Legends", "ram_mb": 823},
        {"name": "Discord",           "ram_mb": 347},
    ]
    with patch("triggers.db_helpers.get_latest_session_snapshot", return_value=apps), \
         patch("triggers.db_helpers.was_proactive_attempted_today", return_value=False):
        fired, ctx = session_trigger()
    assert fired is True
    assert "league" in ctx.lower() or "League" in ctx
    assert "Discord" in ctx


def test_session_trigger_no_refire_same_day(fake_db):
    apps = [{"name": "League of Legends", "ram_mb": 823}]
    with patch("triggers.db_helpers.was_proactive_attempted_today", return_value=True), \
         patch("triggers.db_helpers.get_latest_session_snapshot", return_value=apps):
        fired, ctx = session_trigger()
    assert fired is False


# ---------------------------------------------------------------------------
# brain.py — session snapshot injection
# ---------------------------------------------------------------------------

import brain


BRAIN_APPS = [
    {"name": "League of Legends", "ram_mb": 823},
    {"name": "Discord",           "ram_mb": 347},
    {"name": "chrome",            "ram_mb": 198},
]


def test_build_context_includes_session_when_fresh(fake_db):
    with patch("brain.db_helpers.get_latest_session_snapshot", return_value=BRAIN_APPS), \
         patch("brain.db_helpers.get_user_facts", return_value="(no specific facts stored yet)"), \
         patch("brain.spotify_sync.get_recent_tracks", return_value="unavailable"), \
         patch("brain.db_helpers.get_recent_patterns", return_value="(no new patterns observed)"):
        ctx = brain._build_context_line("hey")
    assert "Session:" in ctx
    assert "League of Legends" in ctx
    assert "823MB" in ctx


def test_build_context_skips_session_when_none(fake_db):
    with patch("brain.db_helpers.get_latest_session_snapshot", return_value=None), \
         patch("brain.db_helpers.get_user_facts", return_value="(no specific facts stored yet)"), \
         patch("brain.spotify_sync.get_recent_tracks", return_value="unavailable"), \
         patch("brain.db_helpers.get_recent_patterns", return_value="(no new patterns observed)"):
        ctx = brain._build_context_line("hey")
    assert "Session:" not in ctx


def test_build_proactive_context_includes_session_when_fresh(fake_db):
    with patch("brain.db_helpers.get_latest_session_snapshot", return_value=BRAIN_APPS), \
         patch("brain.db_helpers.get_user_facts", return_value="(no specific facts stored yet)"), \
         patch("brain.spotify_sync.get_recent_tracks", return_value="unavailable"), \
         patch("brain.db_helpers.get_recent_patterns", return_value="(no new patterns observed)"):
        ctx = brain._build_proactive_context()
    assert "Session:" in ctx
    assert "Discord" in ctx
