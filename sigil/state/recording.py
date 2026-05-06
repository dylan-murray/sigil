import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sigil.core.config import SIGIL_DIR
from sigil.core.tools import apply_edit, create_file, multi_edit
from sigil.core.utils import arun

logger = logging.getLogger(__name__)

RECORDINGS_DIR = "recordings"
RESULT_CAP = 4000


@dataclass(frozen=True)
class ReplayResult:
    success: bool
    divergence: str
    worktree_path: str
    branch: str


class Recording:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, tool: str, args: dict, result: str) -> None:
        capped = result[:RESULT_CAP] if len(result) > RESULT_CAP else result
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tool": tool,
            "args": args,
            "result": capped,
        }
        with self._path.open("a") as f:
            f.write(json.dumps(entry) + "\n")


def read_recording(path: Path) -> list[dict]:
    if not path.exists():
        return []
    entries: list[dict] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


MUTATING_TOOLS = frozenset({"apply_edit", "create_file", "multi_edit"})


async def replay_recording(repo: Path, recording_path: Path) -> ReplayResult:
    entries = read_recording(recording_path)
    if not entries:
        return ReplayResult(
            success=False,
            divergence="Recording is empty.",
            worktree_path="",
            branch="",
        )

    slug = f"replay-{recording_path.stem}"
    try:
        worktree_path, branch = await _create_replay_worktree(repo, slug)
    except OSError as e:
        return ReplayResult(
            success=False,
            divergence=f"Worktree creation failed: {e}",
            worktree_path="",
            branch="",
        )

    for i, entry in enumerate(entries):
        tool = entry.get("tool", "")
        args = entry.get("args", {})

        if tool not in MUTATING_TOOLS:
            continue

        result = _replay_tool(worktree_path, tool, args)
        if result is not None:
            _cleanup_replay_worktree(repo, worktree_path, branch)
            return ReplayResult(
                success=False,
                divergence=f"Step {i} ({tool}) failed: {result}",
                worktree_path=str(worktree_path),
                branch=branch,
            )

    return ReplayResult(
        success=True,
        divergence="",
        worktree_path=str(worktree_path),
        branch=branch,
    )


def _replay_tool(worktree: Path, tool: str, args: dict) -> str | None:
    file = args.get("file", "")
    if tool == "apply_edit":
        old_content = args.get("old_content", "")
        new_content = args.get("new_content", "")
        result = apply_edit(worktree, file, old_content, new_content)
        if "Applied edit" not in result:
            return result
        return None

    if tool == "create_file":
        content = args.get("content", "")
        result = create_file(worktree, file, content)
        if "Created" not in result:
            return result
        return None

    if tool == "multi_edit":
        edits = args.get("edits", [])
        result = multi_edit(worktree, file, edits)
        if result.startswith("Applied") and "0/" not in result.split("Applied")[1][:5]:
            return None
        if "Applied 0/" in result:
            return result
        return None

    return None


async def _create_replay_worktree(repo: Path, slug: str) -> tuple[Path, str]:
    import time

    branch = f"sigil/replay/{slug}-{int(time.time())}"
    worktree_path = repo / ".sigil" / "worktrees" / slug
    if worktree_path.exists():
        await arun(
            ["git", "worktree", "remove", "--force", str(worktree_path)],
            cwd=repo,
            timeout=30,
        )
    if worktree_path.exists():
        shutil.rmtree(worktree_path)
    worktree_path.parent.mkdir(parents=True, exist_ok=True)

    rc, _, stderr = await arun(
        ["git", "worktree", "add", "--no-track", str(worktree_path), "-b", branch, "HEAD"],
        cwd=repo,
        timeout=30,
    )
    if rc != 0:
        raise OSError(f"Worktree creation failed: {stderr.strip()}")
    return worktree_path, branch


def _cleanup_replay_worktree(repo: Path, worktree_path: Path, branch: str) -> None:
    import asyncio

    async def _do_cleanup() -> None:
        await arun(
            ["git", "worktree", "remove", "--force", str(worktree_path)],
            cwd=repo,
            timeout=30,
        )
        await arun(["git", "branch", "-D", branch], cwd=repo, timeout=10)

    try:
        asyncio.get_running_loop().create_task(_do_cleanup())
    except RuntimeError:
        pass


def prune_recordings(repo: Path, retention: int) -> int:
    recordings_dir = repo / SIGIL_DIR / RECORDINGS_DIR
    if not recordings_dir.exists():
        return 0
    run_dirs = sorted(
        recordings_dir.iterdir(),
        key=lambda p: p.stat().st_mtime,
    )
    if len(run_dirs) <= retention:
        return 0
    to_remove = run_dirs[: len(run_dirs) - retention]
    removed = 0
    for d in to_remove:
        if d.is_dir():
            shutil.rmtree(d)
            removed += 1
    return removed