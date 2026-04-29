from datetime import datetime, timedelta
import db_helpers


def test_add_and_get_due_reminder(fake_db):
    fire_at = (datetime.now() - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    db_helpers.add_reminder("call mom", fire_at)
    due = db_helpers.get_due_reminders()
    assert len(due) == 1
    assert due[0]["text"] == "call mom"
    assert due[0]["id"] > 0


def test_future_reminder_not_due(fake_db):
    fire_at = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    db_helpers.add_reminder("future task", fire_at)
    due = db_helpers.get_due_reminders()
    assert len(due) == 0


def test_mark_reminder_delivered(fake_db):
    fire_at = (datetime.now() - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    db_helpers.add_reminder("test", fire_at)
    due = db_helpers.get_due_reminders()
    db_helpers.mark_reminder_delivered(due[0]["id"])
    assert len(db_helpers.get_due_reminders()) == 0


def test_delivered_reminder_not_returned(fake_db):
    fire_at = (datetime.now() - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    db_helpers.add_reminder("already done", fire_at)
    due = db_helpers.get_due_reminders()
    db_helpers.mark_reminder_delivered(due[0]["id"])
    assert db_helpers.get_due_reminders() == []
