# Coding Patterns

## Python Standards

- Python 3.11+, type-annotated throughout
- `ruff` for formatting and linting
- `pytest` + `pytest-asyncio` for testing
- `litellm` for LLM calls
- `pydantic` for structured output parsing

## Naming Conventions

- Modules: `snake_case.py`
- Classes: `PascalCase`
- Functions/methods: `snake_case`
- Private helpers: `_leading_underscore`
- Constants: `UPPER_SNAKE_CASE`
- Async functions: `async def` throughout

## Dataclass Pattern

Use `@dataclass(frozen=True, slots=True)` for immutable data containers:

```python
@dataclass(frozen=True, slots=True)
class AgentSpec:
    model: str
    max_tokens: int | None
    max_iterations: int
    reasoning_effort: str | None
```

## Tool Class Pattern

Tools are `Tool` dataclass instances created by factory functions:

```python
def make_read_file_tool(repo: Path, tracker: FileTracker | None = None) -> Tool:
    async def _handler(args: dict) -> ToolResult:
        # validate, execute, return ToolResult
        ...
    return Tool(
        name="read_file",
        description="Read a file from the repository",
        parameters=ReadFileArgs.model_json_schema(),
        handler=_handler,
    )
```

## Agent Class Pattern

Agents are instantiated with model, tools, and config, then run with messages:

```python
agent = Agent(
    label="engineer",
    model=model,
    tools=[...],
    system_prompt=...,
    max_rounds=50,
    temperature=0.3,
    max_tokens=16384,
    reasoning_effort="medium",
)
await agent.run(messages=[{"role": "user", "content": prompt}])
```

The agent loop no longer calls `reduce_context` unconditionally after each round. It only reduces context under token pressure or on `ContextOverflowError`.

## Config Access Pattern

Agent configurations are accessed via `Config.instances_for()` which returns `list[AgentSpec]`:

```python
specs = config.instances_for("ideator")
for spec in specs:
    agent = Agent(label="ideation", model=spec.model, ...)
```

Convenience methods (`model_for()`, `max_iterations_for()`, etc.) return values for the first instance only.

## Async Subprocess Pattern

Use `asyncio.create_subprocess_exec` with timeout:

```python
proc = await asyncio.create_subprocess_exec(
    *cmd, stdout=PIPE, stderr=PIPE, cwd=str(path)
)
try:
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
except asyncio.TimeoutError:
    proc.kill()
    raise
```

## Validation Spec Pattern

For structured LLM output, use pydantic models with `inline_pydantic_schema`:

```python
class ReviewDecision(BaseModel):
    action: str
    new_disposition: str | None = None
    reason: str
    spec: str = ""
    relevant_files: tuple[str, ...] = ()
    priority: int = 5
```

## Normalized Fuzzy Matching Pattern

For edit tools, use `normalize_for_fuzzy_match()` to handle LLM-introduced character mismatches:

```python
normalized_content = normalize_for_fuzzy_match(content)
normalized_old = normalize_for_fuzzy_match(old_content)
if normalized_old and normalized_content.count(normalized_old) >= 1:
    content = normalized_content
    matched_text = normalized_old
```

This catches smart quotes, em-dashes, NBSP, and other Unicode artifacts deterministically.
