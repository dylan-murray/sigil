import pytest
from unittest.mock import MagicMock, patch

from sigil.core.security import contains_unsafe_code
from sigil.pipeline.executor import _finalize_worktree
from sigil.pipeline.models import ExecutionResult, FailureType
from sigil.state.chronic import WorkItem
from sigil.core.config import Config


def test_contains_unsafe_code_happy_path():
    assert not contains_unsafe_code("def hello():\n    print('hello')")
    assert not contains_unsafe_code("x = 1 + 1")
    assert not contains_unsafe_code("my_eval = 10")
    assert not contains_unsafe_code("exec_count = 0")


def test_contains_unsafe_code_eval_violation():
    assert contains_unsafe_code("eval('1 + 1')")


def test_contains_unsafe_code_exec_violation():
    assert contains_unsafe_code("exec('print(1)')")


def test_contains_unsafe_code_false_positives():
    assert not contains_unsafe_code("eval_something()")
    assert not contains_unsafe_code("execute_task()")
    assert not contains_unsafe_code("my_eval = 1")


@pytest.mark.asyncio
async def test_finalize_worktree_security_violation(tmp_path):
    # Setup
    repo = tmp_path / "repo"
    repo.mkdir()
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    config = Config()
    item = MagicMock(spec=WorkItem)
    slug = "test-slug"
    branch = "test-branch"

    # Create a python file with unsafe code in the worktree
    unsafe_file = "unsafe.py"
    (worktree / unsafe_file).write_text("eval('1+1')")

    # Mock execute to return success and the unsafe file in tracker
    mock_result = ExecutionResult(
        success=True,
        diff="some diff",
        hooks_passed=True,
        failed_hook=None,
        retries=0,
        failure_reason=None,
        failure_type=None,
        doom_loop_detected=False,
        summary="Success",
        downgraded=False,
        downgrade_context=None,
    )

    mock_tracker = MagicMock()
    mock_tracker.modified = {unsafe_file}
    mock_tracker.created = set()

    with (
        patch("sigil.pipeline.executor.execute", return_value=(mock_result, mock_tracker)),
        patch("sigil.pipeline.executor._describe_item", return_value="Test Item"),
    ):
        result_item, result_exec, result_branch = await _finalize_worktree(
            repo, worktree, config, item, slug, branch
        )

        assert result_exec.success is False
        assert result_exec.failure_type == FailureType.SECURITY_VIOLATION
        assert "Security violation" in result_exec.failure_reason
        assert result_exec.downgraded is False


@pytest.mark.asyncio
async def test_finalize_worktree_security_happy_path(tmp_path):
    # Setup
    repo = tmp_path / "repo"
    repo.mkdir()
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    config = Config()
    item = MagicMock(spec=WorkItem)
    slug = "test-slug"
    branch = "test-branch"

    # Create a safe python file
    safe_file = "safe.py"
    (worktree / safe_file).write_text("print('hello')")

    mock_result = ExecutionResult(
        success=True,
        diff="some diff",
        hooks_passed=True,
        failed_hook=None,
        retries=0,
        failure_reason=None,
        failure_type=None,
        doom_loop_detected=False,
        summary="Success",
        downgraded=False,
        downgrade_context=None,
    )

    mock_tracker = MagicMock()
    mock_tracker.modified = {safe_file}
    mock_tracker.created = set()

    with (
        patch("sigil.pipeline.executor.execute", return_value=(mock_result, mock_tracker)),
        patch("sigil.pipeline.executor._commit_changes", return_value=(True, "")),
        patch("sigil.pipeline.executor._rebase_onto_main", return_value=(True, "")),
        patch("sigil.pipeline.executor._describe_item", return_value="Test Item"),
    ):
        result_item, result_exec, result_branch = await _finalize_worktree(
            repo, worktree, config, item, slug, branch
        )

        assert result_exec.success is True
