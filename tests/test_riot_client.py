from unittest.mock import patch, MagicMock
import riot_client


@patch("riot_client.urllib.request.urlopen")
def test_is_in_game_true_when_spectator_returns_200(mock_urlopen, monkeypatch):
    monkeypatch.setattr(riot_client, "RIOT_API_KEY", "test-key")
    mock_resp = MagicMock(status=200)
    mock_resp.read.return_value = b'{"gameMode": "CLASSIC"}'
    mock_urlopen.return_value.__enter__.return_value = mock_resp
    assert riot_client.is_in_game("fake-puuid") is True


@patch("riot_client.urllib.request.urlopen")
def test_is_in_game_false_when_spectator_404(mock_urlopen, monkeypatch):
    monkeypatch.setattr(riot_client, "RIOT_API_KEY", "test-key")
    import urllib.error
    mock_urlopen.side_effect = urllib.error.HTTPError("", 404, "", {}, None)
    assert riot_client.is_in_game("fake-puuid") is False


def test_is_in_game_returns_false_when_no_api_key(monkeypatch):
    monkeypatch.setattr(riot_client, "RIOT_API_KEY", "")
    assert riot_client.is_in_game("any") is False
