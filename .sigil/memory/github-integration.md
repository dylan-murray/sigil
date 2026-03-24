# GitHub Integration

## Authentication & Setup

### Token Requirements
- **Environment variable:** `GITHUB_TOKEN`
- **Permissions:** `contents:write`, `pull-requests:write`, `issues:write`
- **Token types:** Personal access token or GitHub Actions `GITHUB_TOKEN`
- **Fail fast:** If `GITHUB_TOKEN` is missing in live mode (not `--dry-run`), `cli.py` exits immediately with a clear error

### Repository Detection
```python
# Auto-detects from git remote
git remote get-url origin

# Supports both formats:
# git@github.com:owner/repo.git  → "owner/repo"
# https://github.com/owner/repo.git  → "owner/repo"
```

If `GITHUB_TOKEN` is not set, `create_client()` returns `None`.

## Deduplication System

Before executing any item, Sigil checks for duplicates against:
1. **Open PRs** with `sigil` label
2. **Open issues** with `sigil` label (both open and closed)
3. **Closed issues** with `sigil` label (prevents re-proposing rejected work)

### Three Matching Strategies (in order)
```python
# 1. Exact normalized title match
def _normalize(title: str) -> str:
    t = title.lower().strip()
    t = re.sub(r"^sigil:\s*", "", t)   # Remove "sigil:" prefix
    t = re.sub(r"\s+", " ", t)          # Normalize whitespace
    return t

# 2. Category+file key match (findings only)
def _item_key(item: WorkItem) -> str | None:
    if isinstance(item, Finding):
        return f"{item.category}:{item.file}"
    return None

# 3. Token similarity (Jaccard ≥ 0.6)
SIMILARITY_THRESHOLD = 0.6
def _is_similar(tokens_a: set[str], tokens_b: set[str]) -> bool:
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union) >= SIMILARITY_THRESHOLD
```

### Title Generation
- **Findings:** `"sigil: fix {category} in {file}"`
- **Ideas:** `"sigil: {title}"`

## Pull Request Flow

```
1. push_branch(repo, branch)
   → git push -u origin {branch}
   → Returns False if push fails (PR not created)

2. _create_pull(client, title, body, branch)  [decorated with @_gh_retry]
   → client.repo.create_pull(title, body, head=branch, base=default_branch)
   → pr.add_to_labels("sigil")
   → Returns PR HTML URL

3. open_pr() wraps both steps, returns URL or None
```

### PR Body Template
```markdown
## What
Fix **{category}** issue in `{file}`  (or: Implement **{title}**)

## Changes
{done_summary or "See diff for details."}

## Confidence
Risk: {risk} | Hooks: pass

## Validation
Retries: {count} | Diff: +{lines} lines

---
*Automated by [Sigil](https://github.com/dylan-murray/sigil)*
```

## Issue Flow

Issues are created for:
- Items with `disposition="issue"` from validation
- Items that were downgraded from PR candidates (execution failed)

### Issue Body Template
```markdown
## Finding
**Category:** {category}
**Location:** `{file}:{line}`
**Risk:** {risk}

## Description
{description}

## Suggested Fix
{suggested_fix}

## Downgrade Context          ← only if downgraded
This was originally a PR candidate but was downgraded:
{downgrade_context}

---
*Automated by [Sigil](https://github.com/dylan-murray/sigil)*
```

For ideas (not findings), the body uses `## Idea`, `## Description`, `## Rationale` sections.

## Label Management

### Primary Label
- **Name:** `sigil`
- **Color:** `7B68EE` (medium slate blue)
- **Description:** "Automated improvement by Sigil"
- **Auto-created** if missing via `ensure_labels()`

### Category Labels
- **Pattern:** `sigil:{category}` (e.g., `sigil:security`, `sigil:dead_code`, `sigil:feature`)
- **Color:** `CCCCCC` (light gray)
- **Auto-created** when opening issues if missing

## Rate Limiting & Error Handling

### Retry Decorator
```python
_gh_retry = retry(
    retry=retry_if_exception(
        lambda e: isinstance(e, GithubException) and e.status in (403, 429)
    ),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    reraise=True,
)
```

Applied to `_create_pull` and `_open_issue_sync` (sync functions, before `to_thread` wrapping).

### Graceful Degradation
- **No token:** Fail fast in live mode (not silent)
- **No remote:** Log warning, return `None` from `create_client()`
- **Auth failure:** Log warning, return `None` from `create_client()`
- **Push failure:** Log warning, skip PR creation for that branch
- **PR creation failure:** Log warning, continue with other items
- **Issue creation failure:** Log warning, return `None`

## Publishing Limits

```python
# Enforced in publish_results()
pr_count = 0
for item, result, branch in execution_results:
    if pr_count >= config.max_prs_per_run:  # Default: 3
        break
    if not branch or not result.diff:       # Skip if no branch or no diff
        continue
    ...

issue_count = 0
for item, downgrade_context in issue_items:
    if issue_count >= config.max_issues_per_run:  # Default: 5
        break
    ...
```

## Branch Cleanup

After publishing, `cleanup_after_push()` removes:
- Git worktrees: `git worktree remove --force {worktree_path}`
- Local branches: `git branch -D {branch}`

Only cleans branches that were successfully pushed (tracked in `pushed_branches` set).

Worktree path is reconstructed from branch name:
```python
slug = branch.split("/")[-1].rsplit("-", 1)[0]
worktree_path = repo / ".sigil" / "worktrees" / slug
```

## GitHub Actions Integration

### Reusable Action (recommended)

The repo ships a composite action at `action.yml`. The simplest workflow:

```yaml
name: Sigil
on:
  schedule:
    - cron: '0 2 * * *'
  workflow_dispatch:

jobs:
  sigil:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
      issues: write
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: dylan-murray/sigil@main
        with:
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
        # Pass any env vars your MCP servers need (${VAR} in .sigil/config.yml):
        # env:
        #   SLACK_BOT_TOKEN: ${{ secrets.SLACK_BOT_TOKEN }}
        #   JIRA_API_KEY: ${{ secrets.JIRA_API_KEY }}
```

This is exactly the workflow used in `.github/workflows/sigil.yml` to dogfood Sigil on itself.

### Manual Setup Variant

```yaml
- uses: astral-sh/setup-uv@v4
- run: uv tool install sigil
- run: sigil run
  env:
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

`fetch-depth: 0` is required — shallow clones break git worktree operations.

**Note:** `uv tool install sigil` requires the package to be published to PyPI. As of current state, it is not yet published (open issue #008 / gap in GitHub Action example).

### Dogfood Workflow (`.github/workflows/sigil.yml`)

Sigil runs on itself daily via a dedicated workflow:

```yaml
name: Sigil
on:
  schedule:
    - cron: '0 2 * * *'   # Daily at 02:00 UTC
  workflow_dispatch:       # Also triggerable manually

jobs:
  sigil:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
      issues: write
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: dylan-murray/sigil@main
        with:
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

This workflow uses `ANTHROPIC_API_KEY` from repository secrets. `GITHUB_TOKEN` is automatically provided by the composite action from `github.token`.

## Async Wrapping Pattern

All PyGithub calls are synchronous and must be wrapped:

```python
# Pattern used throughout github.py
@_gh_retry
def _sync_operation(client: GitHubClient, ...) -> ...:
    return client.repo.some_sync_method(...)

result = await asyncio.to_thread(_sync_operation, client, ...)
```

The `@_gh_retry` decorator is applied to sync functions before they're wrapped with `to_thread`.
