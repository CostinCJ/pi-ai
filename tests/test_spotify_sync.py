"""Spotify timestamps: the API returns played_at in UTC ('...Z'). Everything
downstream (spotify_played_within, get_recent_spotify ages) treats played_at
as localtime, so ingestion must convert. Regression tests for the July 2026
bug where UTC was stored raw and the briefing music signal could never fire.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import db_helpers
import spotify_sync


def _api_item(played_at_utc):
    return {
        "played_at": played_at_utc.strftime("%Y-%m-%dT%H:%M:%S.123Z"),
        "track": {"artists": [{"name": "ptv"}], "name": "song"},
    }


def _fake_sp(items):
    sp = MagicMock()
    sp.current_user_recently_played.return_value = {"items": items}
    return sp


def test_recent_tracks_raw_converts_played_at_to_localtime():
    played = datetime.now(timezone.utc) - timedelta(minutes=5)
    with patch("spotify_sync._get_sp", return_value=_fake_sp([_api_item(played)])):
        tracks = spotify_sync.get_recent_tracks_raw()
    assert len(tracks) == 1
    stored = datetime.strptime(tracks[0]["played_at"], "%Y-%m-%d %H:%M:%S")
    # Stored value must be local wall-clock time: ~5 minutes ago by local now.
    age = datetime.now() - stored
    assert timedelta(minutes=4) < age < timedelta(minutes=7), (
        f"played_at {tracks[0]['played_at']} is {age} old by local clock — "
        "looks like raw UTC was stored"
    )


def test_played_within_sees_track_logged_from_api(fake_db):
    played = datetime.now(timezone.utc) - timedelta(minutes=5)
    with patch("spotify_sync._get_sp", return_value=_fake_sp([_api_item(played)])):
        tracks = spotify_sync.get_recent_tracks_raw()
    for t in tracks:
        assert db_helpers.log_spotify_track(t["artist"], t["title"], t["played_at"])
    assert db_helpers.spotify_played_within(20)
