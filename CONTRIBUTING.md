# Contributing to Sigil

Thanks for your interest in contributing! Here's how to get started.

## Setup

```bash
git clone https://github.com/dylan-murray/sigil.git
cd sigil
uv sync
```

## Development Workflow

1. Create a branch from `main`
2. Make your changes
3. Run lint and tests:
   ```bash
   uv run ruff check .
   uv run ruff format .
   uv run pytest tests/unit/ -x -q
   ```
4. Open a PR against `main`

## Code Standards

- **Python 3.11+** with type hints on all function signatures
- **No comments** unless explicitly asked — code should be self-documenting
- **f-strings** only — no `.format()` or `%` formatting
- **`X | None`** (PEP 604) — not `Optional[X]`
- **Absolute imports** only
- **`logger`** for logging variables (not `log`)
- Always run `uv run ruff format .` as the last step

## Testing

- Framework: **pytest** with **pytest-asyncio**
- Run: `uv run pytest tests/unit/ -x -q`
- Use `unittest.mock.patch` over `monkeypatch`
- Use `@pytest.mark.parametrize` over duplicate test functions
- Integration tests (real LLM calls) are marked with `@pytest.mark.integration`

## PR Guidelines

- Keep PRs small and focused — one concern per PR
- All CI checks must pass (lint, test, Semgrep)
- PRs require CODEOWNER approval before merge

## Reporting Issues

Use [GitHub Issues](https://github.com/dylan-murray/sigil/issues) for bug reports and feature requests.
