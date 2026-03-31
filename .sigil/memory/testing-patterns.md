# pytest + pytest-asyncio Test Setup with Mock Patterns

Sigil has a comprehensive test suite split into unit and integration tests.

## Unit Tests (`tests/unit/`)
- **Mocking LLMs:** Tests patch `sigil.core.llm.acompletion` to return simulated tool calls and responses.
- **Git Simulation:** Uses `tmp_path` and `subprocess` to create real git repositories for testing worktree and rebase logic.
- **Fast Feedback:** Unit tests require no API keys and run in seconds.

## Integration Tests (`tests/integration/`)
- **Live Providers:** Uses real API keys to verify compatibility with OpenAI, Anthropic, Gemini, etc.
- **Pipeline Verification:** `test_pipeline.py` runs the full analyze -> validate -> execute flow against a
