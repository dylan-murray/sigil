from unittest.mock import AsyncMock, patch
from sigil.core.agent import Agent, Tool, ToolResult

async def test_doom_loop_strategy_pivot():
    # Setup a tool that always returns the same result to trigger a doom loop
    async def loop_handler(args):
        return ToolResult(content="Same result every time", stop=False)

    tool = Tool(
        name="loop_tool",
        description="A tool that loops",
        parameters={"type": "object", "properties": {"arg": {"type": "string"}}, "required": ["arg"]},
        handler=loop_handler,
    )

    agent = Agent(
        label="test-pivot",
        model="test-model",
        tools=[tool],
        system_prompt="You are a helpful assistant.",
        enable_doom_loop=True,
        max_rounds=10,
    )

    # 1. Initial call
    resp1 = AsyncMock()
    resp1.choices = [
        AsyncMock(
            finish_reason="stop",
            message=AsyncMock(
                content="",
                tool_calls=[
                    AsyncMock(
                        id="call_1",
                        function=AsyncMock(name="loop_tool", arguments='{"arg": "test"}'),
                    )
                ],
            ),
        )
    ]

    # 2-5. Repeat the same call
    resp_repeat = AsyncMock()
    resp_repeat.choices = [
        AsyncMock(
            finish_reason="stop",
            message=AsyncMock(
                content="",
                tool_calls=[
                    AsyncMock(
                        id="call_repeat",
                        function=AsyncMock(name="loop_tool", arguments='{"arg": "test"}'),
                    )
                ],
            ),
        )
    ]

    # 6. The Pivot Analysis response
    resp_pivot = AsyncMock()
    resp_pivot.choices = [
        AsyncMock(
            finish_reason="stop",
            message=AsyncMock(
                content="Analysis: I assumed X. Strategy: Try Y.",
                tool_calls=[],
            ),
        )
    ]

    # 7. Final response after pivot
    resp_final = AsyncMock()
    resp_final.choices = [
        AsyncMock(
            finish_reason="stop",
            message=AsyncMock(content="I have pivoted and now I am done.", tool_calls=[]),
        )
    ]

    # Sequence of responses for acompletion
    # The agent will call acompletion:
    # - Round 1: resp1
    # - Round 2: resp_repeat
    # - Round 3: resp_repeat
    # - Round 4: resp_repeat
    # - Round 5: resp_repeat
    # - Round 6: detect_doom_loop triggers -> _handle_strategy_pivot calls acompletion -> resp_pivot
    # - Round 6 (continued): agent calls acompletion again -> resp_final
    responses = [resp1, resp_repeat, resp_repeat, resp_repeat, resp_repeat, resp_pivot, resp_final]

    async def mock_acompletion(**kwargs):
        if not responses:
            return resp_final
        return responses.pop(0)

    with patch("sigil.core.agent.acompletion", side_effect=mock_acompletion):
        result = await agent.run(messages=[{"role": "user", "content": "Start loop"}])

    assert result.pivoted is True
    assert result.rounds >= 6
