import asyncio
import logging
import shutil
from pathlib import Path

from sigil.core.config import Config
from sigil.core.utils import arun
from sigil.integrations.github import GitHubClient

logger = logging.getLogger(__name__)

STALE_BRANCH_PREFIX = "sigil/auto/"


async def cleanup_stale_resources(
    repo: Path,
    config: Config,
    gh_client: GitHubClient | None = None,
) -> list[str]:
    actions: list[str] = []

    try:
        stale_worktrees = await _find_stale_worktrees(repo)
    except Exception as exc:
        logger.warning("Failed to find stale worktrees: %s", exc)
        stale_worktrees = []

    for worktree_path, branch_name in stale_worktrees:
        if await _remove_worktree(repo, worktree_path):
            actions.append(f"Removed orphaned worktree {worktree_path} (branch {branch_name})")
        else:
            actions.append(f"Failed to remove worktree {worktree_path}")

    try:
        stale_branches = await _find_stale_branches(repo, gh_client)
    except Exception as exc:
        logger.warning("Failed to find stale branches: %s", exc)
        stale_branches = []

    for branch in stale_branches:
        if await _remove_branch(repo, branch):
            actions.append(f"Removed orphaned branch {branch}")
        else:
            actions.append(f"Failed to remove branch {branch}")

    try:
        temp_cleaned = _cleanup_temp_files(repo)
    except Exception as exc:
        logger.warning("Failed to clean temp files: %s", exc)
        temp_cleaned = []

    for temp_path in temp_cleaned:
        actions.append(f"Removed temp file {temp_path}")

    return actions


async def _find_stale_worktrees(repo: Path) -> list[tuple[str, str]]:
    rc, stdout, _ = await arun(["git", "worktree", "list", "--porcelain"], cwd=repo, timeout=10)
    if rc != 0:
        return []

    stale: list[tuple[str, str]] = []
    worktree_path = ""
    branch_name = ""

    for line in stdout.splitlines():
        if line.startswith("worktree "):
            worktree_path = line[len("worktree ") :]
        elif line.startswith("branch "):
            branch_name = line[len("branch ") :]
        elif line == "":
            if worktree_path and ".sigil/worktrees/" in worktree_path:
                path_obj = Path(worktree_path)
                branch_short = branch_name.removeprefix("refs/heads/") if branch_name else ""
                is_orphaned = not branch_short or not await _branch_exists(repo, branch_short)
                if is_orphaned or not path_obj.exists() or not any(path_obj.iterdir()):
                    stale.append((worktree_path, branch_short))
            worktree_path = ""
            branch_name = ""

    if worktree_path and ".sigil/worktrees/" in worktree_path:
        path_obj = Path(worktree_path)
        branch_short = branch_name.removeprefix("refs/heads/") if branch_name else ""
        is_orphaned = not branch_short or not await _branch_exists(repo, branch_short)
        if is_orphaned or not path_obj.exists() or not any(path_obj.iterdir()):
            stale.append((worktree_path, branch_short))

    return stale


async def _branch_exists(repo: Path, branch: str) -> bool:
    rc, _, _ = await arun(["git", "rev-parse", "--verify", branch], cwd=repo, timeout=5)
    return rc == 0


async def _remove_worktree(repo: Path, worktree_path: str) -> bool:
    rc, _, _ = await arun(
        ["git", "worktree", "remove", "--force", worktree_path],
        cwd=repo,
        timeout=30,
    )
    if rc == 0:
        return True

    try:
        shutil.rmtree(worktree_path)
        return True
    except OSError as exc:
        logger.warning("Failed to remove worktree %s: %s", worktree_path, exc)
        return False


async def _find_stale_branches(repo: Path, gh_client: GitHubClient | None) -> list[str]:
    rc, stdout, _ = await arun(
        ["git", "branch", "--list", f"{STALE_BRANCH_PREFIX}*"],
        cwd=repo,
        timeout=10,
    )
    if rc != 0:
        return []

    branches = [line.strip().lstrip("* ") for line in stdout.splitlines() if line.strip()]
    if not branches or gh_client is None:
        return []

    open_pr_branches = await _get_open_pr_branches(gh_client)
    if open_pr_branches is None:
        return []

    stale: list[str] = []
    for branch in branches:
        if branch not in open_pr_branches:
            stale.append(branch)

    return stale


async def _get_open_pr_branches(gh_client: GitHubClient) -> set[str] | None:
    def _fetch() -> set[str]:
        branches: set[str] = set()
        for pr in gh_client.repo.get_pulls(state="open"):
            if any(lbl.name == "sigil" for lbl in pr.labels):
                branches.add(pr.head.ref)
        return branches

    try:
        return await asyncio.to_thread(_fetch)
    except Exception as exc:
        logger.warning("Failed to fetch open PR branches: %s", exc)
        return None


async def _remove_branch(repo: Path, branch: str) -> bool:
    rc, _, _ = await arun(["git", "branch", "-D", branch], cwd=repo, timeout=10)
    return rc == 0


def _cleanup_temp_files(repo: Path) -> list[str]:
    sigil_dir = repo / ".sigil"
    if not sigil_dir.exists():
        return []

    removed: list[str] = []
    for path in sigil_dir.glob("temp_*"):
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            removed.append(str(path))
        except OSError as exc:
            logger.warning("Failed to remove temp file %s: %s", path, exc)

    return removed
