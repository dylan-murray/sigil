# Dependencies — Sigil

## Package Manager

**uv** — Modern Python package manager. Fast dependency resolution and virtual environment management.

```bash
uv sync          # Install all deps
uv add <pkg>     # Add a dependency
uv run <cmd>     # Run a command in the venv
uv tool install sigil  # Install as a global tool
```

## Runtime Dependencies

### CLI & Terminal
| Package | Version | Purpose |
|---------|---------|---------|
| `typer` | >=0.15 | CLI framework with automatic help generation and type validation |
| `rich` | >=13.0 | Terminal formatting, progress spinners, panels, colored output |

### LLM Integration
| Package | Version | Purpose |
|---------|---------|---------|
| `litellm` | >=1.82 | Model-agnostic LLM client — unified API for Anthropic, OpenAI, Gemini, etc. |

litellm provides:
- `litellm.acompletion()` — async LLM calls (used everywhere)
- `litellm.get_model_info()` — context window + output token limits
- `litellm.suppress_debug_info = True` — set in `llm.py` to reduce noise

### GitHub Integration
| Package | Version | Purpose |
|---------|---------|---------|
| `PyGithub` | >=2.6 | GitHub API client for PR/issue management |
| `tenacity` | >=9.1.4 | Retry logic with exponential backoff for rate limiting |

PyGithub is synchronous — all calls wrapped with `asyncio.to_thread()`.

### Configuration & Data
| Package | Version | Purpose |
|---------|---------|---------|
| `pyyaml` | >=6.0 | YAML parsing for `.sigil/config.yml` and idea frontmatter |

## Development Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `pytest` | >=9.0.2 | Test framework |
| `pytest-asyncio` | >=1.3.0 | Async test support (`asyncio_mode = "auto"`) |
| `ruff` | >=0.15.6 | Linter + formatter (replaces black, isort, flake8) |

## Internal Module Dependency Graph

```
cli.py
├── config.py
├── discovery.py
│   ├── llm.py
│   └── utils.py
├── knowledge.py
│   ├── config.py (SIGIL_DIR, MEMORY_DIR)
│   ├── llm.py
│   └── utils.py
├── memory.py
│   ├── config.py
│   ├── llm.py
│   └── utils.py
├── maintenance.py
│   ├── config.py
│   ├── knowledge.py
│   ├── llm.py
│   └── memory.py
├── ideation.py
│   ├── config.py
│   ├── knowledge.py
│   ├── llm.py
│   ├── memory.py
│   └── utils.py
├── validation.py
│   ├── config.py
│   ├── knowledge.py
│   ├── llm.py
│   ├── maintenance.py (Finding type)
│   └── memory.py
├── executor.py
│   ├── config.py
│   ├── ideation.py (FeatureIdea type)
│   ├── knowledge.py
│   ├── llm.py
│   ├── maintenance.py (Finding type)
│   └── utils.py
└── github.py
    ├── executor.py (ExecutionResult, WorkItem)
    ├── maintenance.py (Finding type)
    └── utils.py
```

**Shared utilities (no internal deps):**
- `llm.py` — only imports `litellm`
- `utils.py` — only imports stdlib (`asyncio`, `datetime`, `pathlib`)

## External Service Dependencies

### Required at Runtime
- **LLM API** — One of: Anthropic (`ANTHROPIC_API_KEY`), OpenAI (`OPENAI_API_KEY`), Google (`GEMINI_API_KEY`)
- **GitHub API** — `GITHUB_TOKEN` for PR/issue creation
- **Git** — Local git binary for file operations, branch management, worktrees

### Optional
- **CI Environment** — GitHub Actions or similar for scheduled runs

## Model Configuration

Sigil uses litellm's model string format:

```
anthropic/claude-sonnet-4-6        # Default
anthropic/claude-opus-4-6-20250527
anthropic/claude-haiku-4-5-20251001
openai/gpt-4o
openai/gpt-4o-mini
gemini/gemini-pro
gemini/gemini-flash
```

`MODEL_OVERRIDES` in `llm.py` provides correct token limits for models where litellm's info is stale.

## Removed Dependencies

- **tree-sitter-languages** — Removed (issue #024). Discovery now passes raw source code to LLM instead of AST summaries.
- **threading** — Removed (issue #022). Full async/await replaces thread-based concurrency.
- **requests** — Never added. PyGithub handles HTTP; subprocess handles git.
