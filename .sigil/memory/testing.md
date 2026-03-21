# Testing — Sigil

## Framework & Configuration

- **pytest** with **pytest-asyncio** (`asyncio_mode = "auto"` in pyproject.toml)
- All async test functions run automatically without `@pytest.mark.asyncio`
- 108 tests passing as of current state
- `conftest.py` is currently empty — no shared fixtures yet

## Directory Structure

```
tests/
├── conftest.py              # Shared fixtures (currently empty)
├── unit/                    # Fast unit tests — all external services mocked
│   ├── test_config.py       # Config loading, validation, YAML serialization
│   ├── test_discovery.py    # File filtering, budget system, source summarization
│   ├── test_executor.py     # Worktrees, branches, parallel execution, path safety
│   ├── test_github.py       # URL parsing, dedup, PR/issue creation, labels
│   ├── test_ideation.py     # Dual-pass ideation, TTL, dedup, validation
│   ├── test_knowledge.py    # Compaction, selection, staleness detection
│   ├── test_maintenance.py  # Finding collection, priority sorting, defaults
│   ├── test_utils.py        # arun subprocess, timeout, cwd
│   └── test_validation.py   # Approve/adjust/veto, unreviewed defaults
└── integration/             # Integration tests (real services — currently EMPTY)
    └── __init__.py
```

## Test Conventions

### Style
- **Plain functions only:** `def test_foo():` — never classes
- **Descriptive names:** `test_load_unknown_fields_raises`, not `test_load_error`
- **Parametrize** for multiple inputs: `@pytest.mark.parametrize`
- **Fixtures:** `tmp_path` for file system, `monkeypatch` for mocking

### Async Tests
```python
async def test_analyze_collects_findings(tmp_path, monkeypatch):
    # Mock LLM
    async def fake_acompletion(**kwargs):
        return mock_response
    monkeypatch.setattr("sigil.maintenance.litellm.acompletion", fake_acompletion)

    # Mock knowledge selection
    async def _noop_select(*a, **kw):
        return {}
    monkeypatch.setattr("sigil.maintenance.select_knowledge", _noop_select)
    monkeypatch.setattr("sigil.maintenance.load_working", lambda r: "")

    result = await analyze(tmp_path, config)
    assert len(result) == 2
```

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

def _mock_response_with_findings(findings_args):
    calls = [_make_tool_call(f"call_{i}", "report_finding", args)
             for i, args in enumerate(findings_args)]

    # First response: tool calls
    msg1 = MagicMock()
    msg1.tool_calls = calls
    msg1.content = None
    choice1 = MagicMock()
    choice1.message = msg1
    choice1.finish_reason = "tool_calls"
    resp1 = MagicMock()
    resp1.choices = [choice1]

    # Second response: stop (no more tool calls)
    msg2 = MagicMock()
    msg2.tool_calls = None
    msg2.content = "Done."
    choice2 = MagicMock()
    choice2.message = msg2
    choice2.finish_reason = "stop"
    resp2 = MagicMock()
    resp2.choices = [choice2]

    return [resp1, resp2]

# Usage: cycle through responses
call_count = {"n": 0}
async def fake_acompletion(**kwargs):
    idx = call_count["n"]
    call_count["n"] += 1
    return responses[idx]
```

### GitHub Client Mock
```python
def _mock_client() -> GitHubClient:
    repo = MagicMock()
    gh = MagicMock()
    return GitHubClient(gh=gh, repo=repo)

# Set up specific behaviors
client.repo.get_pulls.return_value = [mock_pr]
client.repo.create_pull.return_value = mock_pr
type(client.repo).default_branch = PropertyMock(return_value="main")
```

### Real Git Repos (executor tests)

Executor tests use real git repos because worktree operations require actual git state:

```python
def _init_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=repo, capture_output=True, check=True
    )
    return repo
```

**Note:** Git config (`user.email`/`user.name`) must be set for commits to work in CI. This was fixed in PR #1.

## Factory Functions

All test modules define local factory functions for test data:

```python
def _make_finding(**kw) -> Finding:
    defaults = dict(
        category="dead_code", file="src/utils.py", line=42,
        description="Unused import", risk="low", suggested_fix="Remove it",
        disposition="pr", priority=1, rationale="Not referenced",
    )
    defaults.update(kw)
    return Finding(**defaults)

def _make_idea(**kw) -> FeatureIdea:
    defaults = dict(
        title="Add retry logic", description="Retry failed HTTP calls",
        rationale="Improves reliability", complexity="low",
        disposition="pr", priority=2,
    )
    defaults.update(kw)
    return FeatureIdea(**defaults)
```

## Coverage by Module

### `test_config.py`
- Load missing file → defaults
- Load valid config with overrides
- Unknown fields raise ValueError
- Invalid boldness raises ValueError
- `schedule` field raises (removed from schema)
- Invalid YAML raises ValueError
- Non-mapping YAML raises ValueError
- `to_yaml()` doesn't include `schedule`

### `test_discovery.py`
- `_should_skip()` — node_modules, __pycache__, .git, .venv → True; src/ → False
- `_summarize_source_files()` — budget truncation, already-read skipping, raw content inclusion

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
- `_format_run_context()` — downgraded/succeeded/failed counts

### `test_github.py`
- `_parse_remote_url()` — SSH, HTTPS, invalid
- `_item_title()` — finding vs idea
- `_normalize()` — strips "sigil:" prefix, normalizes whitespace
- `_is_similar()` — Jaccard similarity matching
- `_item_key()`, `_extract_finding_key()` — category+file key extraction
- `dedup_items()` — filters duplicates, passes new items
- `_format_pr_body()` — finding vs idea
- `_format_issue_body()` — finding, with downgrade context, idea
- `ensure_labels()` — creates missing, skips existing
- `open_pr()` — success, push fails, GitHub error
- `open_issue()` — success, GitHub error, creates category label
- `publish_results()` — respects max_prs_per_run and max_issues_per_run
- `create_client()` — no token, SSH URL, HTTPS URL

### `test_ideation.py`
- `ideate()` — collects from two passes, variable temperature, conservative skips, doesn't save to disk
- `save_ideas()` — writes files with YAML frontmatter
- `_load_existing_ideas()` — loads with summary, TTL expiry
- `_slug()` — normalization, truncation
- `_save_idea()` — collision handling (-2, -3, etc.)
- `_deduplicate()` — case-insensitive slug dedup

### `test_knowledge.py`
- `_knowledge_budget()` — scales with context window
- `_load_existing_knowledge()` — skips INDEX.md and working.md
- `compact_knowledge()` — writes files, rejects reserved names, empty response
- `select_knowledge()` — calls LLM and loads files, no index → empty
- `is_knowledge_stale()` — no index, HEAD matches, HEAD differs

### `test_maintenance.py`
- `analyze()` — collects findings, no findings, invalid disposition/risk defaults, priority sorting

### `test_utils.py`
- `arun()` — exec success, exec failure, shell success, shell pipe, timeout, command not found, cwd

### `test_validation.py`
- `validate_all()` — approve all, adjust disposition, veto removes, unreviewed defaults, empty input, findings-only, ideas-only

## Coverage Gaps (Known)

- **`llm.py`** — no tests at all (MODEL_OVERRIDES, get_context_window, get_max_output_tokens)
- **`memory.py`** — no tests (update_working, load_working)
- **`github.py`** — no integration tests (real GitHub API)
- **Integration tests** — directory exists but is completely empty
- **`cli.py`** — no tests for the main pipeline orchestration

## Running Tests

```bash
uv run pytest                                                          # All tests
uv run pytest tests/unit/ -v                                           # Unit tests verbose
uv run pytest tests/unit/test_executor.py -v                           # Single file
uv run pytest tests/unit/test_config.py::test_load_unknown_fields_raises -v  # Single test
```
