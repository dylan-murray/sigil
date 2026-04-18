import pytest

from sigil.core.agent import (
    Agent,
    AgentCoordinator,
    AgentHealthError,
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


async def _async_false(*a, **k):
    return False


async def _error_handler(args):
    return ToolResult(content="error", is_error=True)


async def _ok_handler(args):
    return ToolResult(content="ok")


def _make_error_tool():
    return Tool(
        name="error_tool",
        description="always errors",
        parameters={"type": "object", "properties": {}},
        handler=_error_handler,
    )


def _make_ok_tool():
    return Tool(
        name="ok_tool",
        description="always ok",
        parameters={"type": "object", "properties": {}},
        handler=_ok_handler,
    )


async def test_health_tracker_circuit_breaker_on_tool_errors(monkeypatch):
    """Agent raises AgentHealthError after health_threshold consecutive tool errors."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    call_count = 0

    async def fake_acompletion(**kw):
        nonlocal call_count
        call_count += 1
        tc = MagicMock()
        tc.id = f"c{call_count}"
        tc.function.name = "error_tool"
        tc.function.arguments = "{}"
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=None, tool_calls=[tc]),
                    finish_reason="length",
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=100,
                completion_tokens=20,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
        )

    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)
    monkeypatch.setattr("sigil.core.agent.reduce_context", _async_false)
    monkeypatch.setattr("sigil.core.agent.safe_max_tokens", lambda *a, **k: 1000)
    monkeypatch.setattr("sigil.core.agent.supports_prompt_caching", lambda m: False)
    monkeypatch.setattr("sigil.core.agent.context_pressure", lambda *a, **k: False)

    agent = Agent(
        label="test",
        model="m",
        tools=[_make_error_tool()],
        system_prompt="",
        health_threshold=0,
    )

    with pytest.raises(AgentHealthError) as exc_info:
        await agent.run(messages=[{"role": "user", "content": "go"}])

    assert "consecutive tool errors" in str(exc_info.value)
    assert exc_info.value.tracker["consecutive_errors"] >= 1


async def test_health_tracker_circuit_breaker_on_idle_rounds(monkeypatch):
    """Agent raises AgentHealthError after health_threshold rounds without output."""
    from types import SimpleNamespace

    call_count = 0

    async def fake_acompletion(**kw):
        nonlocal call_count
        call_count += 1
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

    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)
    monkeypatch.setattr("sigil.core.agent.reduce_context", _async_false)
    monkeypatch.setattr("sigil.core.agent.safe_max_tokens", lambda *a, **k: 1000)
    monkeypatch.setattr("sigil.core.agent.supports_prompt_caching", lambda m: False)
    monkeypatch.setattr("sigil.core.agent.context_pressure", lambda *a, **k: False)

    agent = Agent(
        label="test",
        model="m",
        tools=[],
        system_prompt="",
        health_threshold=0,
    )

    with pytest.raises(AgentHealthError) as exc_info:
        await agent.run(messages=[{"role": "user", "content": "go"}])

    assert "rounds without output" in str(exc_info.value)
    assert exc_info.value.tracker["idle_rounds"] >= 1


async def test_health_tracker_resets_on_success(monkeypatch):
    """Health tracker resets when tools succeed."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    call_count = 0

    async def fake_acompletion(**kw):
        nonlocal call_count
        call_count += 1
        tc = MagicMock()
        tc.id = f"c{call_count}"
        tc.function.name = "ok_tool"
        tc.function.arguments = "{}"
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=None, tool_calls=[tc]),
                    finish_reason="length",
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=100,
                completion_tokens=20,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
        )

    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)
    monkeypatch.setattr("sigil.core.agent.reduce_context", _async_false)
    monkeypatch.setattr("sigil.core.agent.safe_max_tokens", lambda *a, **k: 1000)
    monkeypatch.setattr("sigil.core.agent.supports_prompt_caching", lambda m: False)
    monkeypatch.setattr("sigil.core.agent.context_pressure", lambda *a, **k: False)

    agent = Agent(
        label="test",
        model="m",
        tools=[_make_ok_tool()],
        system_prompt="",
        health_threshold=3,
    )

    await agent.run(messages=[{"role": "user", "content": "go"}])

    assert agent._health_tracker["consecutive_errors"] == 0


async def test_tool_execute_sets_is_error_on_exception(monkeypatch):
    """Tool.execute sets is_error=True when handler raises an exception."""

    async def _raising_handler(args):
        raise ValueError("boom")

    tool = Tool(
        name="boom",
        description="boom",
        parameters={"type": "object", "properties": {}},
        handler=_raising_handler,
    )

    result = await tool.execute({})
    assert result.is_error is True
    assert "Tool error" in result.content


async def test_tool_execute_no_error_on_normal_result(monkeypatch):
    """Tool.execute does not set is_error on normal results."""
    tool = _make_ok_tool()
    result = await tool.execute({})
    assert result.is_error is False


async def test_agent_health_error_has_tracker():
    """AgentHealthError exposes the tracker dict."""
    err = AgentHealthError("test", {"consecutive_errors": 5, "idle_rounds": 0})
    assert err.tracker["consecutive_errors"] == 5
    assert err.tracker["idle_rounds"] == 0
    assert "test" in str(err)
