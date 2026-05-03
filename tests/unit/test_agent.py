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


@pytest.mark.parametrize(
    "schema_type,value,expected",
    [
        ("integer", "42", 42),
        ("integer", " 7 ", 7),
        ("boolean", "true", True),
        ("boolean", "True", True),
        ("boolean", "false", False),
        ("boolean", "FALSE", False),
        ("number", "3.14", 3.14),
        ("number", " 2.0 ", 2.0),
        ("array", "[1, 2, 3]", [1, 2, 3]),
        ("array", '["a", "b"]', ["a", "b"]),
    ],
)
def test_coerce_args_basic_coercion(schema_type, value, expected):
    parameters = {
        "type": "object",
        "properties": {"field": {"type": schema_type}},
        "required": ["field"],
    }
    args = {"field": value}
    coerced, err = _coerce_args(args, parameters)
    assert err is None
    assert coerced["field"] == expected


@pytest.mark.parametrize(
    "schema_type,value",
    [
        ("integer", "not_a_number"),
        ("integer", "12.5"),
        ("number", "abc"),
        ("boolean", "yes"),
        ("array", "not json"),
        ("array", "{}"),
    ],
)
def test_coerce_args_failure_returns_error(schema_type, value):
    parameters = {
        "type": "object",
        "properties": {"field": {"type": schema_type}},
        "required": ["field"],
    }
    args = {"field": value}
    coerced, err = _coerce_args(args, parameters)
    assert err is not None
    assert "field" in err


def test_coerce_args_already_correct_type_passes_through():
    parameters = {
        "type": "object",
        "properties": {
            "count": {"type": "integer"},
            "flag": {"type": "boolean"},
            "ratio": {"type": "number"},
            "items": {"type": "array"},
        },
    }
    args = {"count": 5, "flag": True, "ratio": 1.0, "items": [1, 2]}
    coerced, err = _coerce_args(args, parameters)
    assert err is None
    assert coerced == args


def test_coerce_args_fills_defaults():
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "limit": {"type": "integer", "default": 10},
        },
        "required": ["name"],
    }
    args = {"name": "test"}
    coerced, err = _coerce_args(args, parameters)
    assert err is None
    assert coerced == {"name": "test", "limit": 10}


def test_coerce_args_strips_unknown_keys():
    parameters = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }
    args = {"name": "test", "extra": "removed"}
    coerced, err = _coerce_args(args, parameters)
    assert err is None
    assert "extra" not in coerced
    assert coerced["name"] == "test"


def test_coerce_args_missing_required_returns_error():
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "count": {"type": "integer"},
        },
        "required": ["name", "count"],
    }
    args = {"name": "test"}
    coerced, err = _coerce_args(args, parameters)
    assert err is not None
    assert "count" in err


def test_coerce_args_empty_parameters():
    parameters = {"type": "object", "properties": {}}
    args = {"extra": "stuff"}
    coerced, err = _coerce_args(args, parameters)
    assert err is None
    assert coerced == {}


async def test_coerce_args_disabled(monkeypatch):
    received_args = []

    async def _capture_handler(args):
        received_args.append(dict(args))
        return ToolResult(content="ok", stop=True, result="done")

    tool = Tool(
        name="do_thing",
        description="do a thing",
        parameters={
            "type": "object",
            "properties": {"count": {"type": "integer"}},
            "required": ["count"],
        },
        handler=_capture_handler,
    )

    tc = MagicMock()
    tc.id = "c1"
    tc.function.name = "do_thing"
    tc.function.arguments = '{"count": "42"}'

    r1 = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=None, tool_calls=[tc]),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=100,
            completion_tokens=10,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )

    async def fake_acompletion(**kw):
        return r1

    async def _noop_reduce(messages, model, **kw):
        return False

    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)
    monkeypatch.setattr("sigil.core.agent.reduce_context", _noop_reduce)
    monkeypatch.setattr("sigil.core.agent.safe_max_tokens", lambda *a, **k: 1000)
    monkeypatch.setattr("sigil.core.agent.supports_prompt_caching", lambda m: False)

    agent = Agent(
        label="test",
        model="m",
        tools=[tool],
        system_prompt="",
        coerce_args=False,
    )
    await agent.run(messages=[{"role": "user", "content": "go"}])

    assert received_args[0]["count"] == "42", (
        "raw string should pass through when coerce_args=False"
    )


async def test_coerce_args_enabled_in_agent_run(monkeypatch):
    received_args = []

    async def _capture_handler(args):
        received_args.append(dict(args))
        return ToolResult(content="ok", stop=True, result="done")

    tool = Tool(
        name="do_thing",
        description="do a thing",
        parameters={
            "type": "object",
            "properties": {"count": {"type": "integer"}},
            "required": ["count"],
        },
        handler=_capture_handler,
    )

    tc = MagicMock()
    tc.id = "c1"
    tc.function.name = "do_thing"
    tc.function.arguments = '{"count": "42"}'

    r1 = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=None, tool_calls=[tc]),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=100,
            completion_tokens=10,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )

    async def fake_acompletion(**kw):
        return r1

    async def _noop_reduce(messages, model, **kw):
        return False

    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)
    monkeypatch.setattr("sigil.core.agent.reduce_context", _noop_reduce)
    monkeypatch.setattr("sigil.core.agent.safe_max_tokens", lambda *a, **k: 1000)
    monkeypatch.setattr("sigil.core.agent.supports_prompt_caching", lambda m: False)

    agent = Agent(label="test", model="m", tools=[tool], system_prompt="")
    await agent.run(messages=[{"role": "user", "content": "go"}])

    assert received_args[0]["count"] == 42, "string should be coerced to int by default"


async def test_coerce_args_validation_error_returned_to_llm(monkeypatch):
    tool = Tool(
        name="do_thing",
        description="do a thing",
        parameters={
            "type": "object",
            "properties": {"count": {"type": "integer"}},
            "required": ["count"],
        },
        handler=lambda args: ToolResult(content="ok"),
    )

    tc = MagicMock()
    tc.id = "c1"
    tc.function.name = "do_thing"
    tc.function.arguments = '{"count": "not_a_number"}'

    r1 = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=None, tool_calls=[tc]),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=100,
            completion_tokens=10,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )
    r2 = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="all done", tool_calls=None),
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

    call_count = {"n": 0}

    async def fake_acompletion(**kw):
        idx = call_count["n"]
        call_count["n"] += 1
        return [r1, r2, r2][idx]

    async def _noop_reduce(messages, model, **kw):
        return False

    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)
    monkeypatch.setattr("sigil.core.agent.reduce_context", _noop_reduce)
    monkeypatch.setattr("sigil.core.agent.safe_max_tokens", lambda *a, **k: 1000)
    monkeypatch.setattr("sigil.core.agent.supports_prompt_caching", lambda m: False)
    monkeypatch.setattr("sigil.core.agent.context_pressure", lambda *a, **k: False)

    agent = Agent(label="test", model="m", tools=[tool], system_prompt="")
    result = await agent.run(messages=[{"role": "user", "content": "go"}])

    tool_msgs = [m for m in result.messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert "count" in tool_msgs[0]["content"]
    assert "integer" in tool_msgs[0]["content"]
