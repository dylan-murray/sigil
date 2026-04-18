# pytest + pytest-asyncio Test Setup with Mock Patterns

Sigil has a comprehensive test suite split into unit and integration tests.

## Unit Tests (`tests/unit/`)
- **Mocking LLMs:** Tests patch `sigil.core.llm.acompletion` to return simulated tool calls and responses.
- **Git Simulation:** Uses `tmp_path` and `subprocess` to create real git repositories for testing worktree and rebase logic.
- **Fast Feedback:** Unit tests require no API keys and run in seconds.

## Integration Tests (`tests/integration/`)
- **Live Providers:** Uses real API keys to verify compatibility with OpenAI, Anthropic, Gemini, etc.
- **Pipeline Verification:** `test_pipeline.py` runs the full analyze -> validate -> execute flow against a sample repository.

## Common Test Patterns

### Testing Tool Validation

Tools that use Pydantic models should be tested for validation errors:

```python
from sigil.core.tools import make_my_tool

async def test_my_tool_rejects_invalid_args(tmp_path):
    tool = make_my_tool(tmp_path, None)
    result = await tool.execute({"file": "bad>name.py"})  # invalid path
    assert "Invalid arguments" in result.content
    assert "file" in result.content  # field name in error
```

### Testing Tool Success Cases

```python
async def test_my_tool_valid_passthrough(tmp_path):
    target = tmp_path / "hello.py"
    target.write_text("print('hi')\n")
    tool = make_my_tool(tmp_path, None)
    result = await tool.execute({"file": "hello.py"})
    assert "print('hi')" in result.content
```

### Testing Agent Loop Behavior with Tool Calls

When testing agent continuation logic, mock `acompletion` to return responses with `finish_reason="stop"` and tool calls. The agent should continue to a second round to execute the tool calls:

```python
from types import SimpleNamespace
from unittest.mock import MagicMock

async def test_agent_continues_with_tool_calls(monkeypatch):
    tool_calls_made = []
    async def _record_handler(args):
        tool_calls_made.append(args)
        return ToolResult(content="recorded")
    tool = Tool(name="record", description="...", parameters={...}, handler=_record_handler)

    # First response: finish_reason="stop" but has tool_calls
    tc = MagicMock()
    tc.id = "c1"
    tc.function.name = "record"
    tc.function.arguments = '{"note": "hello"}'
    r1 = SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=None, tool_calls=[tc]),
            finish_reason="stop",
        )],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20, cache_read_input_tokens=0, cache_creation_input_tokens=0),
    )
    # Second response: final content, no tool calls
    r2 = SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content="all done.", tool_calls=None),
            finish_reason="stop",
        )],
        usage=SimpleNamespace(prompt_tokens=120, completion_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0),
    )

    call_count = 0
    async def fake_acompletion(**kw):
        nonlocal call_count
        call_count += 1
        return r1 if call_count == 1 else r2

    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)
    monkeypatch.setattr("sigil.core.agent.reduce_context", lambda *a, **k: False)
    monkeypatch.setattr("sigil.core.agent.safe_max_tokens", lambda *a, **k: 1000)
    monkeypatch.setattr("sigil.core.agent.supports_prompt_caching", lambda m: False)

    agent = Agent(label="test", model="m", tools=[tool], system_prompt="")
    await agent.run(messages=[{"role": "user", "content": "go"}])

    assert call_count == 2, "agent should have run round 2 after tool calls with finish_reason=stop"
    assert len(tool_calls_made) == 1
```

This pattern verifies the agent correctly interprets `finish_reason="stop"` with tool calls as a signal to continue, not exit.
