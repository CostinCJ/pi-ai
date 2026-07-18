from unittest.mock import patch
import db_helpers
import outbox


def test_briefing_urgency_queues_instead_of_sending(fake_db):
    with patch.object(outbox, "send_telegram_message") as tg:
        ok = outbox.send("ptv dropped an album", urgency="briefing")
    assert ok
    tg.assert_not_called()
    assert outbox.drain_queue() == ["ptv dropped an album"]


def test_drain_marks_consumed(fake_db):
    outbox.send("item one", urgency="briefing")
    assert outbox.drain_queue() == ["item one"]
    assert outbox.drain_queue() == []


def test_drain_drops_stale_items(fake_db):
    outbox.send("old news", urgency="briefing")
    with db_helpers.get_conn() as conn:
        conn.execute(
            "UPDATE outbox_queue SET created_at = datetime('now', '-3 days')"
        )
    assert outbox.drain_queue() == []


def test_urgent_sends_immediately(fake_db):
    with patch.object(outbox, "send_telegram_message", return_value=True) as tg:
        ok = outbox.send("disk at 91%", urgency="urgent")
    assert ok
    tg.assert_called_once_with("disk at 91%")


def test_urgent_repeat_suppressed(fake_db):
    db_helpers.log_proactive("t", "k", "disk at 91%", delivered=1)
    with patch.object(outbox, "send_telegram_message") as tg:
        ok = outbox.send("disk at 91%", urgency="urgent")
    assert not ok
    tg.assert_not_called()


def test_urgent_repeat_check_can_be_bypassed(fake_db):
    db_helpers.log_proactive("t", "k", "same text", delivered=1)
    with patch.object(outbox, "send_telegram_message", return_value=True) as tg:
        ok = outbox.send("same text", urgency="urgent", suppress_repeats=False)
    assert ok
    tg.assert_called_once()


def test_is_repeat_matches_near_identical(fake_db):
    db_helpers.log_proactive("t", "k", "still warm out huh", delivered=1)
    assert outbox.is_repeat("still warm out huh")
    assert outbox.is_repeat("it's still warm out huh")
    assert not outbox.is_repeat("cold front tonight, 12 degrees by morning")
