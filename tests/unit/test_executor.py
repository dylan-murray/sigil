import asyncio
import json
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sigil.core.agent import AgentResult
from sigil.core.config import Config
from sigil.core.security import validate_path
from sigil.pipeline import executor as executor_mod
from sigil.pipeline.executor import (
    _ChangeTracker,
    _apply_edit,
    _branch_name,
    _cleanup_worktree,
    _commit_changes,
    _create_file,
    _create_worktree,
    _dedup_slugs,
    _execute_in_worktree,
    _preload_relevant_files,
    _read_file,
    _rebase_onto_main,
    execute,
    execute_parallel,
)
from sigil.pipeline.ideation import FeatureIdea
from sigil.pipeline.maintenance import Finding
from sigil.pipeline.models import ExecutionResult, FailureType
from sigil.state.chronic import slugify


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


def testvalidate_path_blocks_traversal(tmp_path):
    assert validate_path(tmp_path, "../../etc/passwd") is None


def testvalidate_path_allows_valid(tmp_path):
    (tmp_path / "foo.py").write_text("x")
    assert validate_path(tmp_path, "foo.py") == (tmp_path / "foo.py").resolve()


def testvalidate_path_blocks_absolute(tmp_path):
    assert validate_path(tmp_path, "/etc/passwd") is None


def test_read_file_rejects_traversal(tmp_path):
    result = _read_file(tmp_path, "../../etc/passwd")
    assert "Access denied" in result


def test_apply_edit_rejects_traversal(tmp_path):
    tracker = _ChangeTracker()
    result = _apply_edit(tmp_path, "../outside.py", "old", "new", tracker)
    assert "Access denied" in result


def _setup_edit(tmp_path, filename, content):
    (tmp_path / filename).write_text(content)
    tracker = _ChangeTracker()
    tracker.record_read(tmp_path, filename)
    return tracker


def test_apply_edit_exact_match(tmp_path):
    tracker = _setup_edit(tmp_path, "foo.py", "def hello():\n    return 1\n")
    result = _apply_edit(tmp_path, "foo.py", "return 1", "return 2", tracker)
    assert "Applied edit" in result
    assert "foo.py" in tracker.modified
    assert "return 2" in (tmp_path / "foo.py").read_text()


def test_apply_edit_fuzzy_whitespace_diff(tmp_path):
    tracker = _setup_edit(tmp_path, "foo.py", "def hello():\n    return 1\n    x = 2\n")
    result = _apply_edit(
        tmp_path,
        "foo.py",
        "def hello():\n    return 1\n    x= 2\n",
        "def hello():\n    return 42\n    x = 2\n",
        tracker,
    )
    assert "Applied edit" in result
    assert "fuzzy match" in result
    assert "return 42" in (tmp_path / "foo.py").read_text()


def test_apply_edit_fuzzy_extra_blank_line(tmp_path):
    tracker = _setup_edit(tmp_path, "foo.py", "def a():\n    pass\n\ndef b():\n    pass\n")
    result = _apply_edit(
        tmp_path,
        "foo.py",
        "def a():\n    pass\ndef b():\n    pass\n",
        "def a():\n    return 1\ndef b():\n    pass\n",
        tracker,
    )
    assert "Applied edit" in result
    assert "fuzzy match" in result


def test_apply_edit_fuzzy_rejects_ambiguous(tmp_path):
    tracker = _setup_edit(tmp_path, "foo.py", "def a():\n    return 1\n\ndef b():\n    return 1\n")
    result = _apply_edit(
        tmp_path, "foo.py", "def x():\n    return 1\n", "def x():\n    return 2\n", tracker
    )
    assert "not found" in result or "matches" in result


def test_apply_edit_fuzzy_no_match(tmp_path):
    tracker = _setup_edit(tmp_path, "foo.py", "def hello():\n    return 1\n")
    result = _apply_edit(
        tmp_path, "foo.py", "completely_different_content()\nnothing_here()\n", "new stuff", tracker
    )
    assert "not found" in result


def test_apply_edit_ambiguous_shows_line_numbers(tmp_path):
    content = "import os\n\ndef foo():\n    return 1\n\ndef bar():\n    return 1\n"
    tracker = _setup_edit(tmp_path, "foo.py", content)
    result = _apply_edit(tmp_path, "foo.py", "return 1", "return 2", tracker)
    assert "matches 2 locations" in result
    assert "line 4" in result.lower() or "Match at line 4" in result
    assert "line 7" in result.lower() or "Match at line 7" in result


def test_apply_edit_ambiguous_shows_context_windows(tmp_path):
    content = "a = 1\nb = 2\nx = 10\nc = 3\nd = 4\nx = 10\ne = 5\n"
    tracker = _setup_edit(tmp_path, "foo.py", content)
    result = _apply_edit(tmp_path, "foo.py", "x = 10", "x = 99", tracker)
    assert "matches 2 locations" in result
    assert "a = 1" in result
    assert "d = 4" in result


def test_multi_edit_ambiguous_shows_line_numbers(tmp_path):
    from sigil.core.tools import multi_edit

    content = "import os\n\ndef foo():\n    return 1\n\ndef bar():\n    return 1\n"
    (tmp_path / "foo.py").write_text(content)
    tracker = _ChangeTracker()
    tracker.record_read(tmp_path, "foo.py")
    result = multi_edit(
        tmp_path,
        "foo.py",
        [{"old_content": "return 1", "new_content": "return 2"}],
        tracker=tracker,
    )
    assert "matches 2 locations" in result
    assert "lines" in result


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

    with patch(
        "sigil.pipeline.executor._create_worktree", side_effect=OSError("git worktree failed")
    ):
        item, result, branch = await _execute_in_worktree(
            Path("/fake"), config, finding, "dead-code-utils"
        )

    assert item is finding
    assert result.success is False
    assert "Worktree creation failed" in result.failure_reason
    assert branch == ""


async def test_execute_parallel_limits_concurrency():
    config = Config(max_parallel_tasks=1)
    items = [_make_finding(file=f"src/f{i}.py") for i in range(3)]

    peak = [0]
    active = [0]

    async def fake_execute(
        repo, cfg, item, slug, *, instructions=None, mcp_mgr=None, on_status=None
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

    with patch("sigil.pipeline.executor._execute_in_worktree", side_effect=fake_execute):
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
        patch("sigil.pipeline.executor._create_worktree", side_effect=fake_create),
        patch("sigil.pipeline.executor.execute", side_effect=fake_execute),
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
        patch("sigil.pipeline.executor._create_worktree", side_effect=fake_create),
        patch("sigil.pipeline.executor.execute", side_effect=fake_execute),
        patch("sigil.pipeline.executor._commit_changes", side_effect=fake_commit),
        patch("sigil.pipeline.executor._rebase_onto_main", side_effect=fake_rebase),
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
        patch("sigil.pipeline.executor._create_worktree", side_effect=fake_create),
        patch("sigil.pipeline.executor.execute", side_effect=fake_execute),
        patch("sigil.pipeline.executor._commit_changes", side_effect=fake_commit),
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

    progress_call = MagicMock()
    progress_call.id = "call_progress"
    progress_call.function.name = "task_progress"
    progress_call.function.arguments = json.dumps({"summary": "done"})

    msg1 = MagicMock()
    msg1.tool_calls = [read_call]
    msg1.content = None
    choice1 = MagicMock()
    choice1.message = msg1
    resp1 = MagicMock()
    resp1.choices = [choice1]

    msg2 = MagicMock()
    msg2.tool_calls = [progress_call]
    msg2.content = None
    choice2 = MagicMock()
    choice2.message = msg2
    resp2 = MagicMock()
    resp2.choices = [choice2]

    msg3 = MagicMock()
    msg3.tool_calls = [progress_call]
    msg3.content = None
    choice3 = MagicMock()
    choice3.message = msg3
    resp3 = MagicMock()
    resp3.choices = [choice3]

    captured_messages: list[list[dict]] = []
    call_count = {"n": 0}

    async def fake_acompletion(**kwargs):
        captured_messages.append(kwargs.get("messages", []))
        idx = call_count["n"]
        call_count["n"] += 1
        return [resp1, resp2, resp3][idx]

    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)
    monkeypatch.setattr("sigil.core.agent.mask_old_tool_outputs", lambda m, **kw: None)

    from sigil.core.agent import Agent
    from sigil.pipeline.executor import _make_executor_tools

    tracker = _ChangeTracker()
    tools = _make_executor_tools(tmp_path, tracker, None)
    agent = Agent(
        label="test",
        model="test-model",
        tools=tools,
        system_prompt="",
        max_rounds=5,
    )
    messages: list[dict] = [{"role": "user", "content": "implement change"}]
    await agent.run(messages=messages)

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


_MOCK_SUMMARY = (
    "Fixed the security issue in config.py by removing the hardcoded credential. "
    "Updated the load_config function to read from environment variables instead. "
    "Added test_config.py with parametrized tests for valid and invalid configs."
)


def _make_agent_result(summary=_MOCK_SUMMARY, doom_loop=False):
    return AgentResult(
        messages=[{"role": "user", "content": "test"}],
        doom_loop=doom_loop,
        rounds=1,
        stop_result=summary,
        last_content="",
    )


@pytest.fixture()
def _mock_execute_deps(monkeypatch):
    async def fake_select_memory(*a, **kw):
        return {}

    async def fake_agent_run(self, *, messages=None, context=None, on_status=None):
        return _make_agent_result()

    async def fake_rollback(repo, tracker):
        pass

    original_make_tools = executor_mod._make_executor_tools

    def patched_make_tools(repo, tracker, on_status, ignore=None):
        tracker.modified.add("fake_changed.py")
        return original_make_tools(repo, tracker, on_status, ignore=ignore)

    monkeypatch.setattr("sigil.pipeline.executor.select_memory", fake_select_memory)
    monkeypatch.setattr("sigil.core.agent.Agent.run", fake_agent_run)
    monkeypatch.setattr("sigil.pipeline.executor._rollback", fake_rollback)
    monkeypatch.setattr("sigil.pipeline.executor._make_executor_tools", patched_make_tools)


async def test_execute_no_hooks_succeeds(tmp_path, monkeypatch, _mock_execute_deps):
    async def fake_get_diff(repo):
        return "+added line"

    run_command_calls = []

    async def fake_run_command(repo, cmd):
        run_command_calls.append(cmd)
        return True, ""

    monkeypatch.setattr("sigil.pipeline.executor._get_diff", fake_get_diff)
    monkeypatch.setattr("sigil.pipeline.executor._run_command", fake_run_command)

    config = Config(pre_hooks=[], post_hooks=[])
    result, tracker = await execute(tmp_path, config, _make_finding())

    assert result.success is True
    assert result.hooks_passed is True
    assert result.failed_hook is None
    assert result.failure_type is None
    assert result.doom_loop_detected is False
    assert run_command_calls == []


async def test_execute_pre_hook_failure_aborts(tmp_path, monkeypatch, _mock_execute_deps):
    agent_called = []

    async def fake_agent_run(self, *, messages=None, context=None, on_status=None):
        agent_called.append(True)
        return _make_agent_result()

    monkeypatch.setattr("sigil.core.agent.Agent.run", fake_agent_run)

    run_command_calls = []

    async def fake_run_command(repo, cmd):
        run_command_calls.append(cmd)
        if cmd == "mypy .":
            return False, "type errors found"
        return True, ""

    monkeypatch.setattr("sigil.pipeline.executor._run_command", fake_run_command)

    config = Config(pre_hooks=["mypy ."], post_hooks=["ruff format .", "pytest"])
    result, tracker = await execute(tmp_path, config, _make_finding())

    assert result.success is False
    assert result.hooks_passed is False
    assert result.failed_hook == "mypy ."
    assert "Pre-hook failed" in result.failure_reason
    assert result.failure_type == FailureType.PRE_HOOK
    assert agent_called == []
    assert "pytest" not in run_command_calls
    assert "ruff format ." not in run_command_calls


async def test_execute_post_hooks_all_run_on_failure(tmp_path, monkeypatch, _mock_execute_deps):
    async def fake_get_diff(repo):
        return ""

    monkeypatch.setattr("sigil.pipeline.executor._get_diff", fake_get_diff)

    run_command_calls = []

    async def fake_run_command(repo, cmd):
        run_command_calls.append(cmd)
        if cmd == "ruff check .":
            return False, "lint errors"
        return True, ""

    monkeypatch.setattr("sigil.pipeline.executor._run_command", fake_run_command)

    config = Config(
        pre_hooks=[],
        post_hooks=["ruff format .", "ruff check .", "pytest"],
        max_retries=0,
    )
    result, tracker = await execute(tmp_path, config, _make_finding())

    assert result.hooks_passed is True
    assert result.failed_hook is None
    assert result.failure_type == FailureType.NO_CHANGES


async def test_execute_post_hook_failure_reported(tmp_path, monkeypatch, _mock_execute_deps):
    async def fake_run_command(repo, cmd):
        if cmd == "pytest":
            return False, "test failed"
        return True, ""

    async def fake_get_diff(repo):
        return "+fixed"

    monkeypatch.setattr("sigil.pipeline.executor._run_command", fake_run_command)
    monkeypatch.setattr("sigil.pipeline.executor._get_diff", fake_get_diff)

    config = Config(
        pre_hooks=[],
        post_hooks=["ruff format .", "pytest"],
    )
    result, tracker = await execute(tmp_path, config, _make_finding())

    assert result.hooks_passed is False
    assert result.failed_hook == "pytest"
    assert result.failure_type == FailureType.POST_HOOK


async def test_execute_post_hook_exhausts_retries(tmp_path, monkeypatch, _mock_execute_deps):
    rollback_called = []

    async def fake_rollback(repo, tracker):
        rollback_called.append(True)

    monkeypatch.setattr("sigil.pipeline.executor._rollback", fake_rollback)

    async def fake_run_command(repo, cmd):
        if cmd == "pytest":
            return False, "always fails"
        return True, ""

    async def fake_get_diff(repo):
        return "+some changes"

    monkeypatch.setattr("sigil.pipeline.executor._run_command", fake_run_command)
    monkeypatch.setattr("sigil.pipeline.executor._get_diff", fake_get_diff)

    config = Config(
        pre_hooks=[],
        post_hooks=["ruff format .", "pytest"],
        max_retries=2,
    )
    result, tracker = await execute(tmp_path, config, _make_finding())

    assert result.success is False
    assert result.hooks_passed is False
    assert result.failed_hook == "pytest"
    assert "Post-hooks failed" in result.failure_reason
    assert result.failure_type == FailureType.POST_HOOK
    assert rollback_called == [], "should NOT rollback when there is a diff to preserve"


async def test_failure_type_doom_loop_no_diff(tmp_path, monkeypatch, _mock_execute_deps):
    async def fake_agent_run(self, *, messages=None, context=None, on_status=None):
        return _make_agent_result(summary=None, doom_loop=True)

    async def fake_get_diff(repo):
        return ""

    async def fake_rollback(repo, tracker):
        pass

    monkeypatch.setattr("sigil.core.agent.Agent.run", fake_agent_run)
    monkeypatch.setattr("sigil.pipeline.executor._get_diff", fake_get_diff)
    monkeypatch.setattr("sigil.pipeline.executor._rollback", fake_rollback)

    config = Config(pre_hooks=[], post_hooks=[], max_retries=0)
    result, tracker = await execute(tmp_path, config, _make_finding())

    assert result.success is False
    assert result.failure_type == FailureType.DOOM_LOOP
    assert result.doom_loop_detected is True


async def test_failure_type_doom_loop_beats_post_hook(tmp_path, monkeypatch, _mock_execute_deps):
    async def fake_agent_run(self, *, messages=None, context=None, on_status=None):
        return _make_agent_result(summary=None, doom_loop=True)

    async def fake_run_command(repo, cmd):
        return False, "lint error"

    async def fake_get_diff(repo):
        return "+changes"

    monkeypatch.setattr("sigil.core.agent.Agent.run", fake_agent_run)
    monkeypatch.setattr("sigil.pipeline.executor._run_command", fake_run_command)
    monkeypatch.setattr("sigil.pipeline.executor._get_diff", fake_get_diff)

    config = Config(pre_hooks=[], post_hooks=["ruff check ."], max_retries=0)
    result, tracker = await execute(tmp_path, config, _make_finding())

    assert result.success is False
    assert result.failure_type == FailureType.DOOM_LOOP
    assert result.doom_loop_detected is True


async def test_doom_loop_detected_on_success(tmp_path, monkeypatch, _mock_execute_deps):
    async def fake_agent_run(self, *, messages=None, context=None, on_status=None):
        return _make_agent_result(summary="summary", doom_loop=True)

    async def fake_run_command(repo, cmd):
        return True, ""

    async def fake_get_diff(repo):
        return "+changes"

    monkeypatch.setattr("sigil.core.agent.Agent.run", fake_agent_run)
    monkeypatch.setattr("sigil.pipeline.executor._run_command", fake_run_command)
    monkeypatch.setattr("sigil.pipeline.executor._get_diff", fake_get_diff)

    config = Config(pre_hooks=[], post_hooks=["ruff check ."], max_retries=0)
    result, tracker = await execute(tmp_path, config, _make_finding())

    assert result.success is False
    assert result.failure_type == FailureType.DOOM_LOOP
    assert result.doom_loop_detected is True


@pytest.mark.parametrize(
    "item,file_contents,expected_in,expected_empty",
    [
        pytest.param(
            "finding_with_files",
            {"src/utils.py": "def foo(): pass\n", "tests/test_utils.py": "def test_foo(): ...\n"},
            ["src/utils.py", "tests/test_utils.py", "def foo", "def test_foo"],
            False,
            id="finding_with_relevant_files",
        ),
        pytest.param(
            "idea_with_files",
            {"src/api.py": "class API: ...\n"},
            ["src/api.py", "class API"],
            False,
            id="idea_with_relevant_files",
        ),
        pytest.param(
            "idea_no_files",
            {},
            [],
            True,
            id="idea_no_relevant_files_returns_empty",
        ),
    ],
)
def test_preload_reads_relevant_files(tmp_path, item, file_contents, expected_in, expected_empty):
    for rel, content in file_contents.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)

    if item == "finding_with_files":
        work_item = _make_finding(
            file="src/utils.py",
            relevant_files=tuple(file_contents.keys()),
        )
    elif item == "idea_with_files":
        work_item = _make_idea(relevant_files=tuple(file_contents.keys()))
    else:
        work_item = _make_idea()

    result = _preload_relevant_files(tmp_path, work_item)
    if expected_empty:
        assert result == ""
    else:
        assert "## Pre-loaded Files" in result
        for needle in expected_in:
            assert needle in result


def test_preload_includes_finding_file(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/target.py").write_text("x = 1\n")
    item = _make_finding(file="src/target.py", relevant_files=())
    result = _preload_relevant_files(tmp_path, item)
    assert "src/target.py" in result
    assert "x = 1" in result


def test_preload_respects_ignore(tmp_path):
    (tmp_path / "secret.py").write_text("API_KEY = 'xxx'\n")
    (tmp_path / "ok.py").write_text("print('hi')\n")
    item = _make_finding(
        file="ok.py",
        relevant_files=("secret.py", "ok.py"),
    )
    result = _preload_relevant_files(tmp_path, item, ignore=["secret.py"])
    assert "secret.py" not in result
    assert "ok.py" in result


def test_preload_respects_byte_limit(tmp_path, monkeypatch):
    monkeypatch.setattr("sigil.pipeline.executor.MAX_PRELOAD_BYTES", 100)
    lines = "\n".join(f"line_{i} = {i}" for i in range(50))
    (tmp_path / "big.py").write_text(lines)
    item = _make_idea(relevant_files=("big.py",))
    result = _preload_relevant_files(tmp_path, item)
    assert "[truncated" in result
    assert "line_0" in result
    assert "line_49" not in result


def test_preload_blocks_path_traversal(tmp_path):
    evil = tmp_path.parent / "evil.py"
    evil.write_text("import os; os.system('rm -rf /')\n")
    item = _make_finding(
        file="../evil.py",
        relevant_files=("../evil.py",),
    )
    result = _preload_relevant_files(tmp_path, item)
    assert result == ""


def test_prepare_diff_prioritizes_new_files():
    from sigil.pipeline.executor import _prepare_diff_for_review

    tracker = _ChangeTracker()
    tracker.created.add("new_module.py")

    diff = "diff --git a/old.py b/old.py\n" + ("+ old\n" * 50)
    diff += "diff --git a/new_module.py b/new_module.py\n" + ("+ new\n" * 50)

    result = _prepare_diff_for_review(diff, tracker)
    first_diff = next(line for line in result.splitlines() if line.startswith("diff --git"))
    assert "new_module.py" in first_diff


async def test_rebase_onto_main_mixed_conflict(tmp_path):
    import subprocess

    repo = _init_repo(tmp_path)
    (repo / "app.py").write_text("x = 1\n")
    mem_dir = repo / ".sigil" / "memory"
    mem_dir.mkdir(parents=True)
    (mem_dir / "working.md").write_text("base\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)

    worktree_path, branch = await _create_worktree(repo, "rebase-mixed")
    (worktree_path / "app.py").write_text("x = 'branch'\n")
    (worktree_path / ".sigil" / "memory" / "working.md").write_text("branch change\n")
    subprocess.run(["git", "add", "-A"], cwd=worktree_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "branch edit"], cwd=worktree_path, capture_output=True)

    (repo / "app.py").write_text("x = 'main'\n")
    (mem_dir / "working.md").write_text("main change\n")
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
