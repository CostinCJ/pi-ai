from unittest.mock import patch, MagicMock
import desktop_push


@patch("desktop_push.urllib.request.urlopen")
def test_push_to_desktop_posts_with_auth_header(mock_urlopen, monkeypatch):
    monkeypatch.setattr(desktop_push, "DESKTOP_PUSH_URL", "http://desktop:8767/notify")
    mock_urlopen.return_value.__enter__.return_value = MagicMock(status=200)
    ok = desktop_push.push_to_desktop("hello")
    assert ok is True
    req = mock_urlopen.call_args[0][0]
    body = req.data.decode()
    assert "hello" in body


@patch("desktop_push.urllib.request.urlopen", side_effect=ConnectionRefusedError())
def test_push_to_desktop_returns_false_on_failure(_, monkeypatch):
    monkeypatch.setattr(desktop_push, "DESKTOP_PUSH_URL", "http://desktop:8767/notify")
    assert desktop_push.push_to_desktop("hello") is False


def test_push_to_desktop_returns_false_when_no_url(monkeypatch):
    monkeypatch.setattr(desktop_push, "DESKTOP_PUSH_URL", "")
    assert desktop_push.push_to_desktop("hello") is False
