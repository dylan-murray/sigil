# API Reference — Core Data Structures, Public Functions, and Tool Schemas: Core Data Structures, Public Functions by Module, LLM Tool Schemas, Constants, Known Notes

## Core Data Structures

### `Agent`
```python
class Agent:
    def __init__(
        self,
        label: str,
        model: str,
        tools: list[Tool],
        system_prompt: str,
        temperature: float = 0.0,
        max_rounds: int = 10,
        agent_key: str | None = None,
        use_cache: bool = True,
        enable_doom_loop: bool = True,
        enable_masking: bool = True,
        enable_compaction: bool = True,
        on_truncation: Callable | None = None,
        mcp_mgr: MCPManager | None = None,
        extra_tool_schemas: list[dict] | None = None,
        escalate_after: int = 10,
        subagents: dict[str, SubAgent] | None = None,
        forced_final_tool: str | None = None,
        reasoning_effort: str | None = None,  # NEW: low/medium/high for reasoning models
    ):
        ...
```

- `reasoning_effort`: Optional string (`"low"`, `"medium"`, `"high"`) passed to the LLM for models that support reasoning effort controls. Only used when not using a tool model (i.e., when `forced_final_tool` is not set).

### `Config`
```python
@dataclass(slots=True, frozen=True)
class Config:
    model: str = DEFAULT_MODEL
    boldness: str = "balanced"
    focus: list[str] = field(default_factory=list)
    agents: dict[str, dict] = field(default_factory=dict)
    max_spend_usd: float = 1.0
    pre_hooks: list[str] = field(default_factory=list)
    post_hooks: list[str] = field(default_factory=list)
    mcp_servers: dict[str, MCPServerConfig] = field(default_factory=dict)
    max_parallel_agents: int = 4
    ignore_patterns: list[str] = field(default_factory=list)

    def reasoning_effort_for(self, agent: str) -> str | None:
        """Return the reasoning_effort setting for the given agent, or None if not set.
        Validates that the value is one of: low, medium, high.
        """
        ...
```

## Public Functions by Module

### `sigil.core.config`
- `Config.load(repo_path: Path) -> Config`: Load configuration from `.sigil/config.yml`.
- `Config.reasoning_effort_for(agent: str) -> str | None`: Get the per-agent `reasoning_effort` setting (validates against allowed values).
- `Config.max_tokens_for(agent: str) -> int | None`: Get per-agent max_tokens override.
- `Config.max_iterations_for(agent: str) -> int`: Get per-agent max_iterations override (falls back to `DEFAULT_MAX_ITERATIONS`).

### `sigil.core.agent`
- `Agent(...)`: Construct an agent with tools, system prompt, and optional `reasoning_effort`.
- `Agent.run(context: dict, on_status: Callable | None) -> AgentResult`: Execute the agent loop.

### `sigil.core.llm`
- `acompletion(...)`: Asynchronous LLM completion with retry and logging. Accepts `reasoning_effort` as an extra kwarg for supported models.
- `safe_max_tokens(model: str) -> int`: Calculate safe max tokens for a model.
- `_extract_tc(response)`: Extracts tool call details from various LLM response formats.

## LLM Tool Schemas

(Existing tool schemas remain unchanged)

## Constants

- `MAX_FILE_READ_LINES = 2000`
- `MAX_FILE_READ_BYTES = 50 * 1024` (50KB)
- `COMMAND_TIMEOUT = 120` (seconds for hooks)
- `OUTPUT_TRUNCATE_CHARS = 4000`
- `SIMILARITY_THRESHOLD = 0.6` (for deduplication)
- `MAX_PR_TITLE_LENGTH = 70`
- `MAX_PR_BODY_LENGTH = 250` (words)
- `VALID_REASONING_EFFORTS = frozenset({"low", "medium", "high"})` (valid reasoning effort levels)

## Known Notes

- `reasoning_effort` is only passed to the LLM when `forced_tool_choice` is not set (i.e., when the agent is not forced to use a specific tool). This prevents sending unsupported parameters to tool-only models.
- The `Agent` class builds `extra_kwargs` dynamically to include `tool_choice` and `reasoning_effort` only when needed.
- Config validation: `reasoning_effort` values are validated against `VALID_REASONING_EFFORTS`; invalid values raise `ValueError` on config load.
- All pipeline stages (architect, engineer, ideator, auditor, triager, arbiter) now accept per-agent `reasoning_effort` from config.
- `_extract_tc` function in `sigil.core.llm` handles various tool call formats (dict, object with attributes) and extracts `name`, `arguments`, and `id`.
