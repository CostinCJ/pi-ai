import json
import logging
import re
import time
import psutil
import requests

# Keep in sync with config.py TAILSCALE_IP and SESSION_SERVER_PORT on the Pi
SESSION_SERVER_URL = 'http://100.64.0.1:8765/session'

SYSTEM_PROCESSES = {
    'system', 'registry', 'smss.exe', 'csrss.exe', 'wininit.exe',
    'services.exe', 'lsass.exe', 'lsaiso.exe', 'svchost.exe', 'dwm.exe',
    'winlogon.exe', 'fontdrvhost.exe', 'audiodg.exe', 'spoolsv.exe',
    'taskhostw.exe', 'runtimebroker.exe', 'searchindexer.exe',
    'searchhost.exe', 'startmenuexperiencehost.exe', 'shellexperiencehost.exe',
    'sihost.exe', 'ctfmon.exe', 'conhost.exe', 'dllhost.exe',
    'msmpeng.exe', 'nissrv.exe', 'securityhealthservice.exe',
    'wmiprvse.exe', 'textinputhost.exe', 'applicationframehost.exe',
    'backgroundtaskhost.exe', 'memory compression', 'memcompression',
    'sppsvc.exe', 'dashost.exe', 'wudfhost.exe', 'widgetservice.exe',
    'widgets.exe', 'explorer.exe', 'nvcontainer.exe', 'nvcontainer',
    'msedgewebview2.exe', 'msedgewebview2',
}

logging.basicConfig(
    filename='session_daemon.log',
    level=logging.INFO,
    format='%(asctime)s %(message)s'
)


def get_top_apps():
    totals = {}
    for proc in psutil.process_iter(['name', 'memory_info']):
        try:
            name = proc.info['name'] or ''
            if name.lower() in SYSTEM_PROCESSES:
                continue
            ram_mb = proc.info['memory_info'].rss // (1024 * 1024)
            if ram_mb < 1:
                continue
            clean_name = re.sub(r'\.exe$', '', name, flags=re.IGNORECASE).strip()
            totals[clean_name] = totals.get(clean_name, 0) + ram_mb
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    procs = [{'name': n, 'ram_mb': r} for n, r in totals.items()]
    procs.sort(key=lambda x: x['ram_mb'], reverse=True)
    return procs[:5]


def main():
    logging.info("session daemon started")
    while True:
        try:
            apps = get_top_apps()
            requests.post(SESSION_SERVER_URL, json={'apps': apps}, timeout=10)
            logging.info(f"sent: {[a['name'] for a in apps]}")
        except (requests.ConnectionError, requests.Timeout) as e:
            logging.warning(f"send failed: {e}")
        except Exception as e:
            logging.error(f"unexpected error: {e}")
        time.sleep(120)


if __name__ == '__main__':
    main()
