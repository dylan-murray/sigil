# Testing

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
│   ├── test_agent.py
│   ├── test_config.py
│   ├── test_instructions.py
│   ├── test_discovery.py
│   ├── test_executor.py
│   ├── test_github.py
│   ├── test_ideation.py
│   ├── test_knowledge.py
│   ├── test_llm.py
│   ├── test_maintenance.py
│   ├── test_mcp.py
│   ├── test_memory.py
│   ├── test_attempts.py
│   ├── test_chronic.py
│   ├── test_token_tracking.py
│   ├── test_utils.py
│   └── test_validation.py
└── integration/                 # Real LLM API calls via litellm
    ├── conftest.py              # Provider registry, make_config(), tiny_repo fixture
    ├── test_memory.py           # Memory lifecycle: write → read-back → update across runs
    └── test_pipeline.py         # Real pipeline stage tests across all providers
```

## CI Pipelines

### Unit CI (`.github/workflows/ci.yml`)
- Triggers: push to `main`, pull requests
- Matrix: Python 3.11, 3.12, 3.13
- Steps: `uv sync` → `ruff check` → `ruff format --check` → `pytest tests/unit/ -q`
- No secrets needed — fast feedback loop
- Git identity set via env vars for executor tests that commit

### Integration CI (`.github/workflows/integration.yml`)
- Triggers: weekly schedule (Monday 06:00 UTC) + `workflow_dispatch`
- Matrix: 6 providers (openai, anthropic, gemini, bedrock, azure, mistral)
- `fail-fast: false` — one provider failure doesn't block others
- Timeout: 30 minutes per provider job
- Requires repository secrets: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `MISTRAL_API_KEY`, `AZURE_API_KEY`, `AZURE_API_BASE`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION_NAME`

### Dogfood CI (`.github/workflows/sigil.yml`)
- Triggers: daily schedule (02:00 UTC) + `workflow_dispatch`
- Runs Sigil on itself — opens real PRs/issues against the Sigil repo
- Requires `ANTHROPIC_API_KEY` repository secret; `GITHUB_TOKEN` auto-provided
- Permissions: `contents:write`, `pull-requests:write`, `issues:write`
- Uses `fetch-depth: 0` (full history required for git worktree operations)
- Uses the reusable `dylan-murray/sigil@main` composite action

## Test Conventions

### Style
- **Plain functions only:** `def test_foo():` — never classes
- **Descriptive names:** `test_load_unknown_fields_raises`, not `test_load_error`
- **Parametrize** for multiple inputs: `@pytest.mark.parametrize`
- **Fixtures:** `tmp_path` for file system, `monkeypatch` for mocking

### Async Tests
```python
async def test_analyze_collects_findings(tmp_path, monkeypatch):
    # Mock LLM — patch sigil.maintenance.acompletion (not litellm directly)
    async def fake_acompletion(**kwargs):
        return mock_response
    monkeypatch.setattr("sigil.maintenance.acompletion", fake_acompletion)

    # Mock knowledge selection
    async def _noop_select(*a, **kw):
        return {}
    monkeypatch.setattr("sigil.maintenance.select_knowledge", _noop_select)
    monkeypatch.setattr("sigil.maintenance.load_working", lambda r: "")

    result = await analyze(tmp_path, config)
    assert len(result) == 2
```

**Important:** Always patch `sigil.<module>.acompletion`, not `litellm.acompletion` — modules import `acompletion` from `sigil.llm`.

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

### Knowledge Compaction Mock

The `compact_knowledge` uses JSON response format, not tool calls for writing. Mock with `_make_json_response`:

```python
def _make_json_response(files, index="# Knowledge Index\n\n## project.md\nProject info"):
    payload = json.dumps({"files": files, "index": index})
    msg = MagicMock()
    msg.content = payload
    msg.tool_calls = None
    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = "stop"
    resp = MagicMock()
    resp.choices = [choice]
    return resp
```

For incremental mode (with `read_knowledge_file` tool reads before the JSON response):

```python
def _make_read_then_json_responses(read_files, final_files, final_index):
    tool_calls = [_make_tool_call(f"call_{f}", "read_knowledge_file", {"filename": f})
                  for f in read_files]
    msg1 = MagicMock()
    msg1.tool_calls = tool_calls
    msg1.content = None
    choice1 = MagicMock()
    choice1.message = msg1
    choice1.finish_reason = "tool_calls"
    resp1 = MagicMock()
    resp1.choices = [choice1]
    resp2 = _make_json_response(final_files, final_index)
    return [resp1, resp2]
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
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=repo, capture_output=True, check=True
    )
    return repo
```

**Note:** Git config (`user.email`/`user.name`) must be set for commits to work in CI. The CI workflow sets `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `GIT_COMMITTER_NAME`, `GIT_COMMITTER_EMAIL` env vars. Executor tests use `git init -b main` to ensure the default branch is `main`.

### LLM Retry Tests (test_llm.py)

```python
@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr("sigil.llm.INITIAL_DELAY", 0.0)  # Speed up tests

async def test_acompletion_retries_on_transient_error():
    error = InternalServerError(message="overloaded", model="test", llm_provider="anthropic")
    mock = AsyncMock(side_effect=[error, error, mock_response])
    with patch("sigil.llm.litellm.acompletion", mock):
        result = await acompletion(model="test", messages=[])
    assert mock.await_count == 3
```

## Integration Tests

Parametrized across 6 providers: OpenAI, Anthropic, Gemini, Bedrock, Azure, Mistral.

Pipeline stage tests (`test_pipeline.py`):
1. `test_analyze_returns_valid_findings` — calls `analyze()` against sigil repo, validates Finding fields and file paths exist
2. `test_ideate_returns_valid_ideas` — calls `ideate()`, validates FeatureIdea fields and enums
3. `test_validate_vetoes_hallucination` — feeds hallucinated + real findings to `validate_all()`, asserts hallucination is vetoed
4. `test_execute_fixes_planted_bug` — creates a tiny repo with a planted bug, calls `execute_parallel()`, asserts fix in diff

Memory tests (`test_memory.py`):
5. Memory lifecycle — two sequential `update_working` calls, verifying persistence across runs (all 6 providers)

All gated behind `@pytest.mark.integration`. Auto-skip when env vars are missing.

### Required Env Vars

| Provider  | Env Vars                                                    |
|-----------|-------------------------------------------------------------|
| OpenAI    | `OPENAI_API_KEY`                                            |
| Anthropic | `ANTHROPIC_API_KEY`                                         |
| Gemini    | `GEMINI_API_KEY`                                            |
| Bedrock   | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION_NAME` |
| Azure     | `AZURE_API_KEY`, `AZURE_API_BASE`                           |
| Mistral   | `MISTRAL_API_KEY`                                           |

Tests auto-skip when the required key is missing — no failures from missing credentials.

## Coverage by Module

### `test_config.py`
- Load missing file → defaults
- Load valid config with overrides
- Unknown fields raise ValueError
- Invalid boldness raises ValueError
- `schedule` field raises (removed from schema)
- `fast_model` field raises (deprecated)
- Invalid YAML raises ValueError
- Non-mapping YAML raises ValueError
- `to_yaml()` doesn't include `schedule`
- Per-agent model resolution via `model_for()`

### `test_discovery.py`
- `_should_skip()` — node_modules, __pycache__, .git, .venv → True; src/ → False
- `_summarize_source_files()` — budget truncation, already-read skipping, raw content inclusion
- Edge cases: git failures, file truncation, binary detection

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

### `test_github.py`
- `_parse_remote_url()` — SSH, HTTPS, invalid
- `_item_title()` — finding vs idea
- `_normalize()` — strips "sigil:" prefix, normalizes whitespace
- `_is_similar()` — Jaccard similarity matching
- `_item_key()`, `_extract_finding_key()` — category+file key extraction
- `dedup_items()` — filters duplicates, passes new items
- `fetch_existing_issues()` — mixed issues/PRs, directive detection, body truncation, max cap, comment errors, empty list, None body
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
- Edge cases: save failures, invalid enums, tool call parsing

### `test_knowledge.py`
- `_knowledge_budget()` — scales with context window
- `_load_existing_knowledge()` — skips INDEX.md and working.md
- `_parse_response()` — plain JSON, with fences, truncated (falls back to repair)
- `_repair_truncated_json()` — salvages partial files, returns None on garbage
- `_decode_json_string()` — handles escape sequences
- `_max_input_chars()` — correct formula using context window and output tokens
- `_truncate_to_budget()` — short strings pass through, long strings truncated with marker
- `compact_knowledge()` — full init writes files, rejects reserved names, empty response, skips when HEAD matches, incremental with tool reads
- `select_knowledge()` — calls LLM and loads files, no index → empty
- `is_knowledge_stale()` — no index, HEAD matches, HEAD differs

### `test_llm.py`
- `acompletion()` — success, retries on InternalServerError, retries on RateLimitError, now also retries on `Timeout` errors.

### `test_maintenance.py`
- `analyze()` — collects findings, no findings, invalid disposition/risk defaults, priority sorting
- Edge cases: invalid finding JSON, malformed dispositions, tool call errors

### `test_mcp.py`
- Connection failure paths in `_connect_one` (stdio crash, SSE unreachable)
- Partial failure: one server crashes, other connects successfully
- Malformed tool responses: empty content, model_dump fallback, exception recovery
- `CancelledError` propagation (asyncio contract)
- 44 tests total; existing error handling was already resilient (no hardening needed)

### `test_memory.py`
- `load_working()`: missing file, corrupted YAML, happy path
- `update_working()`: LLM failure, file write, frontmatter roundtrip
- `_write_frontmatter()`: serialization edge cases
- Bug fix verified: memory updated correctly on empty runs

### `test_utils.py`
- `arun()` — exec success, exec failure, shell success, shell pipe, timeout, command not found, cwd

### `test_validation.py`
- `validate_all()` — approve all, adjust disposition, veto removes, unreviewed defaults, empty input, findings-only, ideas-only
- `_format_existing_issues()` — empty list, with directive, no body, receives existing issues in prompt

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
