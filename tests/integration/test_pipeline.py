import json

import pytest

from sigil.llm import acompletion
from tests.integration.conftest import PROVIDERS, skip_if_no_key

PROVIDER_IDS = list(PROVIDERS.keys())

REPORT_TOOL = {
    "type": "function",
    "function": {
        "name": "report_finding",
        "description": "Report a finding about the code snippet.",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["bug", "style", "security"],
                },
                "description": {
                    "type": "string",
                },
                "risk": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                },
            },
            "required": ["category", "description", "risk"],
        },
    },
}

PIPELINE_PROMPT = """\
You are a code reviewer. Analyze this Python snippet and report any findings \
using the report_finding tool. Report at least one finding, then stop.

```python
import os
password = os.environ["DB_PASSWORD"]
print(f"Connecting with password: {password}")
```
"""


@pytest.mark.integration
@pytest.mark.parametrize("provider", PROVIDER_IDS, ids=PROVIDER_IDS)
async def test_pipeline_tool_loop(provider: str):
    skip_if_no_key(provider)

    model = PROVIDERS[provider]["model"]
    messages: list[dict] = [{"role": "user", "content": PIPELINE_PROMPT}]
    findings: list[dict] = []
    max_rounds = 5

    for _ in range(max_rounds):
        response = await acompletion(
            model=model,
            messages=messages,
            tools=[REPORT_TOOL],
            max_tokens=512,
            temperature=0.0,
        )

        choice = response.choices[0]

        if not choice.message.tool_calls:
            break

        messages.append(choice.message)

        for tc in choice.message.tool_calls:
            assert tc.function.name == "report_finding"
            args = json.loads(tc.function.arguments)
            assert "category" in args
            assert "description" in args
            assert "risk" in args
            assert args["category"] in ("bug", "style", "security")
            assert args["risk"] in ("low", "medium", "high")
            findings.append(args)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": f"Recorded: {args['category']} finding.",
                }
            )

    assert len(findings) >= 1, f"Expected at least one finding from {provider}"
    categories = {f["category"] for f in findings}
    assert categories & {"bug", "security"}, (
        f"Expected security or bug finding for leaked password, got {categories}"
    )
