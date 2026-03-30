<!-- head: 05afd4a | updated: 2026-03-25T03:37:29Z -->

# Project Overview — Sigil: Autonomous AI Coding Agent

## What is Sigil?
Sigil is an LLM-agnostic autonomous repository improvement agent that proactively finds improvements and ships pull requests while you sleep. It runs on a schedule (via GitHub Actions or any scheduler), analyzes the codebase, and opens small, safe PRs for low-risk improvements. High-risk findings become GitHub issues. Bring any model — OpenAI, Anthropic, Gemini, or any of 100+ providers supported by litellm.

**The gap it fills:** Every existing tool is either reactive (triggered by humans) or narrow-scoped (only dependencies, only reviews). Sigil is proactive and general-purpose.

## Target Users
- Development teams who want automated code maintenance
- Open source maintainers who need help with routine improvements
- Organizations seeking proactive code quality improvements without manual effort

## Language & Stack
- **Language:** Python 3.11+
- **Package Manager:** uv
- **CLI Framework:** typer + rich for terminal UI
- **LLM Integration:** litellm (model-agnostic — Anthropic, OpenAI, Gemini, etc.)
- **GitHub Integration:** PyGithub for PR/issue management
- **Async Runtime:** Full async/await with asyncio throughout
- **Configuration:** YAML-based `.sigil/config.yml`
- **Retry Logic:** tenacity for GitHub API rate limiting
- **MCP Client:** `mcp` SDK for connecting to external tool servers

## How to Build / Test / Lint
```bash
uv sync                # Install dependencies
uv run sigil --help    # Run the CLI
uv run pytest          # Run tests
uv run ruff format .   # Lint and format (ALWAYS run last after code changes)
uv run ruff check .    # Lint check
```

## Project Structure
```
sigil/
├── cli.py               # CLI commands + main pipeline orchestration
├── core/                # Core infrastructure (agent framework, config, LLM, MCP, utils)
├── pipeline/            # Agent pipeline stages (discovery, executor, ideation, knowledge, maintenance, validation)
├── state/               # State management (attempts, chronic, memory)
└── integrations/        # External service integrations (GitHub)

tests/                   # Unit and integration tests
.github/                 # GitHub Actions workflows
examples/                # Example GitHub Actions workflows
action.yml               # Composite GitHub Action
.sigil/                  # Runtime directory (config, memory, ideas, traces)
.issues/                 # Internal issue tracker (gitignored)
.closed_issues/          # Closed issue archive
```

## Current Status
Phase 1 MVP pipeline is complete. All 24 Phase 1 tickets closed. Extensibility track complete (MCP client support, tool naming, deferred loading). Quality track complete (CI on push, integration CI weekly, full unit test coverage across all modules). Sprint 7 complete (parallel-agent validation + per-agent model configuration). Sprint 8 complete (v1.0.0 release with cost optimization). Sprint 11 complete (agent framework shipped, code reorganized into subpackages).

- **Version:** 1.0.0 (released to PyPI as `sigil-py`)
- **License:** Apache 2.0
- **CI:** GitHub Actions runs lint + unit tests on every push (Python 3.11/3.12/3.13); integration tests run weekly across 6 providers; Sigil runs on itself daily via `sigil.yml`
- **MCP:** Sigil connects to external MCP servers (stdio + SSE), tools namespaced as `mcp__server__tool`
- **Validation:** Single mode (default) or parallel mode (two reviewers + arbiter)
- **Per-agent models:** Each agent can use a different model via `agents` config; cheap models (Haiku) auto-default for ideator/compactor/memory/selector
- **Cost optimization:** Observation masking, tool output truncation, client-side compaction, doom loop detection, run budget cap
- **Token tracking:** Per-call LLM tracing to `.sigil/traces/last-run.json` with `--trace` flag
- **Sprint archives:** Completed sprints archived in `.issues/sprints/sprint-N.md`
- **Dogfood CI:** Sigil runs on itself daily at 02:00 UTC via `.github/workflows/sigil.yml`
- **Modular architecture:** Code organized into `core/`, `pipeline/`, `state/`, `integrations/` subpackages (ticket 076)

## Key Constraints / Hard Rules
- **NEVER commit without running `/commit-review` first** (project rule)
- **NEVER write tests directly** — use `/test-writer` skill
- **Run `uv run ruff format .` as the LAST step** after ALL code changes
- No comments in code unless logic is genuinely non-obvious
- CLI + GitHub Action, tested across 6 LLM providers
- Every PR opened must have CI passing before merge is suggested
- Conservative by default — when in doubt, open an issue not a PR
- Respect existing agent config files in target repos (AGENTS.md, CLAUDE.md, .cursorrules, etc.)
- Copy existing patterns (Claude Code, Agent SDK, Codex) — don't reinvent the wheel

## Issue Tracker
Issues live in `.issues/` (gitignored from public repo). Closed issues in `.closed_issues/`. Sprint history in `.issues/sprints/`. The `/pm` skill manages issue lifecycle.

## Known Bugs (from working memory)
- `execute_parallel` uses `""` as sentinel for "no branch" — should be `str | None`
- `apply_edit` has no guard against empty `old_content` (potential full-file replacement)
- `MODEL_OVERRIDES` in `llm.py` may be dead code (no tests verify the override path)
- `DEFAULT_MODEL` in `config.py` (`anthropic/claude-sonnet-4-6`) doesn't match `configuration.md`
- `config.ignore` field is documented but currently unused in filtering logic
