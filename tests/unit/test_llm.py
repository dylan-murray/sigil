from unittest.mock import AsyncMock, patch

import pytest
from litellm.exceptions import InternalServerError, RateLimitError

from sigil.llm import acompletion


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr("sigil.llm.INITIAL_DELAY", 0.0)


async def test_acompletion_returns_on_success():
    mock_response = {"choices": [{"message": {"content": "ok"}}]}
    with patch(
        "sigil.llm.litellm.acompletion", new_callable=AsyncMock, return_value=mock_response
    ) as mock:
        result = await acompletion(model="test", messages=[])
    assert result == mock_response
    mock.assert_awaited_once()


async def test_acompletion_retries_on_transient_error():
    mock_response = {"choices": [{"message": {"content": "ok"}}]}
    error = InternalServerError(message="overloaded", model="test", llm_provider="anthropic")
    mock = AsyncMock(side_effect=[error, error, mock_response])
    with patch("sigil.llm.litellm.acompletion", mock):
        result = await acompletion(model="test", messages=[])
    assert result == mock_response
    assert mock.await_count == 3


async def test_acompletion_retries_on_rate_limit():
    mock_response = {"choices": [{"message": {"content": "ok"}}]}
    error = RateLimitError(message="rate limited", model="test", llm_provider="anthropic")
    mock = AsyncMock(side_effect=[error, mock_response])
    with patch("sigil.llm.litellm.acompletion", mock):
        result = await acompletion(model="test", messages=[])
    assert result == mock_response
    assert mock.await_count == 2


async def test_acompletion_raises_after_max_retries():
    error = InternalServerError(message="overloaded", model="test", llm_provider="anthropic")
    mock = AsyncMock(side_effect=error)
    with patch("sigil.llm.litellm.acompletion", mock):
        with pytest.raises(InternalServerError):
            await acompletion(model="test", messages=[])
    assert mock.await_count == 4


async def test_acompletion_does_not_retry_non_retryable():
    mock = AsyncMock(side_effect=ValueError("bad"))
    with patch("sigil.llm.litellm.acompletion", mock):
        with pytest.raises(ValueError):
            await acompletion(model="test", messages=[])
    mock.assert_awaited_once()
