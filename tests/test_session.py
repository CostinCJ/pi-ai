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
