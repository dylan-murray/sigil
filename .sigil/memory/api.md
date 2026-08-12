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
- `format_validation_error_fields(exc: ValidationError) -> str`: Format Pydantic validation errors into a comma-separated list of field paths (e.g., "file, edits.0.old_content"). Used by tool handlers to produce user-friendly error messages.

### `sigil.core.tools`
- `make_apply_edit_tool(...) -> Tool`: Factory for the `apply_edit` tool. Validates arguments with `ApplyEditArgs` and reports field-level errors on failure.
- `make_multi_edit_tool(...) -> Tool`: Factory for the `multi_edit` tool. Validates with `MultiEditArgs`.
- `make_create_file_tool(...) -> Tool`: Factory for the `create_file` tool. Validates with `CreateFileArgs`.
- `make_read_file_tool(...) -> Tool`: Factory for the `read_file` tool. Validates with `ReadFileArgs`.
- `make_grep_tool(...) -> Tool`: Factory for the `grep` tool. Validates with `GrepArgs`.
- `make_list_dir_tool(...) -> Tool`: Factory for the `list_dir` tool. Validates with `ListDirectoryArgs`.

### `sigil.core.tool_schemas`
- Pydantic models for tool argument validation:
  - `ApplyEditArgs`: `file`, `old_content`, `new_content` with file path sanitization.
  - `MultiEditArgs`: `file` and list of `EditSpec` (each with `old_content`, `new_content`).
  - `CreateFileArgs`: `file`, `content` with file path sanitization.
  - `ReadFileArgs`: `file`, `offset` (1-based line number, default 1), `limit` (max lines, default 2000).
  - `GrepArgs`: `pattern` (regex), `path` (default "."), `include` (glob filter).
  - `ListDirectoryArgs`: `path` (default "."), `depth` (1-3, default 1).
- All models forbid extra fields (`extra="forbid"`) and validate that path fields do not contain newlines, tabs, or angle brackets.

### `sigil.pipeline.knowledge`
- `compact_knowledge(...)`: Compacts knowledge files; uses `format_validation_error_fields` for validation error messages.
- `select_knowledge(...)`: Selects relevant knowledge for a task.
- `is_knowledge_stale(...)`: Checks if knowledge needs updating.

## LLM Tool Schemas

Tool schemas are generated automatically from Pydantic models using `inline_pydantic_schema()`. This ensures the LLM sees exactly the same validation rules that the code enforces.

- `apply_edit`: Parameters derived from `ApplyEditArgs`.
- `multi_edit`: Parameters derived from `MultiEditArgs`.
- `create_file`: Parameters derived from `CreateFileArgs`.
- `read_file`: Parameters derived from `ReadFileArgs` (file path, offset, limit).
- `grep`: Parameters derived from `GrepArgs` (pattern, path, include).
- `list_dir`: Parameters derived from `ListDirectoryArgs` (path, depth).

All mutating tools (`apply_edit`, `multi_edit`, `create_file`) share a common validation pattern: arguments are validated before execution; on failure, the handler returns a `ToolResult` with a message like "Invalid arguments — errors on: <fields>. Review the tool schema and retry." Read-only tools (`read_file`, `grep`, `list_dir`) follow the same validation pattern.

## Constants

- `MAX_FILE_READ_LINES = 2000`
- `DEFAULT_READ_LIMIT = 2000` (used by `ReadFileArgs`)
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
- Tool argument validation: All tools use Pydantic models (`ApplyEditArgs`, `MultiEditArgs`, `CreateFileArgs`, `ReadFileArgs`, `GrepArgs`, `ListDirectoryArgs`) to validate inputs before execution. The `_validate_tool_args` helper returns `(parsed, error)` and the handler returns early with the error message if validation fails.
- File path validation: The `file` and `path` fields in all tool schemas are validated by `_validate_file_path`, which rejects empty strings and any path containing newlines, carriage returns, tabs, null bytes, or angle brackets (`<`, `>`). This prevents path traversal and injection risks.
- Shared error formatting: `format_validation_error_fields(exc)` produces a concise, comma-separated list of field locations from a Pydantic `ValidationError`. Used in both tool handlers and the knowledge pipeline for consistent user-facing messages.
- Agent loop exit condition: The agent breaks the loop only when `(finish_reason == "stop" and not had_tool_calls) or truncated_with_tools`. This ensures the agent continues if the LLM returns `stop` but still provides tool calls to execute.
