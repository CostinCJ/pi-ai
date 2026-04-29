import db_helpers
import bot


def test_user_recently_repeated_skips_current_row(fake_db):
    """The function is called AFTER the current message is logged. It must
    skip the most recent row (which is itself) and only flag duplicates of
    earlier user messages."""
    db_helpers.log_message('user', 'i m going out')
    db_helpers.log_message('ai', 'where to')
    db_helpers.log_message('user', 'yeah going out')
    assert bot._user_recently_repeated('yeah going out') is True


def test_user_recently_repeated_distinct(fake_db):
    db_helpers.log_message('user', 'morning')
    db_helpers.log_message('ai', 'sup')
    db_helpers.log_message('user', 'how is your day')
    assert bot._user_recently_repeated('how is your day') is False


def test_user_recently_repeated_first_message_not_dup(fake_db):
    db_helpers.log_message('user', 'first ever message here')
    assert bot._user_recently_repeated('first ever message here') is False
