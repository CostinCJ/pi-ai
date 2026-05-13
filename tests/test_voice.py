from unittest.mock import patch, MagicMock
import llm


@patch("llm._client")
def test_transcribe_voice_returns_text(mock_client):
    mock_client.audio.transcriptions.create.return_value = MagicMock(text="salut Lache")
    out = llm.transcribe_voice(b"fake-ogg-bytes")
    assert out == "salut Lache"
    _, kwargs = mock_client.audio.transcriptions.create.call_args
    assert kwargs["model"] == "whisper-large-v3-turbo"


@patch("llm._client")
def test_transcribe_voice_returns_none_on_failure(mock_client):
    mock_client.audio.transcriptions.create.side_effect = RuntimeError("boom")
    assert llm.transcribe_voice(b"x") is None


def test_transcribe_voice_empty_bytes_returns_none():
    assert llm.transcribe_voice(b"") is None
    assert llm.transcribe_voice(None) is None
