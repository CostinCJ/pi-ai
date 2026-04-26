import spotipy
from spotipy.oauth2 import SpotifyOAuth
from config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REDIRECT_URI

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
            return "No tracks played recently."
            
        output = "Recent tracks: "
        for item in results['items']:
            artist = item['track']['artists'][0]['name']
            name = item['track']['name']
            output += f"{artist} - {name}, "
            
        output = output.rstrip(", ")
        current = get_current_track()
        
        if current:
            return current + " | " + output
            
        return output
        
    except Exception as e:
        # If anything major fails, return a string, don't crash the bot
        return f"Spotify data unavailable."

if __name__ == '__main__':
    print(get_recent_tracks())
