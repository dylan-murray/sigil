# GitHub Integration — Sigil

## Authentication & Setup

### Token Requirements
- **Environment variable:** `GITHUB_TOKEN`
- **Permissions:** `contents:write`, `pull-requests:write`, `issues:write`
- **Token types:** Personal access token or GitHub Actions `GITHUB_TOKEN`

### Repository Detection
```python
# Auto-detects from git remote
git remote get-url origin

# Supports both formats:
# git@github.com:owner/repo.git  → "owner/repo"
# https://github.com/owner/repo.git  → "owner/repo"
```

If `GITHUB_TOKEN` is not set, `create_client()` returns `None` and the run proceeds in dry-run mode (no PRs/issues created).

## Deduplication System

Before executing any item, Sigil checks for duplicates against:
1. **Open PRs** with `sigil` label
2. **Open issues** with `sigil` label
3. **Closed issues** with `sigil` label (prevents re-proposing rejected work)

### Matching Logic
```python
def _normalize(title: str) -> str:
    t = title.lower().strip()
    t = re.sub(r"^sigil:\s*", "", t)   # Remove "sigil:" prefix
    t = re.sub(r"\s+", " ", t)          # Normalize whitespace
    return t
```

Titles are normalized before comparison — case-insensitive, prefix-stripped.

### Title Generation
- **Findings:** `"sigil: fix {category} in {file}"`
- **Ideas:** `"sigil: {title}"`

## Pull Request Flow

```
1. push_branch(repo, branch)
   → git push -u origin {branch}
   → Returns False if push fails (PR not created)

2. _create_pull(client, title, body, branch)
   → client.repo.create_pull(title, body, head=branch, base=default_branch)
   → pr.add_to_labels("sigil")
   → Returns PR HTML URL

3. open_pr() wraps both steps, returns URL or None
```

### PR Body Template
```markdown
## What
Fix **{category}** issue in `{file}`  (or: Implement: **{title}**)

## Why
{description from Finding or FeatureIdea}

## Confidence
Risk: {risk} | Lint: pass | Tests: pass

## Validation
Retries: {count} | Diff: +{lines} lines

---
*Automated by [Sigil](https://github.com/dylanmurray/sigil)*
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
```
{downgrade_context}
```

---
*Automated by [Sigil](https://github.com/dylanmurray/sigil)*
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
@retry(
    retry=retry_if_exception(
        lambda e: isinstance(e, GithubException) and e.status in (403, 429)
    ),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    reraise=True,
)
def _create_pull(client, title, body, branch): ...
```

Applied to `_create_pull` and `_open_issue_sync`.

### Graceful Degradation
- **No token:** Skip GitHub entirely, log info message
- **No remote:** Log warning, skip GitHub
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

## GitHub Actions Integration

Example workflow at `examples/github-action.yml`:

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
          fetch-depth: 0      # Full history needed for git operations
      - uses: astral-sh/setup-uv@v4
      - run: uv tool install sigil
      - run: sigil run
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

`fetch-depth: 0` is required — shallow clones break git worktree operations.

## Async Wrapping Pattern

All PyGithub calls are synchronous and must be wrapped:

```python
# Pattern used throughout github.py
def _sync_operation(client: GitHubClient, ...) -> ...:
    return client.repo.some_sync_method(...)

result = await asyncio.to_thread(_sync_operation, client, ...)
```

The `@_gh_retry` decorator is applied to sync functions before they're wrapped with `to_thread`.
