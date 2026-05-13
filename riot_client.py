import json
import logging
import urllib.error
import urllib.request
from config import RIOT_API_KEY, RIOT_REGION, RIOT_PLATFORM

log = logging.getLogger(__name__)


def _headers():
    return {"X-Riot-Token": RIOT_API_KEY}


def is_in_game(puuid: str) -> bool:
    if not RIOT_API_KEY or not puuid:
        return False
    url = f"https://{RIOT_PLATFORM}.api.riotgames.com/lol/spectator/v5/active-games/by-summoner/{puuid}"
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        log.warning("riot spectator error: %s", e)
        return False
    except Exception as e:
        log.warning("riot spectator failure: %s", e)
        return False


def get_recent_match_ids(puuid: str, count: int = 1) -> list[str]:
    if not RIOT_API_KEY or not puuid:
        return []
    url = f"https://{RIOT_REGION}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?count={count}"
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception as e:
        log.warning("riot match list failure: %s", e)
        return []


def get_match(match_id: str) -> dict | None:
    if not RIOT_API_KEY or not match_id:
        return None
    url = f"https://{RIOT_REGION}.api.riotgames.com/lol/match/v5/matches/{match_id}"
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read())
    except Exception as e:
        log.warning("riot match fetch failure: %s", e)
        return None
