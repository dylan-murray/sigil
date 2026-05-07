from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from sigil.core.agent import (
    Agent,
    AgentCoordinator,
    AgentResult,
    Tool,
    ToolResult,
    _coerce_args,
    _looks_truncated,
)


async def _noop_handler(args):
    return ToolResult(content="ok", stop=True, result="done")


def _make_tool():
    return Tool(
        name="done",
        description="done",
        parameters={"type": "object", "properties": {}},
        handler=_noop_handler,
    )


def _stub_run(label_log):
    async def fake_run(self, *, messages=None, context=None, on_status=None):
        label_log.append(self.label)
        msgs = list(messages or [])
        msgs.append({"role": "assistant", "content": "ok"})
        return AgentResult(messages=msgs, stop_result="done")

    return fake_run


async def test_coordinator_inject_isolated(monkeypatch):
    call_log = []
    monkeypatch.setattr("sigil.core.agent.Agent.run", _stub_run(call_log))

    coord = AgentCoordinator(max_rounds=3)
    a = Agent(label="a", model="m", tools=[_make_tool()], system_prompt="")
    b = Agent(label="b", model="m", tools=[_make_tool()], system_prompt="")

    coord.add_agent("a", a, [{"role": "user", "content": "task A"}])
    coord.add_agent("b", b, [{"role": "user", "content": "task B"}])

    await coord.run_agent("a")
    await coord.run_agent("b")

    coord.inject("a", {"role": "user", "content": "feedback for A"})

    await coord.run_agent("a")
    await coord.run_agent("b")

    hist_a = coord.get_history("a")
    hist_b = coord.get_history("b")

    assert any("feedback for A" in str(m) for m in hist_a)
    assert not any("feedback for A" in str(m) for m in hist_b)
    assert len(hist_a) > len(hist_b)
    assert call_log == ["a", "b", "a", "b"]


@pytest.mark.parametrize(
    "content, expected",
    [
        ("Done.", False),
        ("All tasks completed!", False),
        ("Is that right?", False),
        ('She said "no".', False),
        ("Done.\n\n", False),
        ('{"files": {"a.md": "hello"}}', False),
        ("[1, 2, 3]", False),
        ("We\n", True),
        ("We are going to implement the", True),
        ("Let me check", True),
        ("Here is code: `foo()`", True),
        ("def needle():", True),
        ("calling `_check_behavioral_contract`", True),
        ("", False),
        ("   ", False),
    ],
)
def test_looks_truncated(content, expected):
    assert _looks_truncated(content) is expected


async def test_agent_continues_when_stop_finish_reason_with_tool_calls(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    tool_calls_made = []

    async def _record_handler(args):
        tool_calls_made.append(args)
        return ToolResult(content="recorded")

    tool = Tool(
        name="record",
        description="record a note",
        parameters={
            "type": "object",
            "properties": {"note": {"type": "string"}},
            "required": ["note"],
        },
        handler=_record_handler,
    )

    tc = MagicMock()
    tc.id = "c1"
    tc.function.name = "record"
    tc.function.arguments = '{"note": "hello"}'

    r1 = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=None, tool_calls=[tc]),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=100,
            completion_tokens=20,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )
    r2 = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="all done.", tool_calls=None),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=120,
            completion_tokens=5,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )

    call_count = 0

    async def fake_acompletion(**kw):
        nonlocal call_count
        call_count += 1
        return r1 if call_count == 1 else r2

    async def _noop_reduce(messages, model, **kw):
        return False

    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)
    monkeypatch.setattr("sigil.core.agent.reduce_context", _noop_reduce)
    monkeypatch.setattr("sigil.core.agent.safe_max_tokens", lambda *a, **k: 1000)
    monkeypatch.setattr("sigil.core.agent.supports_prompt_caching", lambda m: False)

    agent = Agent(label="test", model="m", tools=[tool], system_prompt="")
    await agent.run(messages=[{"role": "user", "content": "go"}])

    assert call_count == 2, "agent should have run round 2 after tool calls with finish_reason=stop"
    assert len(tool_calls_made) == 1


def _empty_response():
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="", tool_calls=None),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=100,
            completion_tokens=0,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )


def _tool_call_response(tool_name: str, tool_args: str = "{}", call_id: str = "c1"):
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = tool_name
    tc.function.arguments = tool_args
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=None, tool_calls=[tc]),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=120,
            completion_tokens=10,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )


def _patch_agent_deps(monkeypatch, responses: list, capture_kwargs: list | None = None):
    call_count = {"n": 0}

    async def fake_acompletion(**kw):
        if capture_kwargs is not None:
            capture_kwargs.append(kw)
        idx = call_count["n"]
        call_count["n"] += 1
        return responses[idx]

    async def _noop_reduce(messages, model, **kw):
        return False

    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)
    monkeypatch.setattr("sigil.core.agent.reduce_context", _noop_reduce)
    monkeypatch.setattr("sigil.core.agent.safe_max_tokens", lambda *a, **k: 1000)
    monkeypatch.setattr("sigil.core.agent.supports_prompt_caching", lambda m: False)
    return call_count


async def test_empty_response_nudge_recovers(monkeypatch):
    async def _done_handler(args):
        return ToolResult(content="ok", stop=True, result="done")

    tool = Tool(
        name="done",
        description="done",
        parameters={"type": "object", "properties": {}},
        handler=_done_handler,
    )

    responses = [_empty_response(), _tool_call_response("done")]
    call_count = _patch_agent_deps(monkeypatch, responses)

    agent = Agent(label="test", model="m", tools=[tool], system_prompt="")
    result = await agent.run(messages=[{"role": "user", "content": "go"}])

    assert call_count["n"] == 2
    assert result.stop_result == "done"
    nudges = [
        m
        for m in result.messages
        if m.get("role") == "user" and "empty" in str(m.get("content", "")).lower()
    ]
    assert len(nudges) == 1, "expected one empty-response nudge injected between rounds"


async def test_empty_response_budget_tolerates_two(monkeypatch):
    async def _done_handler(args):
        return ToolResult(content="ok", stop=True, result="done")

    tool = Tool(
        name="done",
        description="done",
        parameters={"type": "object", "properties": {}},
        handler=_done_handler,
    )

    responses = [_empty_response(), _empty_response(), _tool_call_response("done")]
    call_count = _patch_agent_deps(monkeypatch, responses)

    agent = Agent(label="test", model="m", tools=[tool], system_prompt="")
    result = await agent.run(messages=[{"role": "user", "content": "go"}])

    assert call_count["n"] == 3
    assert result.stop_result == "done"
    nudges = [
        m
        for m in result.messages
        if m.get("role") == "user" and "empty" in str(m.get("content", "")).lower()
    ]
    assert len(nudges) == 2, "expected two nudges within the content_only_misses<2 budget"


async def test_empty_response_then_forced_final_tool(monkeypatch):
    async def _read_handler(args):
        return ToolResult(content="file contents")

    async def _finalize_handler(args):
        return ToolResult(content="submitted", stop=True, result="submitted")

    read_tool = Tool(
        name="read_file",
        description="read a file",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        handler=_read_handler,
    )
    finalize_tool = Tool(
        name="finalize",
        description="finalize",
        parameters={"type": "object", "properties": {}},
        handler=_finalize_handler,
    )

    responses = [
        _tool_call_response("read_file", tool_args='{"path": "a.md"}', call_id="c1"),
        _empty_response(),
        _tool_call_response("finalize", call_id="c2"),
    ]
    seen_kwargs: list = []
    call_count = _patch_agent_deps(monkeypatch, responses, capture_kwargs=seen_kwargs)

    agent = Agent(
        label="test",
        model="m",
        tools=[read_tool, finalize_tool],
        system_prompt="",
        max_rounds=3,
        forced_final_tool="finalize",
    )
    result = await agent.run(messages=[{"role": "user", "content": "go"}])

    assert call_count["n"] == 3, "agent should survive the empty middle round and reach round 3"
    assert result.stop_result == "submitted"
    assert seen_kwargs[-1].get("tool_choice") == {
        "type": "function",
        "function": {"name": "finalize"},
    }, "forced tool_choice must activate on the final round"


async def test_reduce_context_not_called_below_pressure(monkeypatch):
    async def _done_handler(args):
        return ToolResult(content="ok", stop=True, result="done")

    tool = Tool(
        name="done",
        description="done",
        parameters={"type": "object", "properties": {}},
        handler=_done_handler,
    )

    reduce_calls: list[dict] = []

    async def counting_reduce(messages, model, **kw):
        reduce_calls.append(kw)
        return False

    responses = [_tool_call_response("done"), _empty_response()]
    call_count = {"n": 0}

    async def sequenced_acompletion(**kw):
        idx = call_count["n"]
        call_count["n"] += 1
        return responses[idx]

    monkeypatch.setattr("sigil.core.agent.acompletion", sequenced_acompletion)
    monkeypatch.setattr("sigil.core.agent.reduce_context", counting_reduce)
    monkeypatch.setattr("sigil.core.agent.context_pressure", lambda *a, **k: False)
    monkeypatch.setattr("sigil.core.agent.safe_max_tokens", lambda *a, **k: 1000)
    monkeypatch.setattr("sigil.core.agent.supports_prompt_caching", lambda m: False)

    agent = Agent(label="test", model="m", tools=[tool], system_prompt="")
    await agent.run(messages=[{"role": "user", "content": "go"}])

    assert reduce_calls == [], (
        "reduce_context must not run below pressure — its masking strips tool results "
        "mid-conversation and causes engineers to re-read the same file repeatedly. "
        "Only the pressure-gated and ContextOverflowError-recovery paths should call it."
    )


class TestCoerceArgs:
    def test_string_integer_to_int(self):
        schema = {"type": "object", "properties": {"count": {"type": "integer"}}}
        result = _coerce_args({"count": "42"}, schema)
        assert result["count"] == 42
        assert isinstance(result["count"], int)

    def test_string_float_to_number(self):
        schema = {"type": "object", "properties": {"ratio": {"type": "number"}}}
        result = _coerce_args({"ratio": "3.14"}, schema)
        assert result["ratio"] == pytest.approx(3.14)
        assert isinstance(result["ratio"], float)

    def test_string_true_to_bool(self):
        schema = {"type": "object", "properties": {"flag": {"type": "boolean"}}}
        result = _coerce_args({"flag": "true"}, schema)
        assert result["flag"] is True

    def test_string_false_to_bool(self):
        schema = {"type": "object", "properties": {"flag": {"type": "boolean"}}}
        result = _coerce_args({"flag": "false"}, schema)
        assert result["flag"] is False

    def test_string_bool_capitalized(self):
        schema = {"type": "object", "properties": {"flag": {"type": "boolean"}}}
        result = _coerce_args({"flag": "True"}, schema)
        assert result["flag"] is True
        result = _coerce_args({"flag": "False"}, schema)
        assert result["flag"] is False

    def test_missing_field_with_default(self):
        schema = {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 10}},
        }
        result = _coerce_args({}, schema)
        assert result["limit"] == 10

    def test_failed_int_coersion_preserves_original(self):
        schema = {"type": "object", "properties": {"count": {"type": "integer"}}}
        result = _coerce_args({"count": "not_a_number"}, schema)
        assert result["count"] == "not_a_number"

    def test_failed_float_coercion_preserves_original(self):
        schema = {"type": "object", "properties": {"ratio": {"type": "number"}}}
        result = _coerce_args({"ratio": "abc"}, schema)
        assert result["ratio"] == "abc"

    def test_failed_bool_coercion_preserves_original(self):
        schema = {"type": "object", "properties": {"flag": {"type": "boolean"}}}
        result = _coerce_args({"flag": "yes"}, schema)
        assert result["flag"] == "yes"

    def test_already_correct_types_pass_through(self):
        schema = {
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
                "ratio": {"type": "number"},
                "flag": {"type": "boolean"},
                "name": {"type": "string"},
            },
        }
        args = {"count": 42, "ratio": 3.14, "flag": True, "name": "test"}
        result = _coerce_args(args, schema)
        assert result == args

    def test_empty_properties_is_noop(self):
        result = _coerce_args({"a": 1}, {"type": "object"})
        assert result == {"a": 1}

    def test_no_schema_properties_is_noop(self):
        result = _coerce_args({"a": 1}, {})
        assert result == {"a": 1}

    def test_does_not_mutate_input(self):
        schema = {"type": "object", "properties": {"count": {"type": "integer"}}}
        args = {"count": "42"}
        result = _coerce_args(args, schema)
        assert args["count"] == "42"
        assert result["count"] == 42

    def test_extra_args_not_in_schema_preserved(self):
        schema = {"type": "object", "properties": {"count": {"type": "integer"}}}
        result = _coerce_args({"count": "5", "extra": "value"}, schema)
        assert result["count"] == 5
        assert result["extra"] == "value"

    def test_string_integer_with_float_value(self):
        schema = {"type": "object", "properties": {"count": {"type": "integer"}}}
        result = _coerce_args({"count": "42.0"}, schema)
        assert result["count"] == "42.0"

    def test_integer_string_to_float(self):
        schema = {"type": "object", "properties": {"ratio": {"type": "number"}}}
        result = _coerce_args({"ratio": "7"}, schema)
        assert result["ratio"] == 7.0
        assert isinstance(result["ratio"], float)
