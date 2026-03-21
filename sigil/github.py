from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from github import Github, GithubException
from github.Repository import Repository as GHRepo
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from sigil.executor import ExecutionResult, WorkItem
from sigil.maintenance import Finding

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


def create_client(repo: Path) -> GitHubClient | None:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        logger.info("GITHUB_TOKEN not set — skipping GitHub integration")
        return None

    remote_url = _get_remote_url(repo)
    if not remote_url:
        logger.warning("No git remote found")
        return None

    owner_repo = _parse_remote_url(remote_url)
    if not owner_repo:
        logger.warning("Cannot parse remote URL: %s", remote_url)
        return None

    try:
        gh = Github(token)
        gh_repo = gh.get_repo(owner_repo)
        return GitHubClient(gh=gh, repo=gh_repo)
    except GithubException as e:
        logger.warning("GitHub auth failed: %s", e)
        return None


def _get_remote_url(repo: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            cwd=repo,
            timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def _parse_remote_url(url: str) -> str:
    ssh = re.match(r"git@github\.com:(.+?)(?:\.git)?$", url)
    if ssh:
        return ssh.group(1)
    https = re.match(r"https://github\.com/(.+?)(?:\.git)?$", url)
    if https:
        return https.group(1)
    return ""


def ensure_labels(client: GitHubClient) -> None:
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


def _normalize(title: str) -> str:
    t = title.lower().strip()
    t = re.sub(r"^sigil:\s*", "", t)
    t = re.sub(r"\s+", " ", t)
    return t


def _item_title(item: WorkItem) -> str:
    if isinstance(item, Finding):
        return f"sigil: fix {item.category} in {item.file}"
    return f"sigil: {item.title}"


def _matches_existing(title: str, existing_titles: set[str]) -> bool:
    return _normalize(title) in existing_titles


def dedup_items(client: GitHubClient, items: list[WorkItem]) -> DedupResult:
    existing_titles: set[str] = set()

    for pr in client.repo.get_pulls(state="open"):
        if any(lbl.name == SIGIL_LABEL for lbl in pr.labels):
            existing_titles.add(_normalize(pr.title))

    for issue in client.repo.get_issues(state="open", labels=[SIGIL_LABEL]):
        if issue.pull_request is None:
            existing_titles.add(_normalize(issue.title))

    for issue in client.repo.get_issues(state="closed", labels=[SIGIL_LABEL]):
        if issue.pull_request is None:
            existing_titles.add(_normalize(issue.title))

    remote_branches: set[str] = set()
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", "origin", "sigil/auto/*"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                parts = line.split("\t")
                if len(parts) == 2:
                    ref = parts[1].removeprefix("refs/heads/")
                    remote_branches.add(ref)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    skipped: list[WorkItem] = []
    remaining: list[WorkItem] = []
    reasons: dict[int, str] = {}

    for i, item in enumerate(items):
        title = _item_title(item)
        if _matches_existing(title, existing_titles):
            skipped.append(item)
            reasons[i] = f"Duplicate title: {title}"
        else:
            remaining.append(item)

    return DedupResult(skipped=skipped, remaining=remaining, reasons=reasons)


def push_branch(repo: Path, branch: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "push", "-u", "origin", branch],
            capture_output=True,
            text=True,
            cwd=repo,
            timeout=60,
        )
        if result.returncode != 0:
            logger.warning("Push failed for %s: %s", branch, result.stderr.strip())
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("Push failed for %s: %s", branch, e)
        return False


def _format_pr_body(item: WorkItem, result: ExecutionResult) -> str:
    if isinstance(item, Finding):
        what = f"Fix **{item.category}** issue in `{item.file}`"
        why = item.description
        confidence = f"Risk: {item.risk} | Lint: {'pass' if result.lint_passed else 'fail'} | Tests: {'pass' if result.tests_passed else 'fail'}"
    else:
        what = f"Implement: **{item.title}**"
        why = item.description
        confidence = f"Complexity: {item.complexity} | Lint: {'pass' if result.lint_passed else 'fail'} | Tests: {'pass' if result.tests_passed else 'fail'}"

    validation = f"Retries: {result.retries}"
    if result.diff:
        diff_lines = len(result.diff.splitlines())
        validation += f" | Diff: +{diff_lines} lines"

    return (
        f"## What\n{what}\n\n"
        f"## Why\n{why}\n\n"
        f"## Confidence\n{confidence}\n\n"
        f"## Validation\n{validation}\n\n"
        f"---\n*Automated by [Sigil](https://github.com/dylanmurray/sigil)*"
    )


def open_pr(
    client: GitHubClient, item: WorkItem, result: ExecutionResult, branch: str, repo: Path
) -> str | None:
    if not push_branch(repo, branch):
        return None

    title = _item_title(item)
    body = _format_pr_body(item, result)

    try:
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


def open_issue(
    client: GitHubClient, item: WorkItem, downgrade_context: str | None = None
) -> str | None:
    title = _item_title(item)
    body = _format_issue_body(item, downgrade_context)

    try:
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
    except GithubException as e:
        logger.warning("Issue creation failed: %s", e)
        return None


def cleanup_after_push(
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
        try:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree_path)],
                cwd=repo,
                capture_output=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        try:
            subprocess.run(
                ["git", "branch", "-D", branch],
                cwd=repo,
                capture_output=True,
                timeout=10,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass


def publish_results(
    repo: Path,
    config,
    client: GitHubClient,
    execution_results: list[tuple[WorkItem, ExecutionResult, str]],
    issue_items: list[tuple[WorkItem, str | None]],
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
            url = _gh_retry(open_pr)(client, item, result, branch, repo)
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
        try:
            url = _gh_retry(open_issue)(client, item, downgrade_context)
            if url:
                issue_urls.append(url)
                issue_count += 1
                logger.info("Opened issue: %s", url)
        except GithubException as e:
            logger.warning("Failed to open issue: %s", e)

    return pr_urls, issue_urls, pushed_branches
