# Sigil — Autonomous Repo Improvement Agent (Python 3.11/litellm/uv): Tech Stack, Build and Test

## Tech Stack

- **Language:** Python 3.11+
- **Package Manager:** `uv` (fast, modern Python package manager)
- **LLM Integration:** `litellm` (unified API for various LLM providers)
- **CLI Framework:** `typer` (built on `click` and `pydantic`)
- **Git Operations:** `gitpython` (Python interface to Git)
- **Type Checking:** `mypy`
- **Linting:** `ruff`
- **Testing:** `pytest`, `pytest-asyncio`
- **Code Formatting:** `black`
- **Static Analysis:** `semgrep`

## Build and Test

### Installation

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install project dependencies
uv sync

# Install sigil as a uv tool
uv tool install sigil-py
```

### Running Tests

```bash
uv run pytest
```

### Linting and Formatting

```bash
uv run ruff check .
uv run black .
```

### Type Checking

```bash
uv run mypy .
```

### Static Analysis

```bash
uv run semgrep --config auto
```
