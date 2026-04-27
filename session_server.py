import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
import db_helpers
from config import TAILSCALE_IP, SESSION_SERVER_PORT

logging.basicConfig(
    filename='/home/pi/pi-ai/session_server.log',
    level=logging.INFO,
    format='%(asctime)s %(message)s'
)


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


if __name__ == '__main__':
    server = HTTPServer((TAILSCALE_IP, SESSION_SERVER_PORT), SessionHandler)
    logging.info(f"listening on {TAILSCALE_IP}:{SESSION_SERVER_PORT}")
    server.serve_forever()
