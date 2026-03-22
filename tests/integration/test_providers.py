import json

import pytest

from sigil.llm import acompletion
from tests.integration.conftest import (
    PROVIDERS,
    SIMPLE_TOOL,
    completion_messages,
    model_for,
    skip_if_no_key,
    tool_use_messages,
)

PROVIDER_IDS = list(PROVIDERS.keys())


@pytest.mark.integration
@pytest.mark.parametrize("provider", PROVIDER_IDS, ids=PROVIDER_IDS)
async def test_basic_completion(provider: str):
    skip_if_no_key(provider)
    response = await acompletion(
        model=model_for(provider),
        messages=completion_messages(),
        max_tokens=32,
    )
    content = response.choices[0].message.content
    assert content is not None
    assert len(content) > 0


@pytest.mark.integration
@pytest.mark.parametrize("provider", PROVIDER_IDS, ids=PROVIDER_IDS)
async def test_tool_use(provider: str):
    skip_if_no_key(provider)
    response = await acompletion(
        model=model_for(provider),
        messages=tool_use_messages(),
        tools=[SIMPLE_TOOL],
        max_tokens=128,
    )
    msg = response.choices[0].message
    assert msg.tool_calls is not None
    assert len(msg.tool_calls) > 0
    tc = msg.tool_calls[0]
    assert tc.function.name == "report_result"
    args = json.loads(tc.function.arguments)
    assert "answer" in args


@pytest.mark.integration
@pytest.mark.parametrize("provider", PROVIDER_IDS, ids=PROVIDER_IDS)
async def test_auth_error(provider: str):
    skip_if_no_key(provider)
    error_kwargs = PROVIDERS[provider]["auth_error_kwargs"]
    with pytest.raises(Exception) as exc_info:
        await acompletion(
            model=model_for(provider),
            messages=completion_messages(),
            max_tokens=32,
            **error_kwargs,
        )
    assert exc_info.value is not None
