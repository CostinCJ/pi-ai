import json
import logging
import time
import psutil
import requests

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
    'backgroundtaskhost.exe', 'memory compression', 'sppsvc.exe',
    'dashost.exe', 'wudfhost.exe', 'widgetservice.exe', 'widgets.exe',
    'explorer.exe',
}

logging.basicConfig(
    filename='session_daemon.log',
    level=logging.INFO,
    format='%(asctime)s %(message)s'
)


def get_top_apps():
    procs = []
    for proc in psutil.process_iter(['name', 'memory_info']):
        try:
            name = proc.info['name'] or ''
            if name.lower() in SYSTEM_PROCESSES:
                continue
            ram_mb = proc.info['memory_info'].rss // (1024 * 1024)
            if ram_mb < 1:
                continue
            clean_name = name.replace('.exe', '').replace('.EXE', '').strip()
            procs.append({'name': clean_name, 'ram_mb': ram_mb})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
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
