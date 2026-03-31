# Sigil — Autonomous Repo Improvement Agent (Python 3.11/litellm/uv)

Sigil is an autonomous coding agent that proactively improves repositories by finding bugs, refactoring code, and implementing features while developers sleep. It uses a multi-stage async pipeline to scan codebases and ship small, safe pull requests.

## Tech Stack
- **Language:** Python 3.11+
- **Package Manager:** `uv` (Astral)
- **LLM Client:** `litellm` (supports 100+ providers like Anthropic, OpenAI, Gemini)
- **CLI:** `typer` + `rich` for terminal UI
- **GitHub:** `PyGithub` for PR and issue management
- **Async:** `asyncio` throughout for parallel execution

## Build and Test
```bash
# Setup
uv sync

# Run Analysis
uv run sigil run --repo . --dry-run

# Run Tests
uv run pytest tests/unit/ -v
uv run pytest tests/integration/ -m integration

# Linting
uv run ruff check .
uv run ruff format .
```
