import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from litellm.exceptions import InternalServerError, RateLimitError

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


def _make_tool_call(tc_id, name, file="", **extra_args):
    args = json.dumps({"file": file, **extra_args}) if file else "{}"
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


def test_masks_read_when_superseded_by_write():
    from sigil.core.llm import _MASKED_READ_STALE

    messages = [
        {"role": "user", "content": "edit this file"},
        _make_assistant_msg([_make_tool_call("tc_1", "read_file", file="src/a.py")]),
        _make_tool_result("tc_1", LONG_FILE),
        _make_assistant_msg([_make_tool_call("tc_2", "apply_edit", file="src/a.py")]),
        _make_tool_result("tc_2", "Applied edit to src/a.py"),
        _make_assistant_msg([_make_tool_call("tc_3", "read_file", file="src/a.py")]),
        _make_tool_result("tc_3", LONG_FILE),
    ]
    padding = [{"role": "assistant", "content": f"msg {i}"} for i in range(5)]
    messages.extend(padding)

    mask_old_tool_outputs(messages, keep_recent=8)

    assert messages[2]["content"] == _MASKED_READ_STALE
    assert messages[6]["content"] == LONG_FILE


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


def test_keeps_distinct_windows_of_same_file():
    messages = [
        {"role": "user", "content": "start"},
        _make_assistant_msg([_make_tool_call("tc_1", "read_file", file="src/a.py", offset=200)]),
        _make_tool_result("tc_1", LONG_FILE),
        _make_assistant_msg([_make_tool_call("tc_2", "read_file", file="src/a.py", offset=1040)]),
        _make_tool_result("tc_2", LONG_FILE),
        {"role": "assistant", "content": "comparing the two regions"},
        {"role": "assistant", "content": "still thinking"},
    ]

    mask_old_tool_outputs(messages, keep_recent=6)

    assert messages[2]["content"] == LONG_FILE
    assert messages[4]["content"] == LONG_FILE


def test_masks_duplicate_window_reads():
    messages = [
        {"role": "user", "content": "start"},
        _make_assistant_msg(
            [_make_tool_call("tc_1", "read_file", file="src/a.py", offset=200, limit=25)]
        ),
        _make_tool_result("tc_1", LONG_FILE),
        _make_assistant_msg(
            [_make_tool_call("tc_2", "read_file", file="src/a.py", offset=200, limit=25)]
        ),
        _make_tool_result("tc_2", LONG_FILE),
        {"role": "assistant", "content": "thinking"},
        {"role": "assistant", "content": "thinking more"},
    ]

    mask_old_tool_outputs(messages, keep_recent=6)

    assert messages[2]["content"] == _MASKED_READ
    assert messages[4]["content"] == LONG_FILE


def test_stale_windows_masked_after_write():
    from sigil.core.llm import _MASKED_READ_STALE

    messages = [
        {"role": "user", "content": "start"},
        _make_assistant_msg([_make_tool_call("tc_1", "read_file", file="src/a.py", offset=1)]),
        _make_tool_result("tc_1", LONG_FILE),
        _make_assistant_msg([_make_tool_call("tc_2", "read_file", file="src/a.py", offset=500)]),
        _make_tool_result("tc_2", LONG_FILE),
        _make_assistant_msg([_make_tool_call("tc_3", "apply_edit", file="src/a.py")]),
        _make_tool_result("tc_3", "Applied edit to src/a.py"),
        _make_assistant_msg([_make_tool_call("tc_4", "read_file", file="src/a.py", offset=1)]),
        _make_tool_result("tc_4", LONG_FILE),
    ]

    mask_old_tool_outputs(messages, keep_recent=8)

    assert messages[2]["content"] == _MASKED_READ_STALE
    assert messages[4]["content"] == _MASKED_READ_STALE
    assert messages[8]["content"] == LONG_FILE


def test_window_ping_pong_no_doom_loop():
    from sigil.core.llm import detect_doom_loop

    window_a = _make_tool_call("", "read_file", file="src/big.py", offset=200, limit=25)
    window_b = _make_tool_call("", "read_file", file="src/big.py", offset=1040, limit=25)

    def args_of(tc):
        return tc["function"]["arguments"]

    def latest_content(messages, args):
        results = {m["tool_call_id"]: m["content"] for m in messages if m.get("role") == "tool"}
        alive = None
        for m in messages:
            for tc in m.get("tool_calls") or []:
                if tc["function"]["arguments"] == args:
                    alive = results.get(tc["id"])
        return alive

    messages = [{"role": "user", "content": "compare two regions of src/big.py"}]
    reads = 0
    for _ in range(20):
        needed = None
        for window in (window_a, window_b):
            if latest_content(messages, args_of(window)) != LONG_FILE:
                needed = window
                break
        if needed is None:
            break
        reads += 1
        tc_id = f"tc_{reads}"
        messages.append(
            _make_assistant_msg([{**needed, "id": tc_id}]),
        )
        messages.append(_make_tool_result(tc_id, LONG_FILE))
        messages.append({"role": "assistant", "content": f"step {reads}"})
        assert detect_doom_loop(messages) is None
        mask_old_tool_outputs(messages, keep_recent=6)

    assert reads <= 3


def test_detect_doom_loop_counts_key_order_variants_together():
    from sigil.core.llm import detect_doom_loop

    messages = [{"role": "user", "content": "go"}]
    variants = [
        '{"file": "a.py", "offset": 726, "limit": 30}',
        '{"file": "a.py", "limit": 30, "offset": 726}',
        '{"offset": 726, "file": "a.py", "limit": 30}',
        '{"file": "a.py", "offset": 726, "limit": 30}',
        '{"limit": 30, "offset": 726, "file": "a.py"}',
    ]
    for i, args in enumerate(variants):
        messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": f"tc_{i}", "function": {"name": "read_file", "arguments": args}}
                ],
            }
        )
        messages.append(_make_tool_result(f"tc_{i}", LONG_FILE))

    assert detect_doom_loop(messages) is not None


def test_detect_doom_loop_start_ignores_prefix():
    from sigil.core.llm import detect_doom_loop

    messages = [{"role": "user", "content": "go"}]
    for i in range(5):
        messages.append(
            _make_assistant_msg([_make_tool_call(f"tc_{i}", "read_file", file="a.py", offset=726)])
        )
        messages.append(_make_tool_result(f"tc_{i}", LONG_FILE))
    recovery_index = len(messages)
    messages.append({"role": "user", "content": "stop repeating"})
    messages.append(_make_assistant_msg([_make_tool_call("tc_new", "read_file", file="b.py")]))
    messages.append(_make_tool_result("tc_new", LONG_FILE))

    assert detect_doom_loop(messages) is not None
    assert detect_doom_loop(messages, start=recovery_index) is None


@pytest.fixture(autouse=True)
def _clean_traces():
    reset_traces()
    reset_usage()
    yield
    _traces.clear()


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


async def test_check_llm_health_success():
    from sigil.core.llm import check_llm_health

    mock = AsyncMock(return_value=_mock_response())
    with patch("sigil.core.llm.litellm.acompletion", mock):
        ok, err = await check_llm_health("anthropic/claude-sonnet-4-6")
    assert ok is True
    assert err is None
    mock.assert_awaited_once()


async def test_check_llm_health_failure():
    from sigil.core.llm import check_llm_health
    from litellm.exceptions import APIConnectionError

    error = APIConnectionError(message="connection refused", model="test", llm_provider="anthropic")
    mock = AsyncMock(side_effect=error)
    with patch("sigil.core.llm.litellm.acompletion", mock):
        ok, err = await check_llm_health("bad-model")
    assert ok is False
    assert "connection refused" in err


async def test_check_llm_health_timeout():
    from sigil.core.llm import check_llm_health

    mock = AsyncMock(side_effect=asyncio.TimeoutError())
    with patch("sigil.core.llm.litellm.acompletion", mock):
        ok, err = await check_llm_health("slow-model", timeout=5)
    assert ok is False
    assert err is not None


async def test_check_llm_health_timeout():
    from sigil.core.llm import check_llm_health

    mock = AsyncMock(side_effect=asyncio.TimeoutError())
    with patch("sigil.core.llm.litellm.acompletion", mock):
        ok, err = await check_llm_health("slow-model", timeout=1)
    assert ok is False
    assert err
