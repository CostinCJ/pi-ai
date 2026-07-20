from datetime import datetime, timezone, timedelta
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REDIRECT_URI

RECENT_ACTIVE_HOURS = 4

SCOPE = "user-read-recently-played user-read-currently-playing"

def _get_sp():
    return spotipy.Spotify(auth_manager=SpotifyOAuth(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope=SCOPE,
        open_browser=False
    ))

def get_current_track():
    try:
        sp = _get_sp()
        # Changed from current_playback() to current_user_playing_track()
        current = sp.current_user_playing_track() 
        if current and current.get('is_playing') and current.get('item'):
            track = current['item']
            artist = track['artists'][0]['name']
            name = track['name']
            return f"Currently playing: {artist} — {name}"
        return None
    except Exception as e:
        return None

def get_recent_tracks():
    try:
        sp = _get_sp()
        results = sp.current_user_recently_played(limit=5)

        if not results or not results.get('items'):
            return None

        first_item = results['items'][0]
        played_at_str = first_item.get('played_at', '')
        if played_at_str:
            played_at = datetime.fromisoformat(played_at_str.replace('Z', '+00:00'))
            if datetime.now(timezone.utc) - played_at > timedelta(hours=RECENT_ACTIVE_HOURS):
                return None

        output = ""
        for item in results['items']:
            artist = item['track']['artists'][0]['name']
            name = item['track']['name']
            output += f"{artist} - {name}, "

        output = output.rstrip(", ")
        current = get_current_track()

        if current:
            return current + " | " + output

        return output

    except Exception:
        return None

def get_recent_tracks_raw():
    """Return list of {artist, title, played_at} dicts for the polling loop."""
    try:
        sp = _get_sp()
        results = sp.current_user_recently_played(limit=10)
        if not results or not results.get('items'):
            return []
        tracks = []
        for item in results['items']:
            played_at_str = item.get('played_at', '')
            played_local = ''
            if played_at_str:
                played_at = datetime.fromisoformat(played_at_str.replace('Z', '+00:00'))
                if datetime.now(timezone.utc) - played_at > timedelta(hours=RECENT_ACTIVE_HOURS):
                    continue
                # Spotify reports UTC; the DB convention (spotify_played_within,
                # get_recent_spotify ages) is naive localtime.
                played_local = (
                    played_at.astimezone().replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
                )
            tracks.append({
                'artist': item['track']['artists'][0]['name'],
                'title': item['track']['name'],
                'played_at': played_local,
            })
        return tracks
    except Exception:
        return []


if __name__ == '__main__':
    print(get_recent_tracks())
