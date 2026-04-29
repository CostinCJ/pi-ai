import subprocess
from config import PHONE_MAC


def phone_is_home():
    """
    Returns True if PHONE_MAC is visible on the LAN via arp-scan.
    Returns False if scan succeeded but MAC not found.
    Returns None if the scan failed (not installed, timeout, permission error).
    """
    try:
        result = subprocess.run(
            ['sudo', 'arp-scan', '-l', '--quiet'],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return None
        return PHONE_MAC.lower() in result.stdout.lower()
    except Exception:
        return None
