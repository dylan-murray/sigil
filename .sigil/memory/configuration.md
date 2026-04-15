# Config File Format — .sigil/config.yml with Agent and Model Settings

Sigil is configured via a YAML file in the `.sigil/` directory. This file controls model selection, risk appetite, execution hooks, and per-agent tuning.

## Key Settings
- **`model`:** The default litellm model string (e.g., `anthropic/claude-sonnet-4-6`).
- **`boldness`:** `conservative` | `balanced` | `bold` | `experimental`. Controls how aggressive the auditor and ideator are.
- **`focus`:** List of areas to scan (e.g., `tests`, `security`, `dead_code`).
- **`agents`:** Per-agent model, token, iteration, and reasoning overrides. Allows using expensive models for engineering and cheap models for summarization.
- **`pre_hooks` / `post_hooks`:** Shell commands run before/after code generation. Post-hooks (like `pytest`) trigger automatic retries on failure.
- **`mcp_servers`:** Configuration for external tool servers using the Model Context Protocol.
- **`max_spend_usd`:** Hard cost cap per run. Sigil tracks token usage and aborts if this limit is reached.
- **`max_parallel_agents`:** Maximum number of agents running concurrently (default: 4).
- **`ignore_patterns`:** Glob patterns for files/directories to skip during scanning.

## Per-Agent Configuration

Each agent can override the global settings. Example:

```yaml
agents:
  architect:
    model: anthropic/claude-opus-4
    max_tokens: 128000
    max_iterations: 15
    reasoning_effort: high
  engineer:
    model: anthropic/claude-sonnet-4-6
    reasoning_effort: medium
```

Supported per-agent keys:
- `model`: Override the default model for this agent.
- `max_tokens`: Override the maximum output tokens.
- `max_iterations`: Override the maximum tool call rounds.
- `reasoning_effort`: Set reasoning effort to `low`, `medium`, or `high` (for models that support it).

## Run Budget

- **`max_spend_usd`:** Hard cost cap per run. Sigil tracks token usage and aborts if this limit is reached.
