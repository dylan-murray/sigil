# Agent Framework — Unified Tool and Agent Abstractions

## Core Classes

### Tool

A callable tool with a name, description, JSON schema for parameters, and an async handler. Tools are registered with an `Agent` and invoked when the LLM requests them.

```python
@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict  # JSON Schema
    handler: Callable[[dict], Awaitable[ToolResult]]
```

### ToolResult

Returned by tool handlers. Contains content (string), an optional `stop` flag to end the agent loop, and an optional `result` for structured data.

### Agent

Orchestrates a conversation loop with an LLM. Key features:

- **Tool calling**: LLM can invoke registered tools; results are fed back as messages
- **Max rounds**: Configurable limit on tool calls per turn
- **Temperature**: Optional override for creative tasks
- **Reasoning effort**: `low` / `medium` / `high` for reasoning models
- **MCP integration**: External tools via Model Context Protocol
- **Context management**: `reduce_context` is called only under context pressure or on `ContextOverflowError` — NOT unconditionally after every round. This prevents masking tool results mid-conversation.
- **Doom loop detection**: If the LLM repeats the same tool call with identical arguments 3+ times, the loop is terminated
- **Forced tool choice**: On the final round, the agent forces the LLM to call a specific tool (used for `submit_plan`, `report_finding`, etc.)

```python
agent = Agent(
    label="engineer",
    model="anthropic/claude-sonnet-4-6",
    tools=[make_read_file_tool(repo), make_apply_edit_tool(repo)],
    system_prompt="You are an engineer...",
    max_rounds=50,
    temperature=0.3,
    max_tokens=16384,
    reasoning_effort="medium",
)
await agent.run(messages=[{"role": "user", "content": "Implement feature X"}])
```

### Tool Factory Functions

Located in `sigil/core/tools.py`. Each returns a `Tool` instance:

| Factory | Tool Name | Description |
|---|---|---|
| `make_read_file_tool` | `read_file` | Read file with pagination (max 2000 lines, 50KB). Reports oversized first lines. |
| `make_apply_edit_tool` | `apply_edit` | Find-and-replace with normalized fuzzy matching (smart quotes, dashes, spaces folded to ASCII). Detects no-op edits. |
| `make_multi_edit_tool` | `multi_edit` | Atomic batch edit — all edits matched against original file, applied in reverse position order. Rejects overlapping edits. Supports normalized fallback. |
| `make_create_file_tool` | `create_file` | Create new file with content. |
| `make_grep_tool` | `grep` | Search file contents by regex. |
| `make_list_dir_tool` | `list_directory` | List files and subdirectories. |
| `make_bash_tool` | `bash` | Execute shell commands (sandboxed). |
| `make_finalize_tool` | `finalize` | End the agent loop with a result. |

### Normalized Fuzzy Matching

`apply_edit` and `multi_edit` first attempt exact match. If that fails, they normalize both sides via `normalize_for_fuzzy_match()`:
- NFKC normalization
- Smart quotes → ASCII quotes
- Unicode dashes (em-dash, en-dash, figure dash, etc.) → ASCII hyphen
- Special spaces (NBSP, en-space, etc.) → ASCII space
- Per-line trailing whitespace stripped

This catches common LLM-introduced character mismatches deterministically without scoring.

### Atomic Multi-Edit

`multi_edit` applies all edits atomically:
1. All `old_content` strings are matched against the **original** file content
2. Edits are sorted by position and checked for overlap
3. Applied in reverse position order so character offsets stay stable
4. If any edit fails (not found, ambiguous, overlapping), NONE are applied
5. Partial failure reports which edits failed and why

### No-op Detection

Both `apply_edit` and `multi_edit` detect when `new_content` is identical to the matched text and report it as a no-op without writing to disk.

## Status Callbacks

Agents accept an optional `on_status` callback for progress reporting. Status verbs are mapped by agent label:

| Label | Status Verb |
|---|---|
| `architect` | Planning... |
| `audit` | Auditing... |
| `ideation` | Brainstorming... |
| `validation:triager` | Triaging... |
| `engineer` | Engineering... |
| `reviewer` | Reviewing... |
| `knowledge:compact` | Studying... |
| `knowledge:memory` | Remembering... |
| `knowledge:select` | Selecting... |
