# API Reference — Core Data Structures, Public Functions, and Tool Schemas: Core Data Structures, Public Functions by Module, LLM Tool Schemas, Constants, Known Notes

## Core Data Structures

### `WorkItem`
Abstract base class for all work items (Findings, Ideas, Tasks).

```python
@dataclass
class WorkItem(ABC):
    title: str
    description: str
    # ... other common fields
```

### `Finding`
Represents a detected issue in the codebase.

```python
@dataclass
class Finding(WorkItem):
    category: str
    file: str
    line: int
    risk: str
    suggested_fix: str
    # ... other finding-specific fields
```

### `FeatureIdea`
Represents a potential improvement or new feature.

```python
@dataclass
class FeatureIdea(WorkItem):
    rationale: str
    # ... other idea-specific fields
```

### `Task`
Represents a concrete task to be executed.

```python
@dataclass
class Task(WorkItem):
    # ... task-specific fields
```

### `ExecutionResult`
Result of an agent's execution attempt.

```python
@dataclass
class ExecutionResult:
    success: bool
    diff: str
    summary: str | None = None
    hooks_passed: bool = True
    retries: int = 0
    failed_hook: str | None = None
    failure_reason: str | None = None
    downgraded: bool = False
    downgrade_context: str | None = None
    # ... other execution details
```

### `AgentResult`
Result object returned by `Agent.run()`.

```python
@dataclass
class AgentResult:
    messages: list[dict]
    rounds: int
    stop_result: Any | None = None
    # ... other agent execution details
```

## Public Functions by Module

### `sigil.cli`
- `main()`: Entry point for the CLI application.
- `init()`: Initializes a new Sigil repository.
- `run()`: Executes the main Sigil pipeline.

### `sigil.orchestration`
- `orchestrate()`: Main orchestration function, runs the entire pipeline.

### `sigil.integrations.github`
- `open_pr()`: Opens a pull request on GitHub.
- `open_issue()`: Opens an issue on GitHub.
- `publish_results()`: Publishes execution results (PRs or issues) to GitHub.

### `sigil.pipeline.ideation`
- `ideate()`: Generates new `FeatureIdea`s.
- `save_ideas()`: Saves `FeatureIdea`s to disk.
- `mark_idea_done()`: Marks an idea as done.

### `sigil.pipeline.validation`
- `validate()`: Validates `WorkItem`s and assigns dispositions.

### `sigil.pipeline.execution`
- `execute_parallel()`: Executes `WorkItem`s in parallel using worktrees.

### `sigil.core.llm`
- `acompletion()`: Asynchronous LLM completion with retry and logging.
- `safe_max_tokens()`: Calculates safe max tokens for a model.
- `_extract_tc()`: Extracts tool call details from various LLM response formats.

## LLM Tool Schemas

### `read_file`
```json
{
  "name": "read_file",
  "description": "Read file content (capped at 2000 lines / 50KB).",
  "parameters": {
    "type": "object",
    "properties": {
      "path": {"type": "string", "description": "Path to the file."},
      "offset": {"type": "integer", "description": "1-based starting line number (optional)."},
      "limit": {"type": "integer", "description": "Max lines to read from offset (optional)."}
    },
    "required": ["path"]
  }
}
```

### `apply_edit`
```json
{
  "name": "apply_edit",
  "description": "Apply an edit to a file.",
  "parameters": {
    "type": "object",
    "properties": {
      "path": {"type": "string", "description": "Path to the file."},
      "old_content": {"type": "string", "description": "Exact content to replace."},
      "new_content": {"type": "string", "description": "New content to insert."}
    },
    "required": ["path", "old_content", "new_content"]
  }
}
```

### `create_file`
```json
{
  "name": "create_file",
  "description": "Create a new file.",
  "parameters": {
    "type": "object",
    "properties": {
      "path": {"type": "string", "description": "Path to the new file."},
      "content": {"type": "string", "description": "Content of the new file."}
    },
    "required": ["path", "content"]
  }
}
```

### `done`
```json
{
  "name": "done",
  "description": "Signal completion with a summary.",
  "parameters": {
    "type": "object",
    "properties": {
      "summary": {"type": "string", "description": "Summary of work done."}
    },
    "required": ["summary"]
  }
}
```

### `submit_pr_description` (Internal, used by `generate_pr_summary`)
```json
{
  "name": "submit_pr_description",
  "description": "Submits the generated title and body for a pull request.",
  "parameters": {
    "type": "object",
    "properties": {
      "title": {"type": "string", "description": "The title of the pull request."},
      "body": {"type": "string", "description": "The body of the pull request."}
    },
    "required": ["title", "body"]
  }
}
```

## Constants

- `MAX_FILE_READ_LINES = 2000`
- `MAX_FILE_READ_BYTES = 50 * 1024` (50KB)
- `COMMAND_TIMEOUT = 120` (seconds for hooks)
- `OUTPUT_TRUNCATE_CHARS = 4000`
- `SIMILARITY_THRESHOLD = 0.6` (for deduplication)
- `MAX_PR_TITLE_LENGTH = 70`
- `MAX_PR_BODY_LENGTH = 250` (words)

## Known Notes

- `_extract_tc` function in `sigil.core.llm` handles various tool call formats (dict, object with attributes) and extracts `name`, `arguments`, and `id`.
- `apply_edit` tool has a known gap: no guard against empty `old_content` (could replace entire file).
- `execute_parallel` returns `branch=""` as a sentinel for "worktree creation failed" instead of `None` for type safety. Callers check `if not branch`.
