# Sigil — Autonomous Repo Improvement Agent (Python 3.11/litellm/uv): Tech Stack, Build and Test

Sigil is an autonomous AI agent designed to watch a code repository, identify areas for improvement, and automatically ship pull requests or file issues. It's built with a focus on safety, small, incremental changes, and continuous learning.

## Tech Stack

- **Language:** Python 3.11+
- **LLM Integration:** [LiteLLM](https://docs.litellm.ai/) for unified API access to 100+ models (OpenAI, Anthropic, Gemini, DeepSeek, etc.)
- **Package Management & Environment:** [uv](https://github.com/astral-sh/uv) for fast dependency resolution and package installation.
- **Git Operations:** `gitpython` for programmatic interaction with Git repositories.
- **GitHub API:** `PyGithub` for interacting with GitHub (creating PRs, issues, labels).
- **Testing:** `pytest` with `pytest-asyncio` for asynchronous code testing.
- **Configuration:** `Pydantic` for robust settings management.
- **CLI:** `Typer` for building the command-line interface.
- **Diffing:** `difflib` for generating and parsing code differences.

## Build and Test

### Installation

Sigil is distributed as a Python package. The recommended installation method is using `uv`:

```bash
uv tool install sigil-py
```

This installs the `sigil` command-line tool into your `PATH`.

### Development Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/dylan-murray/sigil.git
   cd sigil
   ```

2. **Create a virtual environment and install dependencies:**
   ```bash
   uv venv
   source .venv/bin/activate
   uv pip install -e '.[dev,test]'
   ```

3. **Run tests:**
   ```bash
   pytest
   ```

### Running Sigil

To initialize Sigil in a repository and run it:

```bash
# Set your model provider's API key
export ANTHROPIC_API_KEY=...   # or OPENAI_API_KEY, GEMINI_API_KEY, etc.

# Navigate to your repository
cd your-repo

# Initialize Sigil configuration (creates .sigil/config.yml)
sigil init

# Run Sigil (or use --dry-run to analyze without opening PRs)
sigil run
```

### Versioning

Sigil follows [Semantic Versioning](https://semver.org/). The version is managed in `pyproject.toml` and `sigil/__init__.py`.
