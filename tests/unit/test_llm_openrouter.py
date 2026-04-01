from unittest.mock import Mock, patch

import httpx

from sigil.core.llm import _fetch_openrouter_models_sync, _openrouter_cache


def test_fetch_openrouter_models_sync_populates_cache():
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "data": [
            {
                "id": "model-a",
                "top_provider": {"context_length": 12345, "max_completion_tokens": 678},
            },
            {
                "id": "model-b",
                "context_length": 54321,
                "top_provider": {"max_completion_tokens": 111},
            },
            {"id": "skip-me", "top_provider": {"context_length": 1}},
        ]
    }
    client = Mock()
    client.get.return_value = response
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=None)

    with patch("sigil.core.llm.httpx.Client", return_value=client):
        _fetch_openrouter_models_sync()

    assert _openrouter_cache["openrouter/model-a"] == {
        "max_input_tokens": 12345,
        "max_output_tokens": 678,
    }
    assert _openrouter_cache["openrouter/model-b"] == {
        "max_input_tokens": 54321,
        "max_output_tokens": 111,
    }
    assert "openrouter/skip-me" not in _openrouter_cache


def test_fetch_openrouter_models_sync_handles_http_errors():
    client = Mock()
    client.get.side_effect = httpx.RequestError("boom", request=Mock())
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=None)

    with patch("sigil.core.llm.httpx.Client", return_value=client):
        _fetch_openrouter_models_sync()

    assert _openrouter_cache == {
        "openrouter/model-a": {
            "max_input_tokens": 12345,
            "max_output_tokens": 678,
        },
        "openrouter/model-b": {
            "max_input_tokens": 54321,
            "max_output_tokens": 111,
        },
    }
