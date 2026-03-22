import asyncio
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

from sigil.config import Config
from sigil.executor import (
    ExecutionResult,
    _branch_name,
    _cleanup_worktree,
    _commit_changes,
    _create_worktree,
    _dedup_slugs,
    _execute_in_worktree,
    _rebase_onto_main,
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


async def test_create_worktree(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"], cwd=repo, capture_output=True, check=True
    )

    memory_dir = repo / ".sigil" / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "working.md").write_text("hello")

    worktree_path, branch = await _create_worktree(repo, "test-slug")

    assert worktree_path.exists()
    assert branch.startswith("sigil/auto/test-slug-")
    parts = branch.split("-")
    assert parts[-1].isdigit()
    assert (worktree_path / ".sigil" / "memory" / "working.md").read_text() == "hello"

    subprocess.run(["git", "worktree", "remove", str(worktree_path)], cwd=repo, capture_output=True)


async def test_create_worktree_no_memory(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"], cwd=repo, capture_output=True, check=True
    )

    worktree_path, branch = await _create_worktree(repo, "no-mem")

    assert worktree_path.exists()
    assert not (worktree_path / ".sigil" / "memory").exists()

    subprocess.run(["git", "worktree", "remove", str(worktree_path)], cwd=repo, capture_output=True)


async def test_cleanup_worktree(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"], cwd=repo, capture_output=True, check=True
    )

    worktree_path, branch = await _create_worktree(repo, "cleanup-test")
    assert worktree_path.exists()

    await _cleanup_worktree(repo, worktree_path, branch)

    assert not worktree_path.exists()
    result = subprocess.run(
        ["git", "branch", "--list", branch], cwd=repo, capture_output=True, text=True
    )
    assert branch not in result.stdout


async def test_execute_in_worktree_failure():
    config = Config()
    finding = _make_finding()

    with patch("sigil.executor._create_worktree", side_effect=OSError("git worktree failed")):
        item, result, branch = await _execute_in_worktree(
            Path("/fake"), config, finding, "dead-code-utils"
        )

    assert item is finding
    assert result.success is False
    assert "Worktree creation failed" in result.failure_reason
    assert branch == ""


async def test_execute_parallel_limits_concurrency():
    config = Config(max_parallel_agents=1)
    items = [_make_finding(file=f"src/f{i}.py") for i in range(3)]

    peak = [0]
    active = [0]

    async def fake_execute(
        repo, cfg, item, slug, *, agent_config=None, mcp_mgr=None, on_status=None
    ):
        active[0] += 1
        peak[0] = max(peak[0], active[0])
        await asyncio.sleep(0.05)
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
        results = await execute_parallel(Path("/fake"), config, items)

    assert len(results) == 3
    assert peak[0] == 1


def _init_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    return repo


async def test_commit_changes(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "foo.py").write_text("print('hi')\n")
    tracker = _ChangeTracker()
    tracker.created.add("foo.py")
    ok, err = await _commit_changes(repo, _make_finding(), tracker)
    assert ok is True
    log = subprocess.run(
        ["git", "log", "--oneline", "-1"], cwd=repo, capture_output=True, text=True
    )
    assert "sigil:" in log.stdout


async def test_rebase_onto_main_memory_conflict(tmp_path):
    repo = _init_repo(tmp_path)
    mem_dir = repo / ".sigil" / "memory"
    mem_dir.mkdir(parents=True)
    (mem_dir / "working.md").write_text("base\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "add memory"], cwd=repo, capture_output=True)

    worktree_path, branch = await _create_worktree(repo, "rebase-mem")
    (worktree_path / ".sigil" / "memory" / "working.md").write_text("branch change\n")
    subprocess.run(["git", "add", "-A"], cwd=worktree_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "branch memory"], cwd=worktree_path, capture_output=True)

    (mem_dir / "working.md").write_text("main change\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "main memory"], cwd=repo, capture_output=True)

    ok, err = await _rebase_onto_main(repo, worktree_path)
    assert ok is True
    assert err == ""
    content = (worktree_path / ".sigil" / "memory" / "working.md").read_text()
    assert content == "main change\n"
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree_path)],
        cwd=repo,
        capture_output=True,
    )


async def test_rebase_onto_main_code_conflict(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "app.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "add app"], cwd=repo, capture_output=True)

    worktree_path, branch = await _create_worktree(repo, "rebase-code")
    (worktree_path / "app.py").write_text("x = 'branch'\n")
    subprocess.run(["git", "add", "-A"], cwd=worktree_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "branch edit"], cwd=worktree_path, capture_output=True)

    (repo / "app.py").write_text("x = 'main'\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "main edit"], cwd=repo, capture_output=True)

    ok, err = await _rebase_onto_main(repo, worktree_path)
    assert ok is False
    assert "app.py" in err
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree_path)],
        cwd=repo,
        capture_output=True,
    )


async def test_execute_in_worktree_failure_sets_downgraded():
    config = Config()
    finding = _make_finding()
    fail_result = ExecutionResult(
        success=False,
        diff="",
        lint_passed=False,
        tests_passed=False,
        retries=2,
        failure_reason="Tests failed after all retries.",
    )

    async def fake_create(*a, **kw):
        return (Path("/wt"), "sigil/auto/x")

    async def fake_execute(*a, **kw):
        return (fail_result, _ChangeTracker())

    with (
        patch("sigil.executor._create_worktree", side_effect=fake_create),
        patch("sigil.executor.execute", side_effect=fake_execute),
    ):
        item, result, branch = await _execute_in_worktree(Path("/fake"), config, finding, "x")

    assert result.downgraded is True
    assert "Tests failed" in result.downgrade_context
    assert result.retries == 2


async def test_execute_in_worktree_rebase_conflict_downgrades():
    config = Config()
    finding = _make_finding()
    ok_result = ExecutionResult(
        success=True,
        diff="some diff",
        lint_passed=True,
        tests_passed=True,
        retries=0,
        failure_reason=None,
    )

    async def fake_create(*a, **kw):
        return (Path("/wt"), "sigil/auto/x")

    async def fake_execute(*a, **kw):
        return (ok_result, _ChangeTracker())

    async def fake_commit(*a, **kw):
        return (True, "")

    async def fake_rebase(*a, **kw):
        return (False, "Rebase conflict in app.py")

    with (
        patch("sigil.executor._create_worktree", side_effect=fake_create),
        patch("sigil.executor.execute", side_effect=fake_execute),
        patch("sigil.executor._commit_changes", side_effect=fake_commit),
        patch("sigil.executor._rebase_onto_main", side_effect=fake_rebase),
    ):
        item, result, branch = await _execute_in_worktree(Path("/fake"), config, finding, "x")

    assert result.success is False
    assert result.downgraded is True
    assert "rebase onto main failed" in result.downgrade_context
    assert "app.py" in result.downgrade_context


def test_format_run_context_with_downgraded():
    from sigil.cli import _format_run_context

    findings = [_make_finding()]
    ok = ExecutionResult(
        success=True, diff="+x", lint_passed=True, tests_passed=True, retries=0, failure_reason=None
    )
    down = ExecutionResult(
        success=False,
        diff="",
        lint_passed=False,
        tests_passed=False,
        retries=1,
        failure_reason="Tests failed",
        downgraded=True,
        downgrade_context="Execution failed after 1 retries.\nReason: Tests failed",
    )
    results = [("fix utils", ok), ("fix broken", down)]
    ctx = _format_run_context(findings, [], False, results)
    assert "1 succeeded" in ctx
    assert "1 failed" in ctx
    assert "1 downgraded" in ctx
    assert "[DOWNGRADED] fix broken" in ctx
    assert "[OK] fix utils" in ctx
