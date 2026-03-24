import asyncio
import json
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sigil.config import Config
from sigil.executor import (
    ExecutionResult,
    FailureType,
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
    _validate_path,
    execute,
    execute_parallel,
)
from sigil.chronic import slugify
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
    assert slugify(f) == "dead-code-utils"


def test_slugify_idea():
    idea = _make_idea(title="Add retry logic")
    assert slugify(idea) == "add-retry-logic"


def test_slugify_special_chars():
    idea = _make_idea(title="Fix: the @#$ broken!! stuff (v2)")
    assert slugify(idea) == "fix-the-broken-stuff-v2"


def test_slugify_truncates_to_50():
    idea = _make_idea(title="a" * 100)
    assert len(slugify(idea)) == 50


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
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, capture_output=True, check=True)
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
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, capture_output=True, check=True)
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
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, capture_output=True, check=True)
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
                hooks_passed=True,
                failed_hook=None,
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
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, capture_output=True, check=True)
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
        hooks_passed=False,
        failed_hook="pytest",
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
        hooks_passed=True,
        failed_hook=None,
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


async def test_execute_in_worktree_failed_commit_clears_diff():
    config = Config()
    finding = _make_finding()
    fail_result = ExecutionResult(
        success=False,
        diff="some diff",
        hooks_passed=False,
        failed_hook="pytest",
        retries=1,
        failure_reason="Tests failed after all retries.",
    )

    async def fake_create(*a, **kw):
        return (Path("/wt"), "sigil/auto/x")

    async def fake_execute(*a, **kw):
        return (fail_result, _ChangeTracker())

    async def fake_commit(*a, **kw):
        return (False, "No files to commit")

    with (
        patch("sigil.executor._create_worktree", side_effect=fake_create),
        patch("sigil.executor.execute", side_effect=fake_execute),
        patch("sigil.executor._commit_changes", side_effect=fake_commit),
    ):
        item, result, branch = await _execute_in_worktree(Path("/fake"), config, finding, "x")

    assert result.downgraded is True
    assert result.diff == ""
    assert result.failure_reason == "Tests failed after all retries."


def test_read_file_large_file_capped(tmp_path):
    big = tmp_path / "huge.py"
    big.write_text("\n".join(f"line_{i}" for i in range(5000)))
    result = _read_file(tmp_path, "huge.py")
    content_lines = [line for line in result.splitlines() if not line.startswith("[truncated")]
    assert len(content_lines) == 2000
    assert "[truncated" in result
    assert "offset=2001" in result


def test_read_file_byte_cap_on_fat_lines(tmp_path):
    fat = tmp_path / "bundle.min.js"
    fat.write_text("\n".join("x" * 1000 for _ in range(100)))
    result = _read_file(tmp_path, "bundle.min.js")
    truncation_msg = result[result.index("[truncated") :]
    content_bytes = len(result.encode()) - len(truncation_msg.encode()) - 1
    assert content_bytes <= 50_000
    assert "[truncated" in result


async def test_executor_handler_truncates_large_file(tmp_path, monkeypatch):
    big = tmp_path / "huge.py"
    big.write_text("\n".join(f"line_{i}" for i in range(5000)))

    read_call = MagicMock()
    read_call.id = "call_read"
    read_call.function.name = "read_file"
    read_call.function.arguments = json.dumps({"file": "huge.py"})

    done_call = MagicMock()
    done_call.id = "call_done"
    done_call.function.name = "done"
    done_call.function.arguments = json.dumps({"summary": "done"})

    msg1 = MagicMock()
    msg1.tool_calls = [read_call]
    msg1.content = None
    choice1 = MagicMock()
    choice1.message = msg1
    resp1 = MagicMock()
    resp1.choices = [choice1]

    msg2 = MagicMock()
    msg2.tool_calls = [done_call]
    msg2.content = None
    choice2 = MagicMock()
    choice2.message = msg2
    resp2 = MagicMock()
    resp2.choices = [choice2]

    captured_messages: list[list[dict]] = []
    call_count = {"n": 0}

    async def fake_acompletion(**kwargs):
        captured_messages.append(kwargs.get("messages", []))
        idx = call_count["n"]
        call_count["n"] += 1
        return [resp1, resp2][idx]

    monkeypatch.setattr("sigil.agent.acompletion", fake_acompletion)
    monkeypatch.setattr("sigil.agent.mask_old_tool_outputs", lambda m, **kw: None)

    from sigil.executor import EXECUTOR_TOOLS, _run_llm_edits

    tracker = _ChangeTracker()
    messages: list[dict] = [{"role": "user", "content": "implement change"}]
    await _run_llm_edits(tmp_path, "test-model", messages, tracker, EXECUTOR_TOOLS)

    tool_msgs = [
        m
        for msgs in captured_messages
        for m in msgs
        if isinstance(m, dict) and m.get("role") == "tool"
    ]
    read_response = next(m for m in tool_msgs if m["tool_call_id"] == "call_read")
    content_lines = [
        line for line in read_response["content"].splitlines() if not line.startswith("[truncated")
    ]
    assert len(content_lines) == 2000
    assert "[truncated" in read_response["content"]
    assert "offset=2001" in read_response["content"]


def test_format_run_context_with_downgraded():
    from sigil.cli import _format_run_context

    findings = [_make_finding()]
    ok = ExecutionResult(
        success=True, diff="+x", hooks_passed=True, failed_hook=None, retries=0, failure_reason=None
    )
    down = ExecutionResult(
        success=False,
        diff="",
        hooks_passed=False,
        failed_hook="pytest",
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


_MOCK_SUMMARY = (
    "Fixed the security issue in config.py by removing the hardcoded credential. "
    "Updated the load_config function to read from environment variables instead. "
    "Added test_config.py with parametrized tests for valid and invalid configs."
)


@pytest.fixture()
def _mock_execute_deps(monkeypatch):
    async def fake_select_knowledge(*a, **kw):
        return {}

    async def fake_run_llm_edits(repo, model, messages, tracker, tools, **kw):
        return _MOCK_SUMMARY, False

    async def fake_rollback(repo, tracker):
        pass

    monkeypatch.setattr("sigil.executor.select_knowledge", fake_select_knowledge)
    monkeypatch.setattr("sigil.executor._run_llm_edits", fake_run_llm_edits)
    monkeypatch.setattr("sigil.executor._rollback", fake_rollback)


async def test_execute_no_hooks_succeeds(tmp_path, monkeypatch, _mock_execute_deps):
    async def fake_get_diff(repo):
        return "+added line"

    run_command_calls = []

    async def fake_run_command(repo, cmd):
        run_command_calls.append(cmd)
        return True, ""

    monkeypatch.setattr("sigil.executor._get_diff", fake_get_diff)
    monkeypatch.setattr("sigil.executor._run_command", fake_run_command)

    config = Config(pre_hooks=[], post_hooks=[])
    result, tracker = await execute(tmp_path, config, _make_finding())

    assert result.success is True
    assert result.hooks_passed is True
    assert result.failed_hook is None
    assert result.failure_type is None
    assert result.doom_loop_detected is False
    assert run_command_calls == []


async def test_execute_pre_hook_failure_aborts(tmp_path, monkeypatch, _mock_execute_deps):
    llm_called = []

    async def fake_run_llm_edits(repo, model, messages, tracker, tools, **kw):
        llm_called.append(True)
        return _MOCK_SUMMARY, False

    monkeypatch.setattr("sigil.executor._run_llm_edits", fake_run_llm_edits)

    run_command_calls = []

    async def fake_run_command(repo, cmd):
        run_command_calls.append(cmd)
        if cmd == "mypy .":
            return False, "type errors found"
        return True, ""

    monkeypatch.setattr("sigil.executor._run_command", fake_run_command)

    config = Config(pre_hooks=["mypy ."], post_hooks=["ruff format .", "pytest"])
    result, tracker = await execute(tmp_path, config, _make_finding())

    assert result.success is False
    assert result.hooks_passed is False
    assert result.failed_hook == "mypy ."
    assert "Pre-hook failed" in result.failure_reason
    assert result.failure_type == FailureType.PRE_HOOK
    assert llm_called == []
    assert "pytest" not in run_command_calls
    assert "ruff format ." not in run_command_calls


async def test_execute_post_hooks_short_circuit(tmp_path, monkeypatch, _mock_execute_deps):
    async def fake_get_diff(repo):
        return ""

    monkeypatch.setattr("sigil.executor._get_diff", fake_get_diff)

    run_command_calls = []

    async def fake_run_command(repo, cmd):
        run_command_calls.append(cmd)
        if cmd == "ruff check .":
            return False, "lint errors"
        return True, ""

    monkeypatch.setattr("sigil.executor._run_command", fake_run_command)

    config = Config(
        pre_hooks=[], post_hooks=["ruff format .", "ruff check .", "pytest"], max_retries=0
    )
    result, tracker = await execute(tmp_path, config, _make_finding())

    assert result.hooks_passed is False
    assert result.failed_hook == "ruff check ."
    assert result.failure_type == FailureType.NO_CHANGES
    assert "ruff format ." in run_command_calls
    assert "ruff check ." in run_command_calls
    assert "pytest" not in run_command_calls


async def test_execute_post_hook_failure_triggers_retry(tmp_path, monkeypatch, _mock_execute_deps):
    attempt = {"n": 0}

    async def fake_run_command(repo, cmd):
        if cmd == "pytest":
            attempt["n"] += 1
            if attempt["n"] == 1:
                return False, "test failed"
            return True, ""
        return True, ""

    async def fake_get_diff(repo):
        return "+fixed"

    captured_messages = []

    long_summary = (
        "Fixed the security issue in config.py by removing the hardcoded credential. "
        "Updated the load_config function to read from environment variables instead. "
        "Added test_config.py with parametrized tests for valid and invalid configs."
    )

    async def fake_run_llm_edits(repo, model, messages, tracker, tools, **kw):
        captured_messages.append([m for m in messages if isinstance(m, dict)])
        return long_summary, False

    monkeypatch.setattr("sigil.executor._run_command", fake_run_command)
    monkeypatch.setattr("sigil.executor._get_diff", fake_get_diff)
    monkeypatch.setattr("sigil.executor._run_llm_edits", fake_run_llm_edits)

    config = Config(pre_hooks=[], post_hooks=["ruff format .", "pytest"], max_retries=1)
    result, tracker = await execute(tmp_path, config, _make_finding())

    assert result.success is True
    assert result.hooks_passed is True
    assert result.failed_hook is None
    assert result.retries == 1
    assert len(captured_messages) == 2
    retry_msgs = captured_messages[1]

    def _get_text(msg: dict) -> str:
        c = msg.get("content", "")
        if isinstance(c, list):
            return " ".join(part.get("text", "") for part in c if isinstance(part, dict))
        return c

    error_msg = next(m for m in retry_msgs if "failed a post-commit hook" in _get_text(m).lower())
    assert "pytest" in _get_text(error_msg)
    assert "test failed" in _get_text(error_msg)


async def test_execute_post_hook_exhausts_retries(tmp_path, monkeypatch, _mock_execute_deps):
    rollback_called = []

    async def fake_rollback(repo, tracker):
        rollback_called.append(True)

    monkeypatch.setattr("sigil.executor._rollback", fake_rollback)

    async def fake_run_command(repo, cmd):
        if cmd == "pytest":
            return False, "always fails"
        return True, ""

    async def fake_get_diff(repo):
        return "+some changes"

    monkeypatch.setattr("sigil.executor._run_command", fake_run_command)
    monkeypatch.setattr("sigil.executor._get_diff", fake_get_diff)

    config = Config(pre_hooks=[], post_hooks=["ruff format .", "pytest"], max_retries=2)
    result, tracker = await execute(tmp_path, config, _make_finding())

    assert result.success is False
    assert result.hooks_passed is False
    assert result.failed_hook == "pytest"
    assert result.retries == 2
    assert "Post-hooks failed" in result.failure_reason
    assert result.failure_type == FailureType.POST_HOOK
    assert rollback_called == [], "should NOT rollback when there is a diff to preserve"


async def test_failure_type_doom_loop_no_diff(tmp_path, monkeypatch, _mock_execute_deps):
    async def fake_run_llm_edits(repo, model, messages, tracker, tools, **kw):
        return None, True

    async def fake_get_diff(repo):
        return ""

    async def fake_rollback(repo, tracker):
        pass

    monkeypatch.setattr("sigil.executor._run_llm_edits", fake_run_llm_edits)
    monkeypatch.setattr("sigil.executor._get_diff", fake_get_diff)
    monkeypatch.setattr("sigil.executor._rollback", fake_rollback)

    config = Config(pre_hooks=[], post_hooks=[], max_retries=0)
    result, tracker = await execute(tmp_path, config, _make_finding())

    assert result.success is False
    assert result.failure_type == FailureType.DOOM_LOOP
    assert result.doom_loop_detected is True


async def test_failure_type_doom_loop_beats_post_hook(tmp_path, monkeypatch, _mock_execute_deps):
    async def fake_run_llm_edits(repo, model, messages, tracker, tools, **kw):
        return None, True

    async def fake_run_command(repo, cmd):
        return False, "lint error"

    async def fake_get_diff(repo):
        return "+changes"

    monkeypatch.setattr("sigil.executor._run_llm_edits", fake_run_llm_edits)
    monkeypatch.setattr("sigil.executor._run_command", fake_run_command)
    monkeypatch.setattr("sigil.executor._get_diff", fake_get_diff)

    config = Config(pre_hooks=[], post_hooks=["ruff check ."], max_retries=0)
    result, tracker = await execute(tmp_path, config, _make_finding())

    assert result.success is False
    assert result.failure_type == FailureType.DOOM_LOOP
    assert result.doom_loop_detected is True


async def test_doom_loop_detected_on_success(tmp_path, monkeypatch, _mock_execute_deps):
    async def fake_run_llm_edits(repo, model, messages, tracker, tools, **kw):
        return "summary", True

    async def fake_run_command(repo, cmd):
        return True, ""

    async def fake_get_diff(repo):
        return "+changes"

    monkeypatch.setattr("sigil.executor._run_llm_edits", fake_run_llm_edits)
    monkeypatch.setattr("sigil.executor._run_command", fake_run_command)
    monkeypatch.setattr("sigil.executor._get_diff", fake_get_diff)

    config = Config(pre_hooks=[], post_hooks=["ruff check ."], max_retries=0)
    result, tracker = await execute(tmp_path, config, _make_finding())

    assert result.success is True
    assert result.failure_type is None
    assert result.doom_loop_detected is True
