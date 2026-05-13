"""Tiny status endpoint for Homepage widget consumption. Port 8770."""
import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db_helpers

_START = time.time()


def build_status() -> dict:
    with db_helpers.get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM conversations WHERE date(timestamp)=date('now')")
        msgs = cur.fetchone()[0]
        cur.execute("SELECT timestamp FROM proactive_log ORDER BY timestamp DESC LIMIT 1")
        row = cur.fetchone()
    return {
        "messages_today": msgs,
        "last_proactive": row[0] if row else None,
        "uptime_seconds": int(time.time() - _START),
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/status":
            self.send_response(404); self.end_headers(); return
        body = json.dumps(build_status()).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a, **kw):
        pass


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8770), Handler).serve_forever()
