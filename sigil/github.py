import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from github import Github, GithubException
from github.Repository import Repository as GHRepo
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from sigil.agent_config import AgentConfigResult
from sigil.executor import ExecutionResult, WorkItem
from sigil.maintenance import Finding
from sigil.utils import arun

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
        logger.warning("Cannot parse remote URL: %s", remote_url)
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
    https = re.match(r"https://github\.com/(.+?)(?:\.git)?$", url)
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


def _normalize(title: str) -> str:
    t = title.lower().strip()
    t = re.sub(r"^sigil:\s*", "", t)
    t = re.sub(r"\s+", " ", t)
    return t


def _title_tokens(title: str) -> set[str]:
    t = _normalize(title)
    t = re.sub(r"^(fix|implement)\s+", "", t)
    return {w for w in re.split(r"[\s/._\-:]+", t) if len(w) > 2}


def _item_title(item: WorkItem) -> str:
    if isinstance(item, Finding):
        return f"sigil: fix {item.category} in {item.file}"
    return f"sigil: {item.title}"


def _item_key(item: WorkItem) -> str | None:
    if isinstance(item, Finding):
        return f"{item.category}:{item.file}"
    return None


def _extract_finding_key(title: str) -> str | None:
    m = re.match(r"fix\s+(\w+)\s+in\s+(.+)", _normalize(title))
    if m:
        return f"{m.group(1)}:{m.group(2).strip()}"
    return None


SIMILARITY_THRESHOLD = 0.6


def _is_similar(tokens_a: set[str], tokens_b: set[str]) -> bool:
    if not tokens_a or not tokens_b:
        return False
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union) >= SIMILARITY_THRESHOLD


def _dedup_items_sync(client: GitHubClient, items: list[WorkItem]) -> DedupResult:
    existing_titles: set[str] = set()
    existing_finding_keys: set[str] = set()
    existing_token_sets: list[set[str]] = []

    for pr in client.repo.get_pulls(state="open"):
        if any(lbl.name == SIGIL_LABEL for lbl in pr.labels):
            title = pr.title
            existing_titles.add(_normalize(title))
            key = _extract_finding_key(title)
            if key:
                existing_finding_keys.add(key)
            existing_token_sets.append(_title_tokens(title))

    for issue in client.repo.get_issues(state="all", labels=[SIGIL_LABEL]):
        if issue.pull_request is None:
            title = issue.title
            existing_titles.add(_normalize(title))
            key = _extract_finding_key(title)
            if key:
                existing_finding_keys.add(key)
            existing_token_sets.append(_title_tokens(title))

    skipped: list[WorkItem] = []
    remaining: list[WorkItem] = []
    reasons: dict[int, str] = {}

    for i, item in enumerate(items):
        title = _item_title(item)

        if _normalize(title) in existing_titles:
            skipped.append(item)
            reasons[i] = f"Exact title match: {title}"
            continue

        finding_key = _item_key(item)
        if finding_key and finding_key in existing_finding_keys:
            skipped.append(item)
            reasons[i] = f"Same category+file: {finding_key}"
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


def _format_pr_body(
    item: WorkItem, result: ExecutionResult, agent_config: AgentConfigResult | None = None
) -> str:
    if isinstance(item, Finding):
        what = f"Fix **{item.category}** issue in `{item.file}`"
        confidence = f"Risk: {item.risk} | Lint: {'pass' if result.lint_passed else 'fail'} | Tests: {'pass' if result.tests_passed else 'fail'}"
    else:
        what = f"Implement **{item.title}**"
        confidence = f"Complexity: {item.complexity} | Lint: {'pass' if result.lint_passed else 'fail'} | Tests: {'pass' if result.tests_passed else 'fail'}"

    changes = result.summary or "See diff for details."

    validation = f"Retries: {result.retries}"
    if result.diff:
        diff_lines = len(result.diff.splitlines())
        validation += f" | Diff: +{diff_lines} lines"

    conventions = ""
    if agent_config and agent_config.has_config:
        conventions = f"{agent_config.format_for_pr_body()}\n\n"

    return (
        f"## What\n{what}\n\n"
        f"## Changes\n{changes}\n\n"
        f"## Confidence\n{confidence}\n\n"
        f"## Validation\n{validation}\n\n"
        f"{conventions}"
        f"---\n*Automated by [Sigil](https://github.com/dylanmurray/sigil)*"
    )


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
    agent_config: AgentConfigResult | None = None,
) -> str | None:
    if not await push_branch(repo, branch):
        return None

    title = _item_title(item)
    body = _format_pr_body(item, result, agent_config)

    try:
        return await asyncio.to_thread(_create_pull, client, title, body, branch)
    except GithubException as e:
        logger.warning("PR creation failed for %s: %s", branch, e)
        return None


def _format_issue_body(item: WorkItem, downgrade_context: str | None = None) -> str:
    if isinstance(item, Finding):
        loc = item.file
        if item.line:
            loc = f"{item.file}:{item.line}"
        parts = [
            f"## Finding\n**Category:** {item.category}\n**Location:** `{loc}`\n**Risk:** {item.risk}",
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

    parts.append("---\n*Automated by [Sigil](https://github.com/dylanmurray/sigil)*")
    return "\n\n".join(parts)


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


async def cleanup_after_push(
    repo: Path,
    results: list[tuple[WorkItem, ExecutionResult, str]],
    pushed_branches: set[str] | None = None,
) -> None:
    for _, result, branch in results:
        if not branch:
            continue
        if pushed_branches is not None and branch not in pushed_branches:
            continue
        slug = branch.split("/")[-1].rsplit("-", 1)[0]
        worktree_path = repo / ".sigil" / "worktrees" / slug
        await arun(
            ["git", "worktree", "remove", "--force", str(worktree_path)], cwd=repo, timeout=30
        )
        await arun(["git", "branch", "-D", branch], cwd=repo, timeout=10)


async def publish_results(
    repo: Path,
    config,
    client: GitHubClient,
    execution_results: list[tuple[WorkItem, ExecutionResult, str]],
    issue_items: list[tuple[WorkItem, str | None]],
    *,
    agent_config: AgentConfigResult | None = None,
) -> tuple[list[str], list[str], set[str]]:
    pr_urls: list[str] = []
    issue_urls: list[str] = []
    pushed_branches: set[str] = set()

    pr_count = 0
    for item, result, branch in execution_results:
        if pr_count >= config.max_prs_per_run:
            break
        if not result.success or not branch:
            continue
        try:
            url = await open_pr(client, item, result, branch, repo, agent_config)
            if url:
                pr_urls.append(url)
                pushed_branches.add(branch)
                pr_count += 1
                logger.info("Opened PR: %s", url)
        except GithubException as e:
            logger.warning("Failed to open PR: %s", e)

    issue_count = 0
    for item, downgrade_context in issue_items:
        if issue_count >= config.max_issues_per_run:
            break
        url = await open_issue(client, item, downgrade_context)
        if url:
            issue_urls.append(url)
            issue_count += 1
            logger.info("Opened issue: %s", url)

    return pr_urls, issue_urls, pushed_branches
