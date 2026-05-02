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
    get_stage_usage,
    get_traces,
    get_usage,
    mask_old_tool_outputs,
    reset_traces,
    reset_usage,
    set_token_budget,
    write_trace_file,
)
from sigil.core.llm import BudgetExceededError


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


class TestGetStageUsage:
    def test_returns_zeroes_when_no_calls(self):
        reset_usage()
        import sigil.core.llm as llm_mod

        llm_mod._stage_start_time = 1000.0
        llm_mod._stage_start_usage = (0, 0, 0, 0, 0, 0.0)

        with patch("sigil.core.llm.time.monotonic", return_value=1000.0):
            result = get_stage_usage()

        assert result.prompt_tokens == 0
        assert result.completion_tokens == 0
        assert result.cache_read_tokens == 0
        assert result.cache_creation_tokens == 0
        assert result.calls == 0
        assert result.cost_usd == 0.0
        assert result.latency_ms == 0.0

    async def test_returns_delta_after_calls(self):
        reset_usage()
        import sigil.core.llm as llm_mod

        llm_mod._stage_start_time = 1000.0
        llm_mod._stage_start_usage = (0, 0, 0, 0, 0, 0.0)

        mock = AsyncMock(return_value=_mock_response(prompt_tok=500, completion_tok=200))
        with (
            patch("sigil.core.llm.litellm.acompletion", mock),
            patch("sigil.core.llm.litellm.completion_cost", return_value=0.02),
        ):
            await acompletion(label="test", model="anthropic/claude-sonnet-4-6", messages=[])

        with patch("sigil.core.llm.time.monotonic", return_value=1500.0):
            result = get_stage_usage()

        assert result.prompt_tokens == 500
        assert result.completion_tokens == 200
        assert result.calls == 1
        assert result.cost_usd == pytest.approx(0.02)
        assert result.latency_ms == 500000.0

    async def test_resets_counters_after_call(self):
        reset_usage()
        import sigil.core.llm as llm_mod

        llm_mod._stage_start_time = 1000.0
        llm_mod._stage_start_usage = (0, 0, 0, 0, 0, 0.0)

        mock = AsyncMock(return_value=_mock_response(prompt_tok=300, completion_tok=100))
        with (
            patch("sigil.core.llm.litellm.acompletion", mock),
            patch("sigil.core.llm.litellm.completion_cost", return_value=0.01),
        ):
            await acompletion(label="test", model="anthropic/claude-sonnet-4-6", messages=[])

        with patch("sigil.core.llm.time.monotonic", return_value=2000.0):
            first = get_stage_usage()

        assert first.prompt_tokens == 300

        with patch("sigil.core.llm.time.monotonic", return_value=2000.0):
            second = get_stage_usage()

        assert second.prompt_tokens == 0
        assert second.completion_tokens == 0
        assert second.calls == 0
        assert second.cost_usd == 0.0
        assert second.latency_ms == 0.0

    def test_reports_nonzero_latency(self):
        reset_usage()
        import sigil.core.llm as llm_mod

        llm_mod._stage_start_time = 100.0
        llm_mod._stage_start_usage = (0, 0, 0, 0, 0, 0.0)

        with patch("sigil.core.llm.time.monotonic", return_value=350.0):
            result = get_stage_usage()

        assert result.latency_ms == 250000.0


class TestTokenBudget:
    def test_check_token_budget_raises_when_exceeded(self):
        reset_usage()
        import sigil.core.llm as llm_mod

        llm_mod._max_tokens = 1000
        llm_mod._usage.prompt_tokens = 600
        llm_mod._usage.completion_tokens = 500

        with pytest.raises(BudgetExceededError, match="Token budget exceeded"):
            llm_mod._check_token_budget()

    def test_check_token_budget_does_not_raise_when_under(self):
        reset_usage()
        import sigil.core.llm as llm_mod

        llm_mod._max_tokens = 1000
        llm_mod._usage.prompt_tokens = 400
        llm_mod._usage.completion_tokens = 300

        llm_mod._check_token_budget()

    def test_set_token_budget_zero_disables_check(self):
        reset_usage()
        import sigil.core.llm as llm_mod

        set_token_budget(0)
        llm_mod._usage.prompt_tokens = 999_999
        llm_mod._usage.completion_tokens = 999_999

        llm_mod._check_token_budget()

    def test_set_token_budget_positive_sets_limit(self):
        import sigil.core.llm as llm_mod

        set_token_budget(5000)
        assert llm_mod._max_tokens == 5000

    async def test_token_budget_checked_in_acompletion(self):
        reset_usage()
        import sigil.core.llm as llm_mod

        set_token_budget(100)
        llm_mod._usage.prompt_tokens = 60
        llm_mod._usage.completion_tokens = 50

        mock = AsyncMock(return_value=_mock_response(prompt_tok=10, completion_tok=5))
        with (
            patch("sigil.core.llm.litellm.acompletion", mock),
            patch("sigil.core.llm.litellm.completion_cost", return_value=0.001),
        ):
            with pytest.raises(BudgetExceededError, match="Token budget exceeded"):
                await acompletion(label="test", model="anthropic/claude-sonnet-4-6", messages=[])
