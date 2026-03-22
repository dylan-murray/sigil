# Integration Tests

Real LLM API calls against live providers via litellm. These cost tokens — run them intentionally, not on every push.

## Running

```bash
# All providers (skips those without keys)
uv run pytest tests/integration/ -m integration

# Single provider
uv run pytest tests/integration/ -k openai -m integration

# Exclude integration tests (default for CI)
uv run pytest -m "not integration"
```

## Required Environment Variables

| Provider  | Env Var(s)                                                    | Model Tested                                  |
|-----------|---------------------------------------------------------------|-----------------------------------------------|
| OpenAI    | `OPENAI_API_KEY`                                              | `openai/gpt-4o-mini`                          |
| Anthropic | `ANTHROPIC_API_KEY`                                           | `anthropic/claude-haiku-4-5-20251001`          |
| Gemini    | `GEMINI_API_KEY`                                              | `gemini/gemini-2.0-flash`                      |
| Bedrock   | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION_NAME` | `bedrock/anthropic.claude-3-haiku-20240307-v1:0` |
| Azure     | `AZURE_API_KEY`, `AZURE_API_BASE`                             | `azure/gpt-4o-mini`                           |
| Mistral   | `MISTRAL_API_KEY`                                             | `mistral/mistral-small-latest`                |

Tests auto-skip when the required key is missing — no failures from missing credentials.

## What's Tested

1. **Basic completion** — send a prompt, get a text response
2. **Tool use** — LLM calls a function tool and returns structured args
3. **Auth error** — invalid credentials raise an exception (not a silent failure)
4. **Pipeline loop** (`test_pipeline.py`) — multi-turn tool_use loop mirroring Sigil's analysis agent
