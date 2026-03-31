from unittest.mock import Mock, patch

import httpx

from sigil.core.llm import _fetch_openrouter_models_sync, _openrouter_cache


def test_fetch_openrouter_models_sync_populates_cache() -> None:
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "data": [
            {
                "id": "provider/model-a",
                "context_length": 12345,
                "top_provider": {"max_completion_tokens": 6789},
            },
            {
                "id": "provider/model-b",
                "context_length": None,
                "top_provider": {"context_length": 22222, "max_completion_tokens": 3333},
            },
            {
                "id": "provider/model-c",
                "context_length": 11111,
                "top_provider": {"max_completion_tokens": 0},
            },
        ]
    }

    with patch("sigil.core.llm.httpx.get", return_value=response) as mock_get:
        _fetch_openrouter_models_sync()

    mock_get.assert_called_once_with(
        "https://openrouter.ai/api/v1/models",
        headers={"Accept": "application/json"},
        timeout=10.0,
    )
    assert _openrouter_cache == {
        "openrouter/provider/model-a": {
            "max_input_tokens": 12345,
            "max_output_tokens": 6789,
        },
        "openrouter/provider/model-b": {
            "max_input_tokens": 22222,
            "max_output_tokens": 3333,
        },
    }


def test_fetch_openrouter_models_sync_propagates_http_errors() -> None:
    _openrouter_cache.clear()
    _openrouter_cache["stale/model"] = {"max_input_tokens": 1, "max_output_tokens": 2}

    with patch("sigil.core.llm.httpx.get", side_effect=httpx.TimeoutException("boom")):
        try:
            _fetch_openrouter_models_sync()
        except httpx.TimeoutException:
            raised = True
        else:
            raised = False

    assert raised is True
    assert _openrouter_cache == {"stale/model": {"max_input_tokens": 1, "max_output_tokens": 2}}
