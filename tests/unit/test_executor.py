from __future__ import annotations

import subprocess
import time
from pathlib import Path
from unittest.mock import patch

from sigil.config import Config
from sigil.executor import (
    ExecutionResult,
    _branch_name,
    _cleanup_worktree,
    _create_worktree,
    _dedup_slugs,
    _execute_in_worktree,
    _read_file,
    _apply_edit,
    _create_file,
    _ChangeTracker,
    _slugify,
    _validate_path,
    execute_parallel,
)
from sigil.ideation import FeatureIdea
from sigil.maintenance import Finding


def _make_finding(**kw) -> Finding:
    defaults = dict(
        category="dead_code",
        file="src/utils.py",
        line=42,
        description="Unused import",
        risk="low",
        suggested_fix="Remove it",
        disposition="pr",
        priority=1,
        rationale="Not referenced",
    )
    defaults.update(kw)
    return Finding(**defaults)


def _make_idea(**kw) -> FeatureIdea:
    defaults = dict(
        title="Add retry logic",
        description="Retry failed HTTP calls",
        rationale="Improves reliability",
        complexity="low",
        disposition="pr",
        priority=2,
    )
    defaults.update(kw)
    return FeatureIdea(**defaults)


def test_slugify_finding():
    f = _make_finding(category="dead_code", file="src/utils.py")
    assert _slugify(f) == "dead-code-utils"


def test_slugify_idea():
    idea = _make_idea(title="Add retry logic")
    assert _slugify(idea) == "add-retry-logic"


def test_slugify_special_chars():
    idea = _make_idea(title="Fix: the @#$ broken!! stuff (v2)")
    assert _slugify(idea) == "fix-the-broken-stuff-v2"


def test_slugify_truncates_to_50():
    idea = _make_idea(title="a" * 100)
    assert len(_slugify(idea)) == 50


def test_branch_name_uses_epoch():
    name = _branch_name("my-slug")
    assert name.startswith("sigil/auto/my-slug-")
    ts = int(name.split("-")[-1])
    assert abs(ts - int(time.time())) < 5


def test_dedup_slugs_no_collision():
    items = [
        _make_finding(category="dead_code", file="a.py"),
        _make_finding(category="security", file="b.py"),
    ]
    assert _dedup_slugs(items) == ["dead-code-a", "security-b"]


def test_dedup_slugs_with_collision():
    items = [
        _make_finding(category="dead_code", file="utils.py"),
        _make_finding(category="dead_code", file="utils.py"),
        _make_finding(category="dead_code", file="utils.py"),
    ]
    slugs = _dedup_slugs(items)
    assert slugs == ["dead-code-utils", "dead-code-utils-1", "dead-code-utils-2"]
    assert len(set(slugs)) == 3


def test_validate_path_blocks_traversal(tmp_path):
    assert _validate_path(tmp_path, "../../etc/passwd") is None


def test_validate_path_allows_valid(tmp_path):
    (tmp_path / "foo.py").write_text("x")
    assert _validate_path(tmp_path, "foo.py") == (tmp_path / "foo.py").resolve()


def test_validate_path_blocks_absolute(tmp_path):
    assert _validate_path(tmp_path, "/etc/passwd") is None


def test_read_file_rejects_traversal(tmp_path):
    result = _read_file(tmp_path, "../../etc/passwd")
    assert "Access denied" in result


def test_apply_edit_rejects_traversal(tmp_path):
    tracker = _ChangeTracker()
    result = _apply_edit(tmp_path, "../outside.py", "old", "new", tracker)
    assert "Access denied" in result


def test_create_file_rejects_traversal(tmp_path):
    tracker = _ChangeTracker()
    result = _create_file(tmp_path, "../../evil.py", "content", tracker)
    assert "Access denied" in result


def test_create_worktree(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"], cwd=repo, capture_output=True, check=True
    )

    memory_dir = repo / ".sigil" / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "working.md").write_text("hello")

    worktree_path, branch = _create_worktree(repo, "test-slug")

    assert worktree_path.exists()
    assert branch.startswith("sigil/auto/test-slug-")
    parts = branch.split("-")
    assert parts[-1].isdigit()
    assert (worktree_path / ".sigil" / "memory" / "working.md").read_text() == "hello"

    subprocess.run(["git", "worktree", "remove", str(worktree_path)], cwd=repo, capture_output=True)


def test_create_worktree_no_memory(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"], cwd=repo, capture_output=True, check=True
    )

    worktree_path, branch = _create_worktree(repo, "no-mem")

    assert worktree_path.exists()
    assert not (worktree_path / ".sigil" / "memory").exists()

    subprocess.run(["git", "worktree", "remove", str(worktree_path)], cwd=repo, capture_output=True)


def test_cleanup_worktree(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"], cwd=repo, capture_output=True, check=True
    )

    worktree_path, branch = _create_worktree(repo, "cleanup-test")
    assert worktree_path.exists()

    _cleanup_worktree(repo, worktree_path, branch)

    assert not worktree_path.exists()
    result = subprocess.run(
        ["git", "branch", "--list", branch], cwd=repo, capture_output=True, text=True
    )
    assert branch not in result.stdout


def test_execute_in_worktree_failure():
    config = Config()
    finding = _make_finding()

    with patch(
        "sigil.executor._create_worktree", side_effect=subprocess.CalledProcessError(1, "git")
    ):
        item, result, branch = _execute_in_worktree(
            Path("/fake"), config, finding, "dead-code-utils"
        )

    assert item is finding
    assert result.success is False
    assert "Worktree creation failed" in result.failure_reason
    assert branch == ""


def test_execute_parallel_limits_concurrency():
    config = Config(max_parallel_agents=1)
    items = [_make_finding(file=f"src/f{i}.py") for i in range(3)]

    peak = [0]
    active = [0]

    def fake_execute(repo, cfg, item, slug):
        active[0] += 1
        peak[0] = max(peak[0], active[0])
        time.sleep(0.05)
        active[0] -= 1
        return (
            item,
            ExecutionResult(
                success=True,
                diff="diff",
                lint_passed=True,
                tests_passed=True,
                retries=0,
                failure_reason=None,
            ),
            f"sigil/auto/{slug}",
        )

    with patch("sigil.executor._execute_in_worktree", side_effect=fake_execute):
        results = execute_parallel(Path("/fake"), config, items)

    assert len(results) == 3
    assert peak[0] == 1
