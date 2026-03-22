# Project: Sigil — Autonomous Repo Improvement Agent

## Hard Rules

1. **NEVER commit without running `/commit-review` first.** Stage changes, run the review, fix issues. Then also run it as a subagent with `model: "sonnet"` for a second opinion. No exceptions, even for markdown-only changes.
2. **NEVER write tests directly.** Use `/test-writer` — present a plan, wait for approval, then write.
3. **NEVER create/update/close issues outside `/pm`.** All issue lifecycle goes through the skill.
4. **Run `uv run ruff format .` as the LAST step after ALL code changes.**
5. **ALWAYS** read the `.knowledge/INDEX` file to learn more about the repo.
6. **ALWAYS** update the `.knowledge/*` directory after you learn something new or make significant architecture or component changes.

## What is Sigil?

Sigil is a proactive, scheduled AI agent that watches your repository, finds
improvements, and ships pull requests — without being asked. It runs in CI on
a schedule, analyzes the codebase, and opens small, safe PRs for low-risk
improvements. High-risk findings become issues.

**The gap it fills:** Every tool today is reactive (triggered by humans) or
narrow (only deps, only reviews). Sigil is proactive and general-purpose.

## Issue Tracker

Issues live in `.issues/`. See `.issues/INDEX.md` for the index.
The `/pm` skill manages issue lifecycle, sprint planning, and prioritization.
A post-commit hook checks if open issues should be closed after each commit.

## Sprint Cadence

Sprints are **one week long** and **end on Saturday**. The current sprint lives
in `.issues/current-sprint.md`. At the start of each conversation:

1. Check `.issues/current-sprint.md` for the sprint end date
2. If today is past the end date, the sprint is over — run `/pm` to close it
   and plan the next one before doing any other work
3. If no sprint exists, run `/pm` to create one

Never over-scope a sprint. It should contain only what can realistically ship
in one week. When in doubt, cut scope.

## Skills

- `/commit-review` — pre-commit reviewer. Auto-fixes simple issues, blocks on major problems.
- `/test-writer` — test authoring workflow. Plan first, then write.
- `/pm` — issue lifecycle, sprint planning, prioritization.

## Code Standards

- Language: Python 3.11+ (uv for deps)
- CLI framework: typer + rich
- LLM calls: litellm (model-agnostic)
- No comments unless explicitly asked
- Run `uv run ruff format .` as the LAST step after ALL code changes

## Python Rules

### Imports
- Prefer `from module import thing` for most cases
- Use `import module` when the module is a grab-bag (e.g. `utils`) with many functions
- Always use absolute imports
- Import ordering: stdlib first, then third-party, then local `sigil.*` — each group alphabetical by module name, separated by a blank line

### Type Hints
- Type hints on ALL function signatures (args + return types)
- Use `X | None` (PEP 604) — not `Optional[X]`
- Do NOT use `from __future__ import annotations`

### Strings
- Always use f-strings. No `.format()`, no `%` formatting

### Error Handling
- NEVER use bare `except`. Always catch the specific exception
- Prefer EAFP or LBYL case-by-case, but always name the exception

### Functions
- No max length, but each function should do ONE thing
- Functions must be tightly scoped to a specific piece of logic
- Use early returns to reduce nesting

### Naming
- Follow PEP 8 strictly
- Use `_private` for internal APIs, `__dunder` only for Python protocols
- Constants: module-level `UPPER_SNAKE_CASE`

### Data Structures
- Prefer Pydantic `BaseModel` for structured data (strictly typed, validated)
- `dataclass` is acceptable for simple internal structs without validation
- Avoid `NamedTuple` and `TypedDict` unless there's a clear reason

### Dependency Injection
- Always pass dependencies as arguments — do not rely on module-level state

### Console Output
- Use `rich` or `click.echo` for user-facing output

### Dead Code
- Delete dead code aggressively — no commented-out blocks, no unused imports, no orphan functions
- If it's not called, it's gone

### `assert`
- `assert` is for tests ONLY — never use in production code

### Module Structure
- Keep a clean, professional module structure
- Group related modules in packages with clear boundaries
- `__init__.py` should be minimal — no re-export bloat
- Skip `__all__` unless building a third-party-facing API

### Testing
- Always use pytest
- Use fixtures for setup/teardown
- Prefer `unittest.mock.patch` over `monkeypatch`
- Parametrize heavily — prefer `@pytest.mark.parametrize` over duplicate test functions

## Dependencies

Managed by `uv`: `uv sync`, `uv add <pkg>`, `uv run <cmd>`.

## Project Knowledge

Project knowledge for development lives in `.knowledge/`. See `.knowledge/INDEX`
for a quick-reference table of what to read. Update these files after any
significant architecture or component changes.

### Critical Rules

- `.knowledge/` is committed to the repo and MAY BE PUBLIC
- **NEVER store secrets, API keys, tokens, or credentials in knowledge files**
- After ANY code change that affects architecture, components, or conventions:
  update the relevant `.knowledge/` file so it stays current
- Knowledge must always reflect the current state of the code — if knowledge
  conflicts with code, the code is the source of truth
