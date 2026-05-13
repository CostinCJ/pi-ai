import json
import logging
import os
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
import psutil
import requests

# Keep in sync with config.py TAILSCALE_IP and SESSION_SERVER_PORT on the Pi
SESSION_SERVER_URL = os.environ.get(
    'SESSION_SERVER_URL', 'http://100.64.0.1:8765/session'
)
SESSION_SHARED_SECRET = os.environ.get('SESSION_SHARED_SECRET', '')
SHUTDOWN_PORT = int(os.environ.get('SHUTDOWN_PORT', '8766'))
NOTIFY_PORT = int(os.environ.get('NOTIFY_PORT', '8767'))

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


class _ShutdownHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != '/shutdown':
            self.send_response(404)
            self.end_headers()
            return
        if SESSION_SHARED_SECRET:
            token = self.headers.get('X-Session-Token', '')
            if token != SESSION_SHARED_SECRET:
                logging.warning("shutdown: rejected bad/missing token")
                self.send_response(401)
                self.end_headers()
                return
        self.send_response(200)
        self.end_headers()
        logging.info("shutdown: valid request received — scheduling shutdown in 30s")
        subprocess.Popen(['shutdown', '/s', '/t', '30'])

    def log_message(self, format, *args):
        pass


class _NotifyHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/notify":
            self.send_response(404); self.end_headers(); return
        if SESSION_SHARED_SECRET:
            token = self.headers.get("X-Session-Token", "")
            if token != SESSION_SHARED_SECRET:
                self.send_response(401); self.end_headers(); return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            text = str(body.get("text", ""))[:200]
        except Exception as e:
            logging.warning(f"notify parse error: {e}")
            self.send_response(400); self.end_headers(); return
        try:
            subprocess.run(["notify-send", "Lache", text], timeout=5, capture_output=True)
        except Exception:
            logging.info(f"notify: {text}")
        self.send_response(200); self.end_headers()

    def log_message(self, format, *args):
        pass


def _run_notify_server():
    if not SESSION_SHARED_SECRET:
        logging.warning("notify listener disabled: SESSION_SHARED_SECRET is required")
        return
    server = HTTPServer(("0.0.0.0", NOTIFY_PORT), _NotifyHandler)
    logging.info(f"notify listener on :{NOTIFY_PORT}")
    server.serve_forever()


def _run_shutdown_server():
    if not SESSION_SHARED_SECRET:
        logging.error("shutdown listener disabled: SESSION_SHARED_SECRET is required")
        return
    server = HTTPServer(('0.0.0.0', SHUTDOWN_PORT), _ShutdownHandler)
    logging.info(f"shutdown listener on :{SHUTDOWN_PORT}")
    server.serve_forever()


def main():
    logging.info("session daemon started")
    threading.Thread(target=_run_shutdown_server, daemon=True).start()
    threading.Thread(target=_run_notify_server, daemon=True).start()
    headers = {}
    if SESSION_SHARED_SECRET:
        headers['X-Session-Token'] = SESSION_SHARED_SECRET
    while True:
        try:
            apps = get_top_apps()
            requests.post(
                SESSION_SERVER_URL, json={'apps': apps},
                headers=headers, timeout=10,
            )
            logging.info(f"sent: {[a['name'] for a in apps]}")
        except (requests.ConnectionError, requests.Timeout) as e:
            logging.warning(f"send failed: {e}")
        except Exception as e:
            logging.error(f"unexpected error: {e}")
        time.sleep(120)


if __name__ == '__main__':
    main()
