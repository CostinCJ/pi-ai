import json
import logging
import urllib.request
from config import DESKTOP_PUSH_URL, SESSION_SHARED_SECRET

log = logging.getLogger(__name__)


def push_to_desktop(text: str, timeout: float = 5.0) -> bool:
    if not DESKTOP_PUSH_URL:
        return False
    payload = json.dumps({"text": text}).encode()
    headers = {"Content-Type": "application/json"}
    if SESSION_SHARED_SECRET:
        headers["X-Session-Token"] = SESSION_SHARED_SECRET
    req = urllib.request.Request(DESKTOP_PUSH_URL, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception as e:
        log.warning("desktop push failed: %s", e)
        return False
