import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from litellm.exceptions import InternalServerError, RateLimitError

import sigil.core.llm as llm
from sigil.core.llm import (
    _MASKED_READ,
    _build_tool_call_map,
    _messages_to_text,
    _traces,
    acompletion,
    get_traces,
    get_usage,
    mask_old_tool_outputs,
    reset_traces,
    reset_usage,
    write_trace_file,
)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr("sigil.core.llm.INITIAL_DELAY", 0.0)


async def test_acompletion_returns_on_success():
    mock_response = {"choices": [{"message": {"content": "ok"}}]}
    with patch(
        "sigil.core.llm.litellm.acompletion", new_callable=AsyncMock, return_value=mock_response
    ) as mock:
        result = await acompletion(model="test", messages=[])
    assert result == mock_response
    mock.assert_awaited_once()


async def test_acompletion_retries_on_transient_error():
    mock_response = {"choices": [{"message": {"content": "ok"}}]}
    error = InternalServerError(message="overloaded", model="test", llm_provider="anthropic")
    mock = AsyncMock(side_effect=[error, error, mock_response])
    with patch("sigil.core.llm.litellm.acompletion", mock):
        result = await acompletion(model="test", messages=[])
    assert result == mock_response
    assert mock.await_count == 3


async def test_acompletion_retries_on_rate_limit():
    mock_response = {"choices": [{"message": {"content": "ok"}}]}
    error = RateLimitError(message="rate limited", model="test", llm_provider="anthropic")
    mock = AsyncMock(side_effect=[error, mock_response])
    with patch("sigil.core.llm.litellm.acompletion", mock):
        result = await acompletion(model="test", messages=[])
    assert result == mock_response
    assert mock.await_count == 2


async def test_acompletion_raises_after_max_retries():
    error = InternalServerError(message="overloaded", model="test", llm_provider="anthropic")
    mock = AsyncMock(side_effect=error)
    with patch("sigil.core.llm.litellm.acompletion", mock):
        with pytest.raises(InternalServerError):
            await acompletion(model="test", messages=[])
    assert mock.await_count == 4


async def test_acompletion_does_not_retry_non_retryable():
    mock = AsyncMock(side_effect=ValueError("bad"))
    with patch("sigil.core.llm.litellm.acompletion", mock):
        with pytest.raises(ValueError):
            await acompletion(model="test", messages=[])
    mock.assert_awaited_once()


def _make_assistant_msg(tool_calls):
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": tool_calls,
    }


def _make_tool_call(tc_id, name, file=""):
    args = json.dumps({"file": file}) if file else "{}"
    return {"id": tc_id, "function": {"name": name, "arguments": args}}


def _make_tool_result(tc_id, content):
    return {"role": "tool", "tool_call_id": tc_id, "content": content}


LONG_FILE = "x" * 300


def test_masks_old_read_file_via_tool_call_id():
    messages = [
        {"role": "user", "content": "analyze this repo"},
        _make_assistant_msg([_make_tool_call("tc_1", "read_file", file="src/a.py")]),
        _make_tool_result("tc_1", LONG_FILE),
        _make_assistant_msg([_make_tool_call("tc_2", "report_finding")]),
        _make_tool_result("tc_2", LONG_FILE),
    ]
    padding = [{"role": "assistant", "content": f"msg {i}"} for i in range(10)]
    messages.extend(padding)

    mask_old_tool_outputs(messages, keep_recent=10)

    assert messages[2]["content"] == _MASKED_READ
    assert messages[4]["content"] == LONG_FILE


def test_tool_call_map_with_litellm_objects():
    tc = SimpleNamespace(
        id="tc_obj",
        function=SimpleNamespace(name="read_file", arguments='{"file": "a.py"}'),
    )
    msg = SimpleNamespace(role="assistant", content=None, tool_calls=[tc])

    call_map = _build_tool_call_map([msg])

    assert call_map["tc_obj"].name == "read_file"
    assert call_map["tc_obj"].arguments == '{"file": "a.py"}'


def test_extracts_tool_call_text_from_mixed_inputs():
    messages = [
        _make_assistant_msg([_make_tool_call("tc_1", "read_file", file="src/a.py")]),
        _make_tool_result("tc_1", LONG_FILE),
        SimpleNamespace(
            role="assistant",
            content=None,
            tool_calls=[
                SimpleNamespace(
                    id="tc_2",
                    function=SimpleNamespace(name="", arguments='{"file": "b.py"}'),
                )
            ],
        ),
    ]

    text = _messages_to_text(messages)

    assert '[tool_call] read_file({"file": "src/a.py"})' in text
    assert '[tool_call] ?({"file": "b.py"})' in text


def test_extract_tc_handles_missing_function_mapping():
    tc = {"id": "tc_missing", "function": "not-a-mapping"}

    call_map = _build_tool_call_map(
        [SimpleNamespace(role="assistant", content=None, tool_calls=[tc])]
    )

    assert "tc_missing" not in call_map


def test_fetch_openrouter_models_sync_populates_cache_from_httpx_response():
    payload = {
        "data": [
            {
                "id": "provider/model",
                "context_length": 128_000,
                "top_provider": {"max_completion_tokens": 8_192},
            },
            {
                "id": "missing/output",
                "context_length": 1_024,
                "top_provider": {},
            },
        ]
    }
    response = Mock()
    response.content = json.dumps(payload).encode()
    response.raise_for_status.return_value = None

    with patch("sigil.core.llm.httpx.get", return_value=response) as mock_get:
        llm._fetch_openrouter_models_sync()

    mock_get.assert_called_once_with(
        "https://openrouter.ai/api/v1/models",
        headers={"Accept": "application/json"},
        timeout=10,
    )
    assert llm._openrouter_cache == {
        "openrouter/provider/model": {
            "max_input_tokens": 128_000,
            "max_output_tokens": 8_192,
        }
    }


def test_fetch_openrouter_models_ignores_incomplete_entries():
    payload = {
        "data": [
            {"id": "missing/context", "top_provider": {"max_completion_tokens": 2_048}},
            {"id": "missing/output", "context_length": 1_024, "top_provider": {}},
            {
                "id": "provider/model",
                "context_length": 256_000,
                "top_provider": {"max_completion_tokens": 65_536},
            },
        ]
    }
    response = Mock()
    response.content = json.dumps(payload).encode()
    response.raise_for_status.return_value = None

    with patch("sigil.core.llm.httpx.get", return_value=response):
        llm._fetch_openrouter_models_sync()

    assert llm._openrouter_cache == {
        "openrouter/provider/model": {
            "max_input_tokens": 256_000,
            "max_output_tokens": 65_536,
        }
    }


def test_fetch_openrouter_models_swallows_httpx_errors():
    with patch("sigil.core.llm.httpx.get", side_effect=RuntimeError("boom")):
        llm._fetch_openrouter_models()

    assert llm._openrouter_cache == {}


@pytest.mark.parametrize(
    ("tool_call", "expected"),
    [
        (SimpleNamespace(), ("", "", "")),
        (SimpleNamespace(id="tc_obj"), ("", "", "tc_obj")),
        (
            SimpleNamespace(id="tc_obj", function=SimpleNamespace()),
            ("", "", "tc_obj"),
        ),
        (
            SimpleNamespace(
                id="tc_obj",
                function=SimpleNamespace(name="read_file"),
            ),
            ("read_file", "", "tc_obj"),
        ),
        (
            SimpleNamespace(
                id="tc_obj",
                function={"name": "read_file", "arguments": '{"file": "a.py"}'},
            ),
            ("read_file", '{"file": "a.py"}', "tc_obj"),
        ),
    ],
)
def test_extract_tc_handles_partial_objects(tool_call, expected):
    from sigil.core.llm import _extract_tc

    assert _extract_tc(tool_call) == expected


def test_preserves_recent_messages():
    messages = [{"role": "user", "content": "start"}]
    for i in range(14):
        tc_id = f"tc_{i}"
        messages.append(
            _make_assistant_msg([_make_tool_call(tc_id, "read_file", file=f"file_{i}.py")])
        )
        messages.append(_make_tool_result(tc_id, LONG_FILE))

    originals = [m.get("content") for m in messages]
    mask_old_tool_outputs(messages, keep_recent=10)

    for msg, orig in zip(messages[-10:], originals[-10:]):
        assert msg.get("content") == orig

    masked_count = sum(1 for m in messages[:-10] if m.get("content") == _MASKED_READ)
    assert masked_count > 0


def test_deduplicates_read_file_by_path():
    messages = [
        {"role": "user", "content": "start"},
        _make_assistant_msg([_make_tool_call("tc_1", "read_file", file="src/a.py")]),
        _make_tool_result("tc_1", LONG_FILE),
        {"role": "assistant", "content": "thinking"},
        _make_assistant_msg([_make_tool_call("tc_2", "read_file", file="src/a.py")]),
        _make_tool_result("tc_2", LONG_FILE),
    ]

    mask_old_tool_outputs(messages, keep_recent=3)

    assert messages[2]["content"] == _MASKED_READ
    assert messages[5]["content"] == LONG_FILE


@pytest.fixture(autouse=True)
def _clean_traces():
    reset_traces()
    reset_usage()
    yield
    _traces.clear()


@pytest.fixture(autouse=True)
def _clean_openrouter_state():
    llm._openrouter_cache.clear()
    llm._openrouter_fetched = False
    yield
    llm._openrouter_cache.clear()
    llm._openrouter_fetched = False


def _mock_response(prompt_tok=100, completion_tok=50):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=None))],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tok,
            completion_tokens=completion_tok,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )


async def test_acompletion_records_trace_with_label():
    mock = AsyncMock(return_value=_mock_response(prompt_tok=1000, completion_tok=200))
    with (
        patch("sigil.core.llm.litellm.acompletion", mock),
        patch("sigil.core.llm.litellm.completion_cost", return_value=0.05),
    ):
        await acompletion(label="analysis", model="anthropic/claude-sonnet-4-6", messages=[])

    traces = get_traces()
    assert len(traces) == 1
    t = traces[0]
    assert t.label == "analysis"
    assert t.model == "anthropic/claude-sonnet-4-6"
    assert t.prompt_tokens == 1000
    assert t.completion_tokens == 200
    assert t.cost_usd == pytest.approx(0.05)


async def test_trace_cost_matches_usage():
    model = "anthropic/claude-sonnet-4-6"
    mock = AsyncMock(return_value=_mock_response(prompt_tok=5000, completion_tok=1000))
    with (
        patch("sigil.core.llm.litellm.acompletion", mock),
        patch("sigil.core.llm.litellm.completion_cost", return_value=0.123),
    ):
        await acompletion(label="execution", model=model, messages=[])

    trace = get_traces()[0]
    usage = get_usage()

    assert trace.cost_usd == pytest.approx(0.123)
    assert trace.cost_usd == pytest.approx(usage.cost_usd)


async def test_write_trace_file_structure(tmp_path):
    mock = AsyncMock(return_value=_mock_response(prompt_tok=500, completion_tok=100))
    with (
        patch("sigil.core.llm.litellm.acompletion", mock),
        patch("sigil.core.llm.litellm.completion_cost", return_value=0.01),
    ):
        await acompletion(label="analysis", model="anthropic/claude-sonnet-4-6", messages=[])
        await acompletion(label="execution", model="anthropic/claude-sonnet-4-6", messages=[])

    result = write_trace_file(tmp_path)
    assert result is not None

    data = json.loads(result.read_text())
    assert "started_at" in data
    assert data["total_calls"] == 2
    assert data["total_cost_usd"] > 0
    assert "analysis" in data["summary_by_label"]
    assert "execution" in data["summary_by_label"]


async def test_write_trace_file_summary_rollup(tmp_path):
    mock = AsyncMock(return_value=_mock_response(prompt_tok=1000, completion_tok=200))
    with (
        patch("sigil.core.llm.litellm.acompletion", mock),
        patch("sigil.core.llm.litellm.completion_cost", return_value=0.05),
    ):
        await acompletion(label="analysis", model="anthropic/claude-sonnet-4-6", messages=[])
        await acompletion(label="analysis", model="anthropic/claude-sonnet-4-6", messages=[])
        await acompletion(label="execution", model="anthropic/claude-sonnet-4-6", messages=[])

    result = write_trace_file(tmp_path)
    data = json.loads(result.read_text())

    analysis = data["summary_by_label"]["analysis"]
    assert analysis["calls"] == 2
    assert analysis["prompt_tokens"] == 2000
    assert analysis["completion_tokens"] == 400

    execution = data["summary_by_label"]["execution"]
    assert execution["calls"] == 1

    assert data["total_cost_usd"] == pytest.approx(analysis["cost_usd"] + execution["cost_usd"])


async def test_reset_traces_isolates_runs():
    mock = AsyncMock(return_value=_mock_response())
    with (
        patch("sigil.core.llm.litellm.acompletion", mock),
        patch("sigil.core.llm.litellm.completion_cost", return_value=0.01),
    ):
        await acompletion(label="run1", model="anthropic/claude-sonnet-4-6", messages=[])

    assert len(get_traces()) == 1

    reset_traces()

    assert len(get_traces()) == 0

    with (
        patch("sigil.core.llm.litellm.acompletion", mock),
        patch("sigil.core.llm.litellm.completion_cost", return_value=0.01),
    ):
        await acompletion(label="run2", model="anthropic/claude-sonnet-4-6", messages=[])

    traces = get_traces()
    assert len(traces) == 1
    assert traces[0].label == "run2"
