import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from github import Github, GithubException
from github.Repository import Repository as GHRepo
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from sigil.state.chronic import WorkItem
from sigil.pipeline.models import ExecutionResult
from sigil.core.llm import acompletion, diff_char_budget
from sigil.pipeline.maintenance import Finding
from sigil.core.utils import arun

logger = logging.getLogger(__name__)


@dataclass
class GitHubClient:
    gh: Github
    repo: GHRepo


@dataclass(frozen=True)
class DedupResult:
    skipped: list[WorkItem]
    remaining: list[WorkItem]
    reasons: dict[int, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ExistingIssue:
    number: int
    title: str
    body: str
    labels: list[str]
    is_open: bool
    has_directive: bool


SIGIL_LABEL = "sigil"
SIGIL_LABEL_COLOR = "7B68EE"
_gh_retry = retry(
    retry=retry_if_exception(lambda e: isinstance(e, GithubException) and e.status in (403, 429)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    reraise=True,
)


async def create_client(repo: Path) -> GitHubClient | None:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        logger.info("GITHUB_TOKEN not set — skipping GitHub integration")
        return None

    remote_url = await _get_remote_url(repo)
    if not remote_url:
        logger.warning("No git remote found")
        return None

    owner_repo = _parse_remote_url(remote_url)
    if not owner_repo:
        safe_url = re.sub(r"://[^@]+@", "://***@", remote_url)
        logger.warning("Cannot parse remote URL: %s", safe_url)
        return None

    def _connect() -> GitHubClient:
        gh = Github(token)
        gh_repo = gh.get_repo(owner_repo)
        return GitHubClient(gh=gh, repo=gh_repo)

    try:
        return await asyncio.to_thread(_connect)
    except GithubException as e:
        logger.warning("GitHub auth failed: %s", e)
        return None


async def _get_remote_url(repo: Path) -> str:
    rc, stdout, _ = await arun(["git", "remote", "get-url", "origin"], cwd=repo, timeout=10)
    if rc == 0:
        return stdout.strip()
    return ""


def _parse_remote_url(url: str) -> str:
    ssh = re.match(r"git@github\.com:(.+?)(?:\.git)?$", url)
    if ssh:
        return ssh.group(1)
    https = re.match(r"https://(?:[^@]+@)?github\.com/(.+?)(?:\.git)?$", url)
    if https:
        return https.group(1)
    return ""


def _ensure_labels_sync(client: GitHubClient) -> None:
    try:
        client.repo.get_label(SIGIL_LABEL)
    except GithubException:
        try:
            client.repo.create_label(
                name=SIGIL_LABEL,
                color=SIGIL_LABEL_COLOR,
                description="Automated improvement by Sigil",
            )
        except GithubException as e:
            logger.warning("Could not create label: %s", e)


async def ensure_labels(client: GitHubClient) -> None:
    await asyncio.to_thread(_ensure_labels_sync, client)


@_gh_retry
def _fetch_existing_issues_sync(
    client: GitHubClient,
    *,
    max_issues: int = 25,
    directive_phrase: str = "/sigil work on this",
) -> list[ExistingIssue]:
    results: list[ExistingIssue] = []
    phrase_lower = directive_phrase.lower()

    for issue in client.repo.get_issues(
        state="open", labels=[SIGIL_LABEL], sort="created", direction="desc"
    ):
        if issue.pull_request is not None:
            continue

        has_directive = False
        try:
            for comment in issue.get_comments():
                if phrase_lower in (comment.body or "").lower():
                    has_directive = True
                    break
        except GithubException as e:
            logger.warning("Failed to fetch comments for #%d: %s", issue.number, e)

        body = (issue.body or "")[:200]
        labels = [lbl.name for lbl in issue.labels]

        results.append(
            ExistingIssue(
                number=issue.number,
                title=issue.title,
                body=body,
                labels=labels,
                is_open=issue.state == "open",
                has_directive=has_directive,
            )
        )

        if len(results) >= max_issues:
            break

    return results


async def fetch_existing_issues(
    client: GitHubClient,
    *,
    max_issues: int = 25,
    directive_phrase: str = "/sigil work on this",
) -> list[ExistingIssue]:
    return await asyncio.to_thread(
        _fetch_existing_issues_sync,
        client,
        max_issues=max_issues,
        directive_phrase=directive_phrase,
    )


def _fetch_directive_issues_sync(
    client: GitHubClient,
    *,
    directive_phrase: str = "/sigil work on this",
) -> list[ExistingIssue]:
    # Unbounded scan for open Sigil-labeled issues whose comments contain the
    # directive phrase. Used to convert directive issues into PR-track work
    # items, separate from the capped fetch_existing_issues used for triager
    # dedup context.
    results: list[ExistingIssue] = []
    phrase_lower = directive_phrase.lower()

    for issue in client.repo.get_issues(state="open", labels=[SIGIL_LABEL]):
        if issue.pull_request is not None:
            continue
        has_directive = False
        try:
            for comment in issue.get_comments():
                if phrase_lower in (comment.body or "").lower():
                    has_directive = True
                    break
        except GithubException as e:
            logger.warning("Failed to fetch comments for #%d: %s", issue.number, e)
        if not has_directive:
            continue
        results.append(
            ExistingIssue(
                number=issue.number,
                title=issue.title,
                body=issue.body or "",
                labels=[lbl.name for lbl in issue.labels],
                is_open=True,
                has_directive=True,
            )
        )
    return results


async def fetch_directive_issues(
    client: GitHubClient,
    *,
    directive_phrase: str = "/sigil work on this",
) -> list[ExistingIssue]:
    return await asyncio.to_thread(
        _fetch_directive_issues_sync, client, directive_phrase=directive_phrase
    )


def directive_to_idea(issue: ExistingIssue):
    from sigil.pipeline.models import FeatureIdea

    return FeatureIdea(
        title=issue.title,
        description=issue.body or "(no body)",
        rationale=f"User directive on issue #{issue.number}",
        complexity="medium",
        disposition="pr",
        priority=1,
        boldness="balanced",
        generated_by=f"directive:#{issue.number}",
        source_issue=issue.number,
    )


def _normalize(title: str) -> str:
    t = title.lower().strip()
    t = re.sub(r"^sigil:\s*", "", t)
    t = re.sub(r"\s+", " ", t)
    return t


def _title_tokens(title: str) -> set[str]:
    t = _normalize(title)
    t = re.sub(r"^(fix|implement)\s+", "", t)
    return {w for w in re.split(r"[\s/._\-:]+", t) if len(w) > 2}


def _diff_files(diff: str) -> list[str]:
    files: list[str] = []
    for line in diff.splitlines():
        if line.startswith("diff --git"):
            parts = line.split(" b/", 1)
            if len(parts) == 2:
                files.append(parts[1])
    return files


def _item_title(item: WorkItem) -> str:
    if isinstance(item, Finding):
        desc = item.description.split(".")[0].split("\n")[0].strip()
        if len(desc) > 60:
            desc = desc[:57] + "..."
        return f"sigil: {desc}"
    return f"sigil: {item.title}"


def _item_key(item: WorkItem) -> str | None:
    if isinstance(item, Finding):
        if item.function_name:
            return f"{item.category}:{item.file}:{item.function_name}"
        return f"{item.category}:{item.file}"
    source_issue = getattr(item, "source_issue", None)
    if source_issue:
        return f"issue:#{source_issue}"
    return None


_KEY_MARKER_RE = re.compile(r"<!--\s*sigil-key:\s*([^>]+?)\s*-->")


def _key_marker(key: str) -> str:
    return f"<!-- sigil-key: {key} -->"


def _extract_marker_keys(body: str | None) -> set[str]:
    if not body:
        return set()
    return {m.group(1).strip() for m in _KEY_MARKER_RE.finditer(body)}


SIMILARITY_THRESHOLD = 0.6


def _is_similar(tokens_a: set[str], tokens_b: set[str]) -> bool:
    if not tokens_a or not tokens_b:
        return False
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union) >= SIMILARITY_THRESHOLD


def _dedup_items_sync(client: GitHubClient, items: list[WorkItem]) -> DedupResult:
    existing_titles: set[str] = set()
    existing_keys: set[str] = set()
    existing_token_sets: list[set[str]] = []

    for pr in client.repo.get_pulls(state="open"):
        if not any(lbl.name == SIGIL_LABEL for lbl in pr.labels):
            continue
        existing_titles.add(_normalize(pr.title))
        existing_keys.update(_extract_marker_keys(pr.body))
        existing_token_sets.append(_title_tokens(pr.title))

    for issue in client.repo.get_issues(state="all", labels=[SIGIL_LABEL]):
        if issue.pull_request is not None:
            continue
        existing_titles.add(_normalize(issue.title))
        existing_keys.update(_extract_marker_keys(issue.body))
        existing_token_sets.append(_title_tokens(issue.title))

    skipped: list[WorkItem] = []
    remaining: list[WorkItem] = []
    reasons: dict[int, str] = {}

    for i, item in enumerate(items):
        # Directive items only dedup against marker-tagged open PRs. Their
        # title and content match their source issue verbatim, so the regular
        # title/token paths would always (incorrectly) flag them as
        # duplicates of the very issue they're meant to implement.
        source_issue = getattr(item, "source_issue", None)
        if source_issue:
            key = f"issue:#{source_issue}"
            if key in existing_keys:
                skipped.append(item)
                reasons[i] = f"Issue #{source_issue} already has an open PR"
                continue
            remaining.append(item)
            continue

        title = _item_title(item)

        if _normalize(title) in existing_titles:
            skipped.append(item)
            reasons[i] = f"Exact title match: {title}"
            continue

        key = _item_key(item)
        if key and key in existing_keys:
            skipped.append(item)
            reasons[i] = f"Same finding key: {key}"
            continue

        item_tokens = _title_tokens(title)
        if any(_is_similar(item_tokens, et) for et in existing_token_sets):
            skipped.append(item)
            reasons[i] = f"Similar to existing: {title}"
            continue

        remaining.append(item)

    return DedupResult(skipped=skipped, remaining=remaining, reasons=reasons)


async def dedup_items(client: GitHubClient, items: list[WorkItem]) -> DedupResult:
    return await asyncio.to_thread(_dedup_items_sync, client, items)


async def push_branch(repo: Path, branch: str) -> bool:
    rc, _, stderr = await arun(["git", "push", "-u", "origin", branch], cwd=repo, timeout=60)
    if rc != 0:
        logger.warning("Push failed for %s: %s", branch, stderr.strip())
    return rc == 0


def _diff_stats(diff: str) -> str:
    if not diff:
        return "No changes."
    files = _diff_files(diff)
    adds = 0
    dels = 0
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            adds += 1
        elif line.startswith("-") and not line.startswith("---"):
            dels += 1
    file_list = ", ".join(f"`{f}`" for f in files[:10])
    if len(files) > 10:
        file_list += f" and {len(files) - 10} more"
    return f"Modified {len(files)} file(s): {file_list} (+{adds}/-{dels} lines)"


PR_SUMMARY_PROMPT = """\
You are writing a pull request title and description. The audience is a human \
code reviewer who needs to understand what changed and why.

The task assigned to the coding agent:
{task_ctx}

Agent's notes:
{executor_summary}

Files changed (authoritative — describe ALL of these even if some hunks are \
truncated below):
{file_list}

Diff:
```
{diff}
```

Call the submit_pr_description tool with the title and body."""

PR_DESCRIPTION_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_pr_description",
        "description": "Submit the PR title and description.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": (
                        "Short imperative PR title, max 70 chars. "
                        "Should read like a human wrote it: "
                        "'Fix symlink traversal in path validation', "
                        "'Add retry logic to HTTP client'. "
                        "Do NOT prefix with 'sigil:'."
                    ),
                },
                "body": {
                    "type": "string",
                    "description": (
                        "PR description in markdown. Start with "
                        "'**What this PR does:** <one sentence>', then "
                        "'**Key changes:**' as a bullet list naming specific "
                        "files, functions, and behaviors. Add '**Tests:**' if "
                        "tests were modified. Be specific, under 250 words. "
                        "No markdown H1/H2/H3 headers."
                    ),
                },
            },
            "required": ["title", "body"],
        },
    },
}


async def generate_pr_summary(
    diff: str, item: WorkItem, executor_summary: str, model: str
) -> tuple[str, str]:
    if not diff:
        return _item_title(item), executor_summary or "No changes."

    if isinstance(item, Finding):
        func_ctx = f"::{item.function_name}" if item.function_name else ""
        task_ctx = f"Fix {item.category} in {item.file}{func_ctx}: {item.description}"
    else:
        task_ctx = f"Implement {item.title}: {item.description}"

    files = _diff_files(diff)
    file_list = "\n".join(f"- {f}" for f in files) if files else "(none)"
    budget = diff_char_budget(model)
    truncated = diff[:budget]
    if len(diff) > budget:
        truncated += f"\n\n[diff truncated at {budget} chars; file list above is authoritative]"

    prompt = PR_SUMMARY_PROMPT.format(
        task_ctx=task_ctx,
        executor_summary=executor_summary or "(none provided)",
        file_list=file_list,
        diff=truncated,
    )

    try:
        response = await acompletion(
            label="pr_summary",
            model=model,
            messages=[{"role": "user", "content": prompt}],
            tools=[PR_DESCRIPTION_TOOL],
            temperature=0.0,
            max_tokens=1000,
        )
        msg = response.choices[0].message
        if msg.tool_calls:
            tc = msg.tool_calls[0]
            args = json.loads(tc.function.arguments)
            title = args.get("title", "").strip()
            body = args.get("body", "").strip()
            if title and body:
                return f"sigil: {title}", body
    except Exception as e:
        logger.warning("PR summary generation failed: %s", e)

    return _item_title(item), executor_summary or _diff_stats(diff)


_MODEL_AGENTS_FOR_PR = (
    "architect",
    "engineer",
    "auditor",
    "ideator",
    "triager",
)


def format_models_used(config) -> str:
    seen: dict[str, list[str]] = {}
    for agent_name in _MODEL_AGENTS_FOR_PR:
        try:
            instances = config.instances_for(agent_name)
        except (ValueError, AttributeError):
            continue
        for i, spec in enumerate(instances):
            if not spec.model:
                continue
            base = agent_name if len(instances) == 1 else f"{agent_name}[{i}]"
            label = f"{base} ({spec.reasoning_effort})" if spec.reasoning_effort else base
            seen.setdefault(spec.model, []).append(label)
    if not seen:
        return ""
    lines = [f"- `{model}` — {', '.join(agents)}" for model, agents in seen.items()]
    return "\n".join(lines)


def _format_pr_body(
    item: WorkItem,
    result: ExecutionResult,
    pr_summary: str,
    models_section: str = "",
) -> str:
    hooks_icon = "✅" if result.hooks_passed else "❌"
    if result.hooks_passed:
        hooks_status = f"{hooks_icon} All hooks passed"
    elif result.failed_hook:
        hooks_status = f"{hooks_icon} Failed: `{result.failed_hook}`"
    else:
        hooks_status = f"{hooks_icon} Hooks failed"

    if isinstance(item, Finding):
        meta = f"Risk: {item.risk}"
        if item.function_name:
            meta += f" | Function: `{item.function_name}()`"
    else:
        meta = f"Complexity: {item.complexity}"
        if item.generated_by:
            meta += f" | Ideator: `{item.generated_by}`"

    diff_stat = ""
    if result.diff:
        diff_lines = len(result.diff.splitlines())
        diff_stat = f" | {diff_lines} lines changed"

    stats = _diff_stats(result.diff)

    models_block = f"\n## Models\n{models_section}\n\n" if models_section else ""

    body = (
        f"## Changes\n{pr_summary}\n\n"
        f"## Stats\n{stats}\n\n"
        f"## Status\n{hooks_status} | Retries: {result.retries}{diff_stat} | {meta}\n"
        f"{models_block}"
        f"\n---\n*Automated by [Sigil](https://github.com/dylan-murray/sigil)*"
    )
    key = _item_key(item)
    if key:
        body += f"\n{_key_marker(key)}"
    return body


@_gh_retry
def _create_pull(client: GitHubClient, title: str, body: str, branch: str) -> str | None:
    pr = client.repo.create_pull(
        title=title,
        body=body,
        head=branch,
        base=client.repo.default_branch,
    )
    try:
        pr.add_to_labels(SIGIL_LABEL)
    except GithubException:
        pass
    return pr.html_url


async def open_pr(
    client: GitHubClient,
    item: WorkItem,
    result: ExecutionResult,
    branch: str,
    repo: Path,
    *,
    summary_model: str = "",
    models_section: str = "",
) -> str | None:
    if not await push_branch(repo, branch):
        return None

    if summary_model and result.diff:
        title, pr_summary = await generate_pr_summary(
            result.diff, item, result.summary, summary_model
        )
    else:
        title = _item_title(item)
        pr_summary = result.summary or _diff_stats(result.diff)

    body = _format_pr_body(item, result, pr_summary, models_section=models_section)

    try:
        return await asyncio.to_thread(_create_pull, client, title, body, branch)
    except GithubException as e:
        logger.warning("PR creation failed for %s: %s", branch, e)
        return None


def _format_issue_body(item: WorkItem, downgrade_context: str | None = None) -> str:
    if isinstance(item, Finding):
        loc = item.file
        if item.line and item.end_line and item.end_line > item.line:
            loc = f"{item.file}:{item.line}-{item.end_line}"
        elif item.line:
            loc = f"{item.file}:{item.line}"
        func = f" in `{item.function_name}()`" if item.function_name else ""
        parts = [
            f"## Finding\n**Category:** {item.category}\n**Location:** `{loc}`{func}\n**Risk:** {item.risk}",
            f"## Description\n{item.description}",
            f"## Suggested Fix\n{item.suggested_fix}",
        ]
    else:
        parts = [
            f"## Idea\n**Title:** {item.title}\n**Complexity:** {item.complexity}",
            f"## Description\n{item.description}",
            f"## Rationale\n{item.rationale}",
        ]

    if downgrade_context:
        parts.append(
            f"## Downgrade Context\nThis was originally a PR candidate but was downgraded:\n```\n{downgrade_context}\n```"
        )

    parts.append("---\n*Automated by [Sigil](https://github.com/dylan-murray/sigil)*")
    body = "\n\n".join(parts)
    key = _item_key(item)
    if key:
        body += f"\n{_key_marker(key)}"
    return body


def _category_label(item: WorkItem) -> str:
    if isinstance(item, Finding):
        return f"sigil:{item.category}"
    return "sigil:feature"


@_gh_retry
def _open_issue_sync(
    client: GitHubClient, item: WorkItem, downgrade_context: str | None = None
) -> str | None:
    title = _item_title(item)
    body = _format_issue_body(item, downgrade_context)

    issue = client.repo.create_issue(title=title, body=body, labels=[SIGIL_LABEL])
    cat_label = _category_label(item)
    try:
        client.repo.get_label(cat_label)
    except GithubException:
        try:
            client.repo.create_label(name=cat_label, color="CCCCCC")
        except GithubException:
            pass
    try:
        issue.add_to_labels(cat_label)
    except GithubException:
        pass
    return issue.html_url


async def open_issue(
    client: GitHubClient, item: WorkItem, downgrade_context: str | None = None
) -> str | None:
    try:
        return await asyncio.to_thread(_open_issue_sync, client, item, downgrade_context)
    except GithubException as e:
        logger.warning("Issue creation failed: %s", e)
        return None


async def publish_issues(
    client: GitHubClient,
    issue_items: list[tuple[WorkItem, str | None]],
    *,
    max_issues: int,
) -> list[str]:
    issue_urls: list[str] = []
    for item, downgrade_context in issue_items:
        if len(issue_urls) >= max_issues:
            break
        url = await open_issue(client, item, downgrade_context)
        if url:
            issue_urls.append(url)
            logger.info("Opened issue: %s", url)
    return issue_urls
