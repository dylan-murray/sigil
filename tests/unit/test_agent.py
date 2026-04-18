from dataclasses import dataclass

from sigil.core.agent import (
    Agent,
    AgentCoordinator,
    AgentResult,
    Tool,
    ToolResult,
    _normalize_message,
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


@dataclass
class MockMessage:
    role: str | None = None
    content: str | None = None

    def __init__(self, role=None, content=None, model_dump=None):
        self.role = role
        self.content = content
        if model_dump is not None:
            self.model_dump = model_dump


def test_normalize_message():
    # Standard dictionary
    dict_msg = {"role": "user", "content": "hello"}
    assert _normalize_message(dict_msg) == dict_msg

    # Object with callable model_dump
    class Dumpable:
        def model_dump(self, exclude_none=True):
            return {"role": "assistant", "content": "dumped"}

    dumpable = Dumpable()
    assert _normalize_message(dumpable) == {"role": "assistant", "content": "dumped"}

    # Object with non-callable model_dump
    class NonDumpable:
        model_dump = "not a function"
        role = "user"
        content = "safe"

    non_dumpable = NonDumpable()
    assert _normalize_message(non_dumpable) == {"role": "user", "content": "safe"}

    # Object with None values
    class NoneValues:
        role = None
        content = None

    none_vals = NoneValues()
    assert _normalize_message(none_vals) == {"role": "assistant", "content": ""}

    # Object missing attributes
    class MissingAttrs:
        pass

    missing = MissingAttrs()
    assert _normalize_message(missing) == {"role": "assistant", "content": ""}
