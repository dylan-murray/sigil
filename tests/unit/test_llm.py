from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from litellm.exceptions import InternalServerError, RateLimitError

from sigil.llm import _MASKED_READ, _build_tool_name_map, acompletion, mask_old_tool_outputs


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


def _make_assistant_msg(tool_calls):
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": tool_calls,
    }


def _make_tool_call(tc_id, name):
    return {"id": tc_id, "function": {"name": name, "arguments": "{}"}}


def _make_tool_result(tc_id, content):
    return {"role": "tool", "tool_call_id": tc_id, "content": content}


LONG_FILE = "x" * 300


def test_masks_old_read_file_via_tool_call_id():
    messages = [
        {"role": "user", "content": "analyze this repo"},
        _make_assistant_msg([_make_tool_call("tc_1", "read_file")]),
        _make_tool_result("tc_1", LONG_FILE),
        _make_assistant_msg([_make_tool_call("tc_2", "report_finding")]),
        _make_tool_result("tc_2", LONG_FILE),
    ]
    padding = [{"role": "assistant", "content": f"msg {i}"} for i in range(10)]
    messages.extend(padding)

    mask_old_tool_outputs(messages, keep_recent=10)

    assert messages[2]["content"] == _MASKED_READ
    assert messages[4]["content"] == LONG_FILE


def test_tool_name_map_with_litellm_objects():
    tc = SimpleNamespace(
        id="tc_obj",
        function=SimpleNamespace(name="read_file"),
    )
    msg = SimpleNamespace(role="assistant", content=None, tool_calls=[tc])

    name_map = _build_tool_name_map([msg])

    assert name_map == {"tc_obj": "read_file"}


def test_preserves_recent_messages():
    messages = [{"role": "user", "content": "start"}]
    for i in range(14):
        tc_id = f"tc_{i}"
        messages.append(_make_assistant_msg([_make_tool_call(tc_id, "read_file")]))
        messages.append(_make_tool_result(tc_id, LONG_FILE))

    originals = [m.get("content") for m in messages]
    mask_old_tool_outputs(messages, keep_recent=10)

    for msg, orig in zip(messages[-10:], originals[-10:]):
        assert msg.get("content") == orig

    masked_count = sum(1 for m in messages[:-10] if m.get("content") == _MASKED_READ)
    assert masked_count > 0
