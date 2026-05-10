# Config File Format — .sigil/config.yml with Agent and Model Settings

The configuration file is `.sigil/config.yml`. It controls model selection, agent behavior, run budgets, and post-commit hooks.

## Key Settings

| Field | Default | Description |
|---|---|---|
| `model` | `ollama_chat/deepseek-v4-flash:cloud` | Default LLM for all agents |
| `boldness` | `experimental` | Risk appetite: `balanced`, `bold`, or `experimental` |
| `max_prs_per_run` | `20` | Max pull requests to open per run |
| `max_github_issues` | `0` | Max GitHub issues to create (0 = disabled) |
| `max_ideas_per_run` | `100` | Max ideas to generate per run |
| `idea_ttl_days` | `180` | Days before an idea is considered stale |
| `max_retries` | `3` | Max retries on transient failures |
| `max_parallel_tasks` | `5` | Max parallel worktree tasks |
| `llm_timeout` | `300` | Per-call LLM timeout in seconds |
| `directive_phrase` | `/sigil work on this` | Phrase in GitHub issue comments that triggers sigil to work on an issue |

## Per-Agent Configuration

Each agent value is a **list** of one or more instance configs. Multiple entries enable parallel instances (used by `ideator` for diverse perspectives across models). Singletons are still lists of one for schema uniformity.

Valid agents: `architect`, `engineer`, `auditor`, `ideator`, `triager`, `compactor`, `memory`, `selector`, `discovery`

Each entry accepts:
- `model` — override the global model for this instance
- `max_tokens` — max output tokens per call
- `max_iterations` — max tool calls per turn (prevents runaway agents)
- `reasoning_effort` — `low` / `medium` / `high` (for reasoning models like o3)

```yaml
agents:
  ideator:                              # multi-instance for diverse ideas
    - model: anthropic/claude-opus-4-7
    - model: openai/gpt-5
      reasoning_effort: medium
    - model: google/gemini-2.5-pro
  architect:
    - model: google/gemini-2.5-pro
      max_iterations: 10
  engineer:
    - model: anthropic/claude-sonnet-4-6
      max_iterations: 50
  auditor:
    - model: google/gemini-2.5-flash
  triager:
    - model: anthropic/claude-sonnet-4-6
  compactor:
    - model: google/gemini-2.5-flash
      max_iterations: 5
  memory:
    - model: google/gemini-2.5-flash
      max_iterations: 5
  selector:
    - model: google/gemini-2.5-flash
      max_iterations: 3
```

## Model Overrides

Override context/output token limits when litellm's model metadata is wrong or missing (e.g. newly released or self-hosted models):

```yaml
model_overrides:
  "ollama_chat/deepseek-v4-pro:cloud":
    max_input_tokens: 1048576
    max_output_tokens: 393216
  "ollama_chat/kimi-k2.6:cloud":
    max_input_tokens: 262144
    max_output_tokens: 32768
```

## Run Budget

- `max_spend_usd` — hard cost cap per run (USD). Removed in current config (no longer enforced).
- `max_retries` — retries on transient failures (minimum of this value or number of post_hooks).

## Post Hooks

Commands run after each successful change. All must pass for the change to be accepted:

```yaml
post_hooks:
  - uv run ruff format .
  - uv run ruff check --fix .
  - uv run pytest tests/unit -x -q
```

## MCP Servers

Connect external tools via the Model Context Protocol:

```yaml
mcp_servers:
  - command: npx
    args: ["@modelcontextprotocol/server-filesystem", "/path"]
```

## AgentSpec Dataclass

Internally, each agent instance is represented by `AgentSpec`:

```python
@dataclass(frozen=True, slots=True)
class AgentSpec:
    model: str
    max_tokens: int | None
    max_iterations: int
    reasoning_effort: str | None
```

Access via `config.instances_for("ideator")` returns `list[AgentSpec]`. The convenience methods `model_for()`, `max_iterations_for()`, `max_tokens_for()`, and `reasoning_effort_for()` return values for the first instance only.

## Default Max Iterations

| Agent | Default |
|---|---|
| architect | 15 |
| engineer | 50 |
| auditor | 15 |
| ideator | 15 |
| triager | 15 |
| compactor | 5 |
| memory | 5 |
| selector | 3 |
| discovery | 5 |

## Removed Fields

- `arbiter` — parallel validation mode removed. Validation is now single-pass triager only.
- `challenger` agent — removed alongside arbiter mode.
- `arbiter` agent — removed alongside arbiter mode.
- `reviewer` agent — removed. Code review is now handled by the auditor stage.
- `tool` agent — removed. Tool execution is embedded in the engineer agent.
