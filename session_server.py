import json
import logging
import os
import signal
from logging.handlers import RotatingFileHandler
from http.server import BaseHTTPRequestHandler, HTTPServer
import db_helpers
from config import (
    TAILSCALE_IP, SESSION_SERVER_PORT, SESSION_SHARED_SECRET,
    LOG_DIR, APP_LOG_MAX_BYTES, APP_LOG_BACKUPS,
)

_handler = RotatingFileHandler(
    os.path.join(str(LOG_DIR), 'session_server.log'),
    maxBytes=APP_LOG_MAX_BYTES, backupCount=APP_LOG_BACKUPS,
)
_handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
logging.basicConfig(level=logging.INFO, handlers=[_handler])


def _validate(payload):
    if not isinstance(payload, dict):
        return False
    apps = payload.get('apps')
    if not isinstance(apps, list) or len(apps) == 0:
        return False
    for app in apps:
        if not isinstance(app.get('name'), str):
            return False
        if not isinstance(app.get('ram_mb'), int) or isinstance(app.get('ram_mb'), bool):
            return False
    return True


class SessionHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != '/session':
            self.send_response(404)
            self.end_headers()
            return

        # Optional shared-secret check for defense-in-depth on top of Tailscale ACLs.
        if SESSION_SHARED_SECRET:
            sent = self.headers.get('X-Session-Token', '')
            if sent != SESSION_SHARED_SECRET:
                logging.warning("rejected: bad/missing X-Session-Token")
                self.send_response(401)
                self.end_headers()
                return

        try:
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            payload = json.loads(body)
        except Exception as e:
            logging.warning(f"parse error: {e}")
            self.send_response(400)
            self.end_headers()
            return

        if not _validate(payload):
            logging.warning(f"invalid payload: {str(payload)[:200]}")
            self.send_response(400)
            self.end_headers()
            return

        db_helpers.log_session_snapshot(payload['apps'])
        logging.info(f"accepted: {len(payload['apps'])} apps")
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        pass


def _shutdown(signum, frame):
    logging.info(f"received signal {signum}, shutting down")
    raise SystemExit(0)


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    server = HTTPServer((TAILSCALE_IP, SESSION_SERVER_PORT), SessionHandler)
    logging.info(f"listening on {TAILSCALE_IP}:{SESSION_SERVER_PORT}")
    try:
        server.serve_forever()
    except SystemExit:
        server.server_close()
