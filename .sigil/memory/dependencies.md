<!-- head: 05afd4a | updated: 2026-03-25T03:37:29Z -->

# Dependencies — Sigil Project External Libraries

## Package Manager
**uv** — Modern Python package manager. Fast dependency resolution and virtual environment management.

```bash
uv sync                # Install all deps
uv add <pkg>           # Add a dependency
uv run <cmd>           # Run a command in the venv
uv tool install sigil  # Install as a global tool
```

## Runtime Dependencies

### CLI & Terminal
| Package | Version | Purpose |
|---------|---------|----------|
| `typer` | >=0.15 | CLI framework with automatic help generation and type validation |
| `rich` | >=13.0 | Terminal formatting, progress spinners, panels, colored output |

### LLM Integration
| Package | Version | Purpose |
|---------|---------|----------|
| `litellm` | >=1.82 | Model-agnostic LLM client — unified API for Anthropic, OpenAI, Gemini, Bedrock, Azure, Mistral |

litellm provides:
- `litellm.acompletion()` — async LLM calls (used via `sigil.core.llm.acompletion` wrapper)
- `litellm.get_model_info()` — context window + output token limits
- `litellm.suppress_debug_info = True` — set in `llm.py` to reduce noise

### GitHub Integration
| Package | Version | Purpose |
|---------|---------|----------|
| `PyGithub` | >=2.6 | GitHub API client for PR/issue management |
| `tenacity` | >=9.1.4 | Retry logic with exponential backoff for rate limiting |

PyGithub is synchronous — all calls wrapped with `asyncio.to_thread()`.

### Configuration & Data
| Package | Version | Purpose |
|---------|---------|----------|
| `pyyaml` | >=6.0 | YAML parsing for `.sigil/config.yml` and idea frontmatter |
| `mcp` | >=1.26.0 | MCP client SDK — stdio and SSE transports for external tool servers |

## Development Dependencies

| Package | Version | Purpose |
|---------|---------|----------|
| `pytest` | >=9.0.2 | Test framework |
| `pytest-asyncio` | >=1.3.0 | Async test support (`asyncio_mode = "auto"` in pyproject.toml) |
| `ruff` | >=0.15.6 | Linter + formatter (replaces black, isort, flake8) |

## Internal Module Dependency Graph
```
cli.py
├── core/config.py
├── core/instructions.py
├── core/llm.py
├── core/mcp.py
├── core/utils.py
├── pipeline/discovery.py
│   ├── core/llm.py
│   └── core/utils.py
├── pipeline/knowledge.py
│   ├── core/config.py (SIGIL_DIR, MEMORY_DIR)
│   ├── core/llm.py
│   ├── core/agent.py (Agent framework)
│   └── core/utils.py
├── pipeline/maintenance.py
│   ├── core/config.py
│   ├── pipeline/knowledge.py
│   ├── core/agent.py (Agent, Tool, ToolResult)
│   ├── core/mcp.py
│   └── core/utils.py
├── pipeline/ideation.py
│   ├── core/config.py
│   ├── pipeline/knowledge.py
│   ├── core/agent.py (Agent, Tool, ToolResult)
│   ├── state/memory.py
│   └── core/utils.py
├── pipeline/validation.py
│   ├── core/config.py
│   ├── integrations/github.py (ExistingIssue type)
│   ├── pipeline/ideation.py (FeatureIdea type)
│   ├── pipeline/knowledge.py
│   ├── core/agent.py (Agent, Tool, ToolResult)
│   ├── state/chronic.py (Finding type)
│   ├── core/mcp.py
│   └── state/memory.py
├── pipeline/executor.py
│   ├── core/config.py
│   ├── pipeline/ideation.py (FeatureIdea type)
│   ├── pipeline/knowledge.py
│   ├── core/agent.py (Agent, Tool, ToolResult)
│   ├── state/chronic.py (Finding type)
│   ├── core/mcp.py
│   └── core/utils.py
├── state/memory.py
│   ├── core/config.py
│   ├── core/llm.py
│   └── core/utils.py
├── state/attempts.py
│   └── state/chronic.py
├── integrations/github.py
│   ├── core/instructions.py (Instructions type)
│   ├── state/chronic.py (WorkItem type)
│   ├── pipeline/executor.py (ExecutionResult type)
│   ├── core/llm.py
│   ├── pipeline/maintenance.py (Finding type)
│   └── core/utils.py
└── core/agent.py
    ├── core/llm.py (acompletion, cacheable_message, compact_messages, detect_doom_loop, get_agent_output_cap, mask_old_tool_outputs)
    ├── core/mcp.py (MCPManager, handle_search_tools_call)
    └── core/utils.py (StatusCallback)
```

**Shared utilities (no internal deps):**
- `core/llm.py` — only imports `litellm` and stdlib
- `core/utils.py` — only imports stdlib (`asyncio`, `datetime`, `pathlib`, `os`, `re`)
- `core/agent.py` — imports from `core/llm.py`, `core/mcp.py`, `core/utils.py` (agent framework base)
- `state/chronic.py` — only imports stdlib (`dataclasses`, `typing`)

## External Service Dependencies

### Required at Runtime
- **LLM API** — One of: Anthropic (`ANTHROPIC_API_KEY`), OpenAI (`OPENAI_API_KEY`), Google (`GEMINI_API_KEY`), AWS Bedrock, Azure OpenAI, Mistral
- **GitHub API** — `GITHUB_TOKEN` for PR/issue creation (required in live mode; fails fast if missing)
- **Git** — Local git binary for file operations, branch management, worktrees

### Optional
- **MCP servers** — External tool servers configured in `.sigil/config.yml`; Sigil connects as an MCP client
- **CI Environment** — GitHub Actions or similar for scheduled runs

## Model Configuration
Sigil uses litellm's model string format:

```
anthropic/claude-sonnet-4-6        # Default (in core/config.py)
anthropic/claude-opus-4-6-20250527
anthropic/claude-haiku-4-5-20251001
openai/gpt-4o
openai/gpt-4o-mini
gemini/gemini-pro
gemini/gemini-flash
bedrock/anthropic.claude-3-haiku-20240307-v1:0
azure/gpt-4o-mini
mistral/mistral-small-latest
```

`MODEL_OVERRIDES` in `core/llm.py` provides correct token limits for models where litellm's info is stale:
```python
MODEL_OVERRIDES = {
    "anthropic/claude-sonnet-4-6-20250325": {"max_input_tokens": 200_000, "max_output_tokens": 64_000},
    "anthropic/claude-opus-4-6-20250527": {"max_input_tokens": 1_000_000, "max_output_tokens": 32_000},
    "anthropic/claude-haiku-4-5-20251001": {"max_input_tokens": 200_000, "max_output_tokens": 64_000},
}
```

## Removed Dependencies
- **tree-sitter-languages** — Removed (issue #024). Discovery now passes raw source code to LLM instead of AST summaries. `sigil/summarizer.py` was deleted.
- **threading** — Removed (issue #022). Full async/await replaces thread-based concurrency. Only `asyncio.to_thread` remains for PyGithub sync calls.
- **requests** — Never added. PyGithub handles HTTP; subprocess handles git.
