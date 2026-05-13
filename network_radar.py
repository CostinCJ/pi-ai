import logging
import re
import subprocess
from config import PHONE_MAC

log = logging.getLogger(__name__)


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


def current_ssid() -> str | None:
    try:
        r = subprocess.run(
            ["iwgetid", "-r"], capture_output=True, text=True, timeout=3
        )
        ssid = (r.stdout or "").strip()
        return ssid or None
    except Exception as e:
        log.warning("iwgetid failure: %s", e)
        return None


_BLE_LINE = re.compile(r"\[\w+\] Device ([0-9A-F:]{17}) (.+)")


def nearby_ble_devices(timeout: int = 8) -> list[tuple[str, str]]:
    try:
        r = subprocess.run(
            ["bluetoothctl", "--timeout", str(timeout), "scan", "on"],
            capture_output=True, text=True, timeout=timeout + 5,
        )
        seen = {}
        for line in r.stdout.splitlines():
            m = _BLE_LINE.search(line)
            if m:
                seen[m.group(1)] = m.group(2).strip()
        return list(seen.items())
    except Exception as e:
        log.warning("ble scan failure: %s", e)
        return []
