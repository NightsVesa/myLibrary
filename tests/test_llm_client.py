import json
import pytest
from unittest.mock import patch, MagicMock

from llm.client import LLMConfig, Message, chat, chat_stream


def _make_config():
    return LLMConfig(
        api_base="https://fake.api/v1",
        api_key="test-key",
        model="test-model",
    )


def test_llm_config_is_immutable():
    cfg = _make_config()
    with pytest.raises(AttributeError):
        cfg.api_key = "new"


def test_message_is_immutable():
    m = Message(role="user", content="hello")
    with pytest.raises(AttributeError):
        m.content = "bye"


def test_chat_returns_string():
    cfg = _make_config()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Hello back!"}}]
    }
    mock_response.raise_for_status = MagicMock()

    with patch("llm.client.httpx.post", return_value=mock_response):
        result = chat(cfg, [Message(role="user", content="hi")])
    assert result == "Hello back!"


def test_chat_sends_correct_headers():
    cfg = _make_config()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "ok"}}]
    }
    mock_response.raise_for_status = MagicMock()

    with patch("llm.client.httpx.post", return_value=mock_response) as mock_post:
        chat(cfg, [Message(role="user", content="test")])
    call_args = mock_post.call_args
    headers = call_args.kwargs.get("headers", call_args[1].get("headers", {}))
    assert "Authorization" in headers
    assert headers["Authorization"] == "Bearer test-key"


def test_chat_stream_yields_chunks():
    cfg = _make_config()
    lines = [
        b'data: {"choices":[{"delta":{"content":"He"}}]}',
        b'data: {"choices":[{"delta":{"content":"llo"}}]}',
        b'data: [DONE]',
    ]
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.iter_lines.return_value = iter(lines)
    mock_response.raise_for_status = MagicMock()
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch("llm.client.httpx.stream", return_value=mock_response):
        chunks = list(chat_stream(cfg, [Message(role="user", content="hi")]))
    assert chunks == ["He", "llo"]


def test_chat_raises_on_empty_key():
    cfg = LLMConfig(api_base="https://fake.api/v1", api_key="", model="m")
    with pytest.raises(ValueError, match="API key"):
        chat(cfg, [Message(role="user", content="hi")])
