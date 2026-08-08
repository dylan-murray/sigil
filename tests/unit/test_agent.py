from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from sigil.core.agent import (
    Agent,
    AgentCoordinator,
    AgentResult,
    Tool,
    ToolResult,
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


class _AssistantMsg(SimpleNamespace):
    def model_dump(self, exclude_none: bool = False) -> dict:
        msg: dict = {"role": "assistant", "content": self.content}
        if exclude_none and msg["content"] is None:
            del msg["content"]
        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in self.tool_calls
            ]
        return msg


def _tool_call_response(tool_name: str, tool_args: str = "{}", call_id: str = "c1"):
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = tool_name
    tc.function.arguments = tool_args
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=_AssistantMsg(content=None, tool_calls=[tc]),
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


def _text_response(text):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=text, tool_calls=None),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=100,
            completion_tokens=5,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )


def _make_read_tool(executions):
    async def _handler(args):
        executions.append(args)
        return ToolResult(content="file contents here")

    return Tool(
        name="read_file",
        description="read a file",
        parameters={"type": "object", "properties": {"file": {"type": "string"}}},
        handler=_handler,
        idempotent=True,
    )


def _make_edit_tool():
    async def _handler(args):
        return ToolResult(content="Applied edit.")

    return Tool(
        name="apply_edit",
        description="edit a file",
        parameters={"type": "object", "properties": {"file": {"type": "string"}}},
        handler=_handler,
        mutating=True,
    )


async def test_repeated_read_short_circuited(monkeypatch):
    executions = []
    _patch_agent_deps(
        monkeypatch,
        [
            _tool_call_response("read_file", '{"file": "a.py", "offset": 726}', "c1"),
            _tool_call_response("read_file", '{"file": "a.py", "offset": 726}', "c2"),
            _text_response("giving up on the loop."),
        ],
    )
    agent = Agent(label="test", model="m", tools=[_make_read_tool(executions)], system_prompt="")
    result = await agent.run(messages=[{"role": "user", "content": "go"}])

    assert len(executions) == 1
    second_result = next(
        m for m in result.messages if m.get("role") == "tool" and m.get("tool_call_id") == "c2"
    )
    assert second_result["content"].startswith("Skipped:")


async def test_read_after_mutation_not_short_circuited(monkeypatch):
    executions = []
    _patch_agent_deps(
        monkeypatch,
        [
            _tool_call_response("read_file", '{"file": "a.py", "offset": 726}', "c1"),
            _tool_call_response("apply_edit", '{"file": "a.py"}', "c2"),
            _tool_call_response("read_file", '{"file": "a.py", "offset": 726}', "c3"),
            _text_response("done reviewing."),
        ],
    )
    agent = Agent(
        label="test",
        model="m",
        tools=[_make_read_tool(executions), _make_edit_tool()],
        system_prompt="",
    )
    result = await agent.run(messages=[{"role": "user", "content": "go"}])

    assert len(executions) == 2
    third_result = next(
        m for m in result.messages if m.get("role") == "tool" and m.get("tool_call_id") == "c3"
    )
    assert third_result["content"] == "file contents here"


async def test_key_order_jitter_still_short_circuited(monkeypatch):
    executions = []
    _patch_agent_deps(
        monkeypatch,
        [
            _tool_call_response("read_file", '{"file": "a.py", "offset": 726, "limit": 30}', "c1"),
            _tool_call_response("read_file", '{"file": "a.py", "limit": 30, "offset": 726}', "c2"),
            _text_response("moving on."),
        ],
    )
    agent = Agent(label="test", model="m", tools=[_make_read_tool(executions)], system_prompt="")
    result = await agent.run(messages=[{"role": "user", "content": "go"}])

    assert len(executions) == 1
    second_result = next(
        m for m in result.messages if m.get("role") == "tool" and m.get("tool_call_id") == "c2"
    )
    assert second_result["content"].startswith("Skipped:")


async def test_different_window_not_short_circuited(monkeypatch):
    executions = []
    _patch_agent_deps(
        monkeypatch,
        [
            _tool_call_response("read_file", '{"file": "a.py", "offset": 200}', "c1"),
            _tool_call_response("read_file", '{"file": "a.py", "offset": 400}', "c2"),
            _text_response("finished paging."),
        ],
    )
    agent = Agent(label="test", model="m", tools=[_make_read_tool(executions)], system_prompt="")
    await agent.run(messages=[{"role": "user", "content": "go"}])

    assert len(executions) == 2


async def test_stateful_tool_repeat_not_short_circuited(monkeypatch):
    executions = []

    async def _progress_handler(args):
        executions.append(args)
        if len(executions) >= 2:
            return ToolResult(content="Stopping.", stop=True, result="done")
        return ToolResult(content="call task_progress again when complete")

    progress_tool = Tool(
        name="task_progress",
        description="report progress",
        parameters={"type": "object", "properties": {"summary": {"type": "string"}}},
        handler=_progress_handler,
    )
    _patch_agent_deps(
        monkeypatch,
        [
            _tool_call_response("task_progress", '{"summary": "done"}', "c1"),
            _tool_call_response("task_progress", '{"summary": "done"}', "c2"),
        ],
    )
    agent = Agent(label="test", model="m", tools=[progress_tool], system_prompt="")
    result = await agent.run(messages=[{"role": "user", "content": "go"}])

    assert len(executions) == 2
    assert result.stop_result == "done"


async def test_unknown_tool_repeat_not_short_circuited(monkeypatch):
    _patch_agent_deps(
        monkeypatch,
        [
            _tool_call_response("mcp__ext__fetch", '{"q": "x"}', "c1"),
            _tool_call_response("mcp__ext__fetch", '{"q": "x"}', "c2"),
            _text_response("done fetching."),
        ],
    )
    agent = Agent(label="test", model="m", tools=[], system_prompt="")
    result = await agent.run(messages=[{"role": "user", "content": "go"}])

    tool_msgs = [m for m in result.messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 2
    assert all(m["content"] == "Unknown tool." for m in tool_msgs)


def _make_done_tool():
    async def _handler(args):
        return ToolResult(content="ok", stop=True, result="done")

    return Tool(
        name="done",
        description="done",
        parameters={"type": "object", "properties": {}},
        handler=_handler,
    )


async def test_doom_recovery_nudge_then_success(monkeypatch):
    executions = []
    responses = [
        _tool_call_response("read_file", '{"file": "a.py", "offset": 726}', f"c{i}")
        for i in range(1, 6)
    ]
    responses.append(_tool_call_response("done", "{}", "c6"))
    _patch_agent_deps(monkeypatch, responses)

    agent = Agent(
        label="test",
        model="m",
        tools=[_make_read_tool(executions), _make_done_tool()],
        system_prompt="",
    )
    result = await agent.run(messages=[{"role": "user", "content": "go"}])

    assert result.doom_loop is False
    assert result.stop_result == "done"
    nudges = [
        m
        for m in result.messages
        if m.get("role") == "user" and "Do not repeat that call" in str(m.get("content", ""))
    ]
    assert len(nudges) == 1


async def test_doom_reabort_after_failed_recovery(monkeypatch):
    executions = []
    responses = [
        _tool_call_response("read_file", '{"file": "a.py", "offset": 726}', f"c{i}")
        for i in range(1, 11)
    ]
    _patch_agent_deps(monkeypatch, responses)

    agent = Agent(
        label="test",
        model="m",
        tools=[_make_read_tool(executions)],
        system_prompt="",
        max_rounds=15,
    )
    result = await agent.run(messages=[{"role": "user", "content": "go"}])

    assert result.doom_loop is True
    nudges = [
        m
        for m in result.messages
        if m.get("role") == "user" and "Do not repeat that call" in str(m.get("content", ""))
    ]
    assert len(nudges) == 1


async def test_doom_detection_survives_compaction_after_recovery(monkeypatch):
    executions = []
    responses = [
        _tool_call_response("read_file", '{"file": "a.py", "offset": 726}', f"c{i}")
        for i in range(1, 11)
    ]
    _patch_agent_deps(monkeypatch, responses)

    compacted = {"done": False}

    def fake_pressure(*a, **kw):
        return not compacted["done"] and any(
            "Do not repeat that call" in str(m.get("content", ""))
            for m in a[1]
            if isinstance(m, dict)
        )

    async def fake_reduce(messages, model, **kw):
        keep = messages[-4:]
        messages.clear()
        messages.append({"role": "user", "content": "[conversation summary]"})
        messages.extend(keep)
        compacted["done"] = True
        return True

    monkeypatch.setattr("sigil.core.agent.context_pressure", fake_pressure)
    monkeypatch.setattr("sigil.core.agent.reduce_context", fake_reduce)

    agent = Agent(
        label="test",
        model="m",
        tools=[_make_read_tool(executions)],
        system_prompt="",
        max_rounds=15,
    )
    result = await agent.run(messages=[{"role": "user", "content": "go"}])

    assert compacted["done"] is True
    assert result.doom_loop is True


async def test_doom_recovery_denied_on_final_round(monkeypatch):
    executions = []
    responses = [
        _tool_call_response("read_file", '{"file": "a.py", "offset": 726}', f"c{i}")
        for i in range(1, 6)
    ]
    _patch_agent_deps(monkeypatch, responses)

    agent = Agent(
        label="test",
        model="m",
        tools=[_make_read_tool(executions)],
        system_prompt="",
        max_rounds=6,
    )
    result = await agent.run(messages=[{"role": "user", "content": "go"}])

    assert result.doom_loop is True
    nudges = [
        m
        for m in result.messages
        if m.get("role") == "user" and "Do not repeat that call" in str(m.get("content", ""))
    ]
    assert len(nudges) == 0
