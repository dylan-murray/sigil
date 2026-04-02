# Sigil — Autonomous Repo Improvement Agent (Python 3.11/litellm/uv): Tech Stack, Build and Test

Sigil is an autonomous agent that watches your repo, finds improvements, and ships pull requests.

## Tech Stack
- **Language:** Python 3.11+
- **Package Manager:** `uv` (for speed and reliability)
- **LLM Integration:** `litellm` (supports 100+ models, unified API)
- **CLI:** `typer`
- **Git Operations:** `gitpython`
- **GitHub API:** `pygithub`
- **Testing:** `pytest`, `pytest-asyncio`
- **Static Analysis:** `ruff`, `mypy`

## Build and Test

### Installation
```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install sigil-py as a uv tool
uv tool install sigil-py
```

### Quickstart
```bash
# Set your provider's API key
export ANTHROPIC_API_KEY=...   # or OPENAI_API_KEY, OPENROUTER_API_KEY, GEMINI_API_KEY, etc.

# Initialize Sigil in your repository
cd your-repo
sigil init                     # Creates .sigil/config.yml with all options documented

# Run Sigil
sigil run                      # or --dry-run to analyze without opening PRs
```

### Running Tests
```bash
# Install dev dependencies
uv sync --dev

# Run pytest
pytest
```

### Versioning
Sigil follows [Semantic Versioning](https://semver.org/). The current version is `1.0.1`.
