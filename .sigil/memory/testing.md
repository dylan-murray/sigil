# Testing — pytest + pytest-asyncio with Mock Patterns and Coverage

## Framework & Configuration

- **pytest** with **pytest-asyncio** (`asyncio_mode = "auto"` in pyproject.toml)
- Default flags: `addopts = "-v -rs"` — verbose test names + skip reasons in summary
- All async test functions run automatically without `@pytest.mark.asyncio`
- Integration tests gated behind `@pytest.mark.integration` marker

## Directory Structure

```
tests/
├── conftest.py                  # Shared fixtures
├── unit/                        # Mocked tests, no external calls
│   ├── test_agent_config.py     # Agent config detection
│   ├── test_cli.py              # CLI pipeline orchestration, dry run, PR cap, downgrade callbacks
│   ├── test_config.py           # Config loading, validation, YAML serialization
│   ├── test_discovery.py        # File filtering, budget system, source summarization
│   ├── test_executor.py         # Worktrees, branches, parallel execution, path safety
│   ├── test_github.py           # URL parsing, dedup, PR/issue creation, labels, existing issues
│   ├── test_ideation.py        # Dual-pass ideation, TTL, dedup, validation
│   ├── test_knowledge.py        # Compaction, selection, staleness detection
│   ├── test_llm.py              # acompletion retry behavior
│   ├── test_maintenance.py      # Finding collection, priority sorting
│   ├── test_mcp.py              # MCP client: connection failures, malformed responses
│   ├── test_memory.py           # load_working, update_working, frontmatter roundtrip
│   ├── test_utils.py            # arun subprocess, timeout, cwd
│   └── test_validation.py       # Approve/adjust/veto, unreviewed defaults
└── integration/                 # Real LLM API calls via litellm
    ├── conftest.py              # Provider registry, make_config(), tiny_repo fixture
    ├── test_memory.py           # Memory lifecycle across runs
    └── test_pipeline.py         # Real pipeline stage tests across all providers
```

## CI Pipelines

### Unit CI (`.github/workflows/ci.yml`)
- Triggers: push to `main`, pull requests
- Matrix: Python 3.11, 3.12, 3.13
- Steps: `uv sync` → `ruff check` → `ruff format --check` → `pytest tests/unit/ -q`

### Integration CI (`.github/workflows/integration.yml`)
- Triggers: weekly schedule (Monday 06:00 UTC) + `workflow_dispatch`
- Matrix: 6 providers (openai, anthropic, gemini, bedrock, azure, mistral)
- `fail-fast: false` — one provider failure doesn't block others
- Timeout: 30 minutes per provider job

### Dogfood CI (`.github/workflows/sigil.yml`)
- Triggers: daily schedule (02:00 UTC) + `workflow_dispatch`
- Runs Sigil on itself — opens real PRs/issues against the Sigil repo

## Test Conventions

### Style
- **Plain functions only:** `def test_foo():` — never classes
- **Descriptive names:** `test_load_unknown_fields_raises`, not `test_load_error`
- **Parametrize** for multiple inputs: `@pytest.mark.parametrize`
- **Fixtures:** `tmp_path` for file system, `monkeypatch` for mocking

### Async Tests
```python
async def test_analyze_collects_findings(tmp_path, monkeypatch):
    async def fake_acompletion(**kwargs):
        return mock_response
    monkeypatch.setattr("sigil.maintenance.acompletion", fake_acompletion)
```

**Important:** Always patch `sigil.<module>.acompletion`, not `litellm.acompletion`.

## Mocking Patterns

### LLM Tool Call Responses

Standard pattern for mocking tool-use LLM responses:

```python
def _make_tool_call(call_id, name, args):
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = name
    tc.function.arguments = json.dumps(args)
    return tc
```

### GitHub Client Mock
```python
def _mock_client() -> GitHubClient:
    repo = MagicMock()
    gh = MagicMock()
    return GitHubClient(gh=gh, repo=repo)
```

### Real Git Repos (executor tests)

Executor tests use real git repos because worktree operations require actual git state. Git config (`user.email`/`user.name`) must be set for commits to work in CI.

### CLI Pipeline Mocking

CLI tests mock `execute_parallel` and `publish_issues` (not `publish_results`). When testing downgrade behavior, tests provide a `fake_execute` function that invokes the `on_issue_downgrade` callback to simulate inline PR publishing:

```python
async def fake_execute(*args, **kwargs):
    cb = kwargs.get("on_issue_downgrade")
    assert cb is not None
    for it, res, _branch in exec_results:
        if res.downgraded and not res.diff:
            cb(it, res.downgrade_context)
    return exec_results
```

## Coverage by Module

### `test_cli.py`
- `test_dry_run_with_findings_skips_execution` — dry run skips execution
- `test_no_findings_early_return` — no findings exits early
- `test_pr_cap_overflow_moves_to_issues` — PRs over cap become issues
- `test_downgraded_item_gets_context_in_issue` — downgrade callback fires, context preserved in issue
- `test_downgraded_idea_gets_context_in_issue` — idea downgrade callback fires, context preserved

### `test_github.py`
- `_parse_remote_url()` — SSH, HTTPS, invalid
- `_item_title()` — finding vs idea
- `_normalize()` — strips "sigil:" prefix, normalizes whitespace
- `_is_similar()` — Jaccard similarity matching
- `_item_key()`, `_extract_finding_key()` — category+file key extraction
- `dedup_items()` — filters duplicates, passes new items
- `fetch_existing_issues()` — mixed issues/PRs, directive detection, body truncation, max cap
- `_format_pr_body()` — finding vs idea
- `_format_issue_body()` — finding, with downgrade context, idea
- `ensure_labels()` — creates missing, skips existing
- `open_pr()` — success, push fails, GitHub error
- `open_issue()` — success, GitHub error, creates category label
- `create_client()` — no token, SSH URL, HTTPS URL
- **Removed:** `publish_results()` test (function removed; PRs now published inline in executor)

### `test_executor.py`
- `_slugify()` — finding vs idea, special chars, 50-char truncation
- `_branch_name()` — epoch timestamp in name
- `_dedup_slugs()` — no collision, with collision (append -1, -2)
- `_validate_path()` — traversal blocked, valid path allowed, absolute blocked
- `_read_file()`, `_apply_edit()`, `_create_file()` — traversal rejection
- `_create_worktree()` — creates worktree, copies memory, no memory case
- `_cleanup_worktree()` — removes worktree and branch
- `_commit_changes()` — commits with "sigil:" prefix
- `_rebase_onto_main()` — memory conflict auto-resolved, code conflict → False
- `_execute_in_worktree()` — worktree failure, execution failure (downgraded), rebase conflict (downgraded)
- `execute_parallel()` — concurrency limit respected (peak == max_parallel_agents)
- `_format_run_context()` — downgraded/succeeded/failed counts, empty downgrade_context handled

### `test_config.py`
- Load missing file → defaults
- Load valid config with overrides
- Unknown fields raise ValueError
- Invalid boldness raises ValueError
- `schedule` field raises (removed from schema)
- `fast_model` field raises (deprecated)
- Per-agent model resolution via `model_for()`

### `test_discovery.py`
- `_should_skip()` — node_modules, __pycache__, .git, .venv → True; src/ → False
- `_summarize_source_files()` — budget truncation, already-read skipping
- Edge cases: git failures, file truncation, binary detection

### `test_ideation.py`
- `ideate()` — collects from two passes, variable temperature, conservative skips
- `save_ideas()` — writes files with YAML frontmatter
- `_load_existing_ideas()` — loads with summary, TTL expiry
- `_slug()` — normalization, truncation
- `_deduplicate()` — case-insensitive slug dedup

### `test_knowledge.py`
- `_knowledge_budget()` — scales with context window
- `_load_existing_knowledge()` — skips INDEX.md and working.md
- `_parse_response()` — plain JSON, with fences, truncated
- `_repair_truncated_json()` — salvages partial files
- `compact_knowledge()` — full init writes files, rejects reserved names, incremental with tool reads
- `select_knowledge()` — calls LLM and loads files
- `is_knowledge_stale()` — no index, HEAD matches, HEAD differs

### `test_llm.py`
- `acompletion()` — success, retries on InternalServerError, retries on RateLimitError, raises after max retries, retries on Timeout

### `test_maintenance.py`
- `analyze()` — collects findings, no findings, invalid disposition/risk defaults

### `test_mcp.py`
- Connection failure paths, partial failure, malformed tool responses, CancelledError

### `test_memory.py`
- `load_working()`: missing file, corrupted YAML, happy path
- `update_working()`: LLM failure, file write, frontmatter roundtrip

### `test_utils.py`
- `arun()` — exec success, exec failure, shell success, shell pipe, timeout, command not found, cwd

### `test_validation.py`
- `validate_all()` — approve all, adjust disposition, veto removes, unreviewed defaults

## Running Tests

```bash
uv run pytest                                                          # All tests (excludes integration)
uv run pytest tests/unit/ -v                                           # Unit tests verbose
uv run pytest tests/unit/ -q                                           # Unit tests quiet (CI mode)
uv run pytest tests/integration/ -m integration                        # Integration tests only
uv run pytest tests/unit/test_executor.py -v                           # Single file
uv run pytest tests/unit/test_config.py::test_load_unknown_fields_raises -v  # Single test
uv run pytest -m "not integration"                                     # Everything except integration
```
