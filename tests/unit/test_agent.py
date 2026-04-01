from unittest.mock import AsyncMock, patch

import pytest

from sigil.core.agent import Agent, AgentCoordinator, AgentResult, Tool, ToolResult
from sigil.core.instructions import CORRECTION_PROMPT


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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_run_does_not_inject_correction_prompt_for_success(monkeypatch):
    agent = Agent(
        label="engineer",
        model="m",
        tools=[_make_tool()],
        system_prompt="You are helpful.",
        max_rounds=2,
    )

    captured_messages = []

    async def fake_acompletion(**kwargs):
        captured_messages.append(kwargs["messages"])
        response = AsyncMock()
        response.choices = [AsyncMock()]
        response.choices[0].message.content = ""
        response.choices[0].message.tool_calls = [
            AsyncMock(id="1", function=AsyncMock(name="noop", arguments="{}"))
        ]
        response.choices[0].finish_reason = "stop"
        response.usage = None
        return response

    with patch("sigil.core.agent.acompletion", side_effect=fake_acompletion):
        result = await agent.run(messages=[{"role": "user", "content": "task"}])

    assert result.stop_result is None
    assert len(captured_messages) == 1
    assert all(CORRECTION_PROMPT not in str(message) for message in captured_messages[0])
    assert all(CORRECTION_PROMPT not in str(message) for message in result.messages)


@pytest.mark.asyncio
async def test_run_injects_correction_prompt_after_error_tool_result():
    agent = Agent(
        label="engineer",
        model="m",
        tools=[_make_tool()],
        system_prompt="You are helpful.",
        max_rounds=3,
    )

    captured_messages = []
    call_count = 0

    async def fake_acompletion(**kwargs):
        nonlocal call_count
        call_count += 1
        captured_messages.append(kwargs["messages"])
        response = AsyncMock()
        response.choices = [AsyncMock()]
        if call_count == 1:
            response.choices[0].message.content = ""
            response.choices[0].message.tool_calls = [
                AsyncMock(id="1", function=AsyncMock(name="done", arguments="{}"))
            ]
            response.choices[0].finish_reason = "tool_calls"
        else:
            response.choices[0].message.content = "retry"
            response.choices[0].message.tool_calls = [
                AsyncMock(id="2", function=AsyncMock(name="done", arguments="{}"))
            ]
            response.choices[0].finish_reason = "stop"
        response.usage = None
        return response

    async def failing_handler(args: dict) -> ToolResult:
        return ToolResult(content="bad edit", is_error=True)

    agent.remove_tool("done")
    agent.add_tool(
        Tool(
            name="done",
            description="done",
            parameters={"type": "object", "properties": {}},
            handler=failing_handler,
            mutating=True,
        )
    )

    with patch("sigil.core.agent.acompletion", side_effect=fake_acompletion):
        result = await agent.run(messages=[{"role": "user", "content": "task"}])

    assert len(captured_messages) == 2
    assert CORRECTION_PROMPT in str(captured_messages[1])
    assert CORRECTION_PROMPT not in str(result.messages)
