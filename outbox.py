"""Delivery module. Import-leaf: config/db_helpers/stdlib/requests ONLY —
autonomy imports this module, so importing autonomy here is a cycle.

urgency='urgent'   -> immediate Telegram send (repeat-suppressed by default)
urgency='briefing' -> queued in outbox_queue, drained into the next briefing
"""
import logging
import requests
import db_helpers
from config import (
    TELEGRAM_TOKEN, CHAT_ID,
    PROACTIVE_REPEAT_OVERLAP, PROACTIVE_REPEAT_DAYS,
)

log = logging.getLogger(__name__)


def send_telegram_message(text):
    """Sends via Telegram. Returns True on 2xx, False otherwise. Never raises."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": CHAT_ID, "text": text}, timeout=10)
        if 200 <= r.status_code < 300:
            return True
        log.error(f"send_telegram_message non-2xx: {r.status_code} {r.text[:200]}")
        return False
    except Exception as e:
        log.error(f"send_telegram_message failed: {e}")
        return False


def _word_overlap(a, b):
    wa, wb = set(a.lower().split()), set(b.lower().split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))


def is_repeat(message):
    """True if near-identical to a recently sent proactive message."""
    for prev in db_helpers.get_recent_proactive_texts(days=PROACTIVE_REPEAT_DAYS):
        if _word_overlap(message, prev) >= PROACTIVE_REPEAT_OVERLAP:
            return True
    return False


def send(text, urgency="urgent", suppress_repeats=True):
    """Route a message. Returns True if delivered (or queued)."""
    if urgency == "briefing":
        with db_helpers.get_conn() as conn:
            conn.execute("INSERT INTO outbox_queue (text) VALUES (?)", (text,))
        return True
    if suppress_repeats and is_repeat(text):
        log.info(f"outbox: suppressed repeat: {text[:60]}")
        return False
    return send_telegram_message(text)


def drain_queue():
    """Unconsumed briefing items, oldest first; marks them consumed.
    Items older than 48h are dropped — stale news isn't news."""
    with db_helpers.get_conn() as conn:
        conn.execute(
            "DELETE FROM outbox_queue WHERE created_at < datetime('now', '-48 hours')"
        )
        rows = conn.execute(
            "SELECT id, text FROM outbox_queue WHERE consumed=0 ORDER BY id"
        ).fetchall()
        if rows:
            ids = [r[0] for r in rows]
            conn.execute(
                f"UPDATE outbox_queue SET consumed=1 WHERE id IN ({','.join('?' * len(ids))})",
                ids,
            )
    return [r[1] for r in rows]
