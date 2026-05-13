import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
from lache_status_api import build_status


def test_build_status_returns_required_fields(fake_db):
    status = build_status()
    for key in ("messages_today", "last_proactive", "uptime_seconds"):
        assert key in status
    assert isinstance(status["messages_today"], int)
    assert isinstance(status["uptime_seconds"], int)
