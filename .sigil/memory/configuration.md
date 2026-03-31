# Sigil Configuration — .sigil/config.yml with Agent and Model Settings

Sigil is configured via a YAML file in the `.sigil/` directory. This file controls model selection, risk appetite, and execution hooks.

## Key Settings
- **`model`:** The default litellm model string (e.g., `anthropic/claude-sonnet-4-6`).
- **`boldness`:** `conservative` | `balanced` | `bold` | `experimental`. Controls how aggressive the auditor and ideator are.
- **`focus`:** List of areas to scan (e.g., `tests`, `security`, `dead_code`).
- **`agents`:** Per-agent model and iteration overrides. Allows using expensive models for engineering and cheap models for summarization.
- **`pre_hooks` / `post_hooks`:** Shell commands run before/after code generation. Post-hooks (like `pytest`) trigger automatic retries on failure.
- **`mcp_servers`:** Configuration for external tool servers using the Model Context Protocol.

## Run Budget
- **`max_spend_usd`:** Hard cost cap per run. Sigil tracks token usage and aborts if this limit is reached.
