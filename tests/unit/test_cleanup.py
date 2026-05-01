import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sigil.core.config import Config
from sigil.integrations.github import GitHubClient
from sigil.pipeline.cleanup import (
    cleanup_stale_resources,
    _cleanup_temp_files,
    _find_stale_branches,
    _find_stale_worktrees,
    _remove_branch,
    _remove_worktree,
)


@pytest.fixture
def _mock_client() -> GitHubClient:
    repo = MagicMock()
    gh = MagicMock()
    return GitHubClient(gh=gh, repo=repo)


async def test_find_stale_worktrees_orphaned(tmp_path: Path) -> None:
    worktree_path = str(tmp_path / ".sigil" / "worktrees" / "dead-code-utils")
    porcelain = (
        f"worktree {worktree_path}\n"
        "HEAD abc123\n"
        "branch refs/heads/sigil/auto/dead-code-utils-1234567890\n"
        "\n"
    )
    with patch("sigil.pipeline.cleanup.arun", return_value=(0, porcelain, "")):
        result = await _find_stale_worktrees(tmp_path)
    assert len(result) == 1
    assert result[0][0] == worktree_path
    assert result[0][1] == "sigil/auto/dead-code-utils-1234567890"


async def test_find_stale_worktrees_none(tmp_path: Path) -> None:
    porcelain = "worktree /repo\nHEAD abc123\nbranch refs/heads/main\n\n"
    with patch("sigil.pipeline.cleanup.arun", return_value=(0, porcelain, "")):
        result = await _find_stale_worktrees(tmp_path)
    assert result == []


async def test_find_stale_worktrees_missing_directory(tmp_path: Path) -> None:
    worktree_path = str(tmp_path / ".sigil" / "worktrees" / "old-item")
    porcelain = (
        f"worktree {worktree_path}\n"
        "HEAD abc123\n"
        "branch refs/heads/sigil/auto/old-item-1234567890\n"
        "\n"
    )
    with patch("sigil.pipeline.cleanup.arun", return_value=(0, porcelain, "")):
        result = await _find_stale_worktrees(tmp_path)
    assert len(result) == 1
    assert result[0][0] == worktree_path


async def test_remove_worktree_success(tmp_path: Path) -> None:
    with patch("sigil.pipeline.cleanup.arun", return_value=(0, "", "")):
        ok = await _remove_worktree(tmp_path, str(tmp_path / ".sigil" / "worktrees" / "foo"))
    assert ok is True


async def test_remove_worktree_failure(tmp_path: Path) -> None:
    with patch("sigil.pipeline.cleanup.arun", return_value=(1, "", "error")):
        ok = await _remove_worktree(tmp_path, str(tmp_path / ".sigil" / "worktrees" / "foo"))
    assert ok is False


async def test_find_stale_branches_with_gh_client(
    tmp_path: Path, _mock_client: GitHubClient
) -> None:
    branch_list = "  sigil/auto/foo-1234567890\n  sigil/auto/bar-1234567890\n"
    mock_pr = MagicMock()
    mock_pr.head.ref = "sigil/auto/foo-1234567890"
    mock_label = MagicMock()
    mock_label.name = "sigil"
    mock_pr.labels = [mock_label]
    _mock_client.repo.get_pulls.return_value = [mock_pr]
    with patch("sigil.pipeline.cleanup.arun", return_value=(0, branch_list, "")):
        result = await _find_stale_branches(tmp_path, _mock_client)
    assert result == ["sigil/auto/bar-1234567890"]


async def test_find_stale_branches_no_client(tmp_path: Path) -> None:
    result = await _find_stale_branches(tmp_path, None)
    assert result == []


async def test_find_stale_branches_empty(tmp_path: Path, _mock_client: GitHubClient) -> None:
    with patch("sigil.pipeline.cleanup.arun", return_value=(0, "", "")):
        result = await _find_stale_branches(tmp_path, _mock_client)
    assert result == []


async def test_find_stale_branches_all_have_prs(tmp_path: Path, _mock_client: GitHubClient) -> None:
    branch_list = "  sigil/auto/foo-1234567890\n"
    mock_pr = MagicMock()
    mock_pr.head.ref = "sigil/auto/foo-1234567890"
    mock_label = MagicMock()
    mock_label.name = "sigil"
    mock_pr.labels = [mock_label]
    _mock_client.repo.get_pulls.return_value = [mock_pr]
    with patch("sigil.pipeline.cleanup.arun", return_value=(0, branch_list, "")):
        result = await _find_stale_branches(tmp_path, _mock_client)
    assert result == []


async def test_find_stale_branches_gh_error(tmp_path: Path, _mock_client: GitHubClient) -> None:
    from github import GithubException

    branch_list = "  sigil/auto/foo-1234567890\n"
    _mock_client.repo.get_pulls.side_effect = GithubException(500, {}, {})
    with patch("sigil.pipeline.cleanup.arun", return_value=(0, branch_list, "")):
        result = await _find_stale_branches(tmp_path, _mock_client)
    assert result == []


async def test_remove_branch_success(tmp_path: Path) -> None:
    with patch("sigil.pipeline.cleanup.arun", return_value=(0, "", "")):
        ok = await _remove_branch(tmp_path, "sigil/auto/foo-1234567890")
    assert ok is True


async def test_remove_branch_failure(tmp_path: Path) -> None:
    with patch("sigil.pipeline.cleanup.arun", return_value=(1, "", "error")):
        ok = await _remove_branch(tmp_path, "sigil/auto/foo-1234567890")
    assert ok is False


async def test_cleanup_temp_files(tmp_path: Path) -> None:
    sigil_dir = tmp_path / ".sigil"
    sigil_dir.mkdir(parents=True, exist_ok=True)
    temp_file = sigil_dir / "temp_foo.txt"
    temp_file.write_text("hello")
    temp_dir = sigil_dir / "temp_bar"
    temp_dir.mkdir(parents=True, exist_ok=True)
    (temp_dir / "file.txt").write_text("world")

    result = _cleanup_temp_files(tmp_path)

    assert len(result) == 2
    assert not temp_file.exists()
    assert not temp_dir.exists()


async def test_cleanup_temp_files_none(tmp_path: Path) -> None:
    sigil_dir = tmp_path / ".sigil"
    sigil_dir.mkdir(parents=True, exist_ok=True)
    result = _cleanup_temp_files(tmp_path)
    assert result == []


async def test_cleanup_stale_resources_integration(tmp_path: Path) -> None:
    with (
        patch(
            "sigil.pipeline.cleanup._find_stale_worktrees",
            return_value=[(str(tmp_path / ".sigil" / "worktrees" / "a"), "sigil/auto/a-1")],
        ),
        patch("sigil.pipeline.cleanup._remove_worktree", return_value=True),
        patch(
            "sigil.pipeline.cleanup._find_stale_branches",
            return_value=["sigil/auto/b-1"],
        ),
        patch("sigil.pipeline.cleanup._remove_branch", return_value=True),
        patch(
            "sigil.pipeline.cleanup._cleanup_temp_files",
            return_value=[str(tmp_path / ".sigil" / "temp_test")],
        ),
    ):
        result = await cleanup_stale_resources(tmp_path, Config(), None)

    assert len(result) == 3
    assert any("worktree" in r for r in result)
    assert any("branch" in r for r in result)
    assert any("temp" in r for r in result)


async def test_cleanup_stale_resources_no_error_on_failure(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with (
        patch(
            "sigil.pipeline.cleanup._find_stale_worktrees",
            side_effect=RuntimeError("boom"),
        ),
        patch("sigil.pipeline.cleanup._find_stale_branches", return_value=[]),
        patch("sigil.pipeline.cleanup._cleanup_temp_files", return_value=[]),
        caplog.at_level(logging.WARNING, logger="sigil.pipeline.cleanup"),
    ):
        result = await cleanup_stale_resources(tmp_path, Config(), None)

    assert result == []
    assert "Failed to find stale worktrees" in caplog.text


async def test_cleanup_stale_resources_no_client_skips_branches(tmp_path: Path) -> None:
    with (
        patch("sigil.pipeline.cleanup._find_stale_worktrees", return_value=[]),
        patch("sigil.pipeline.cleanup._find_stale_branches") as mock_branches,
        patch("sigil.pipeline.cleanup._cleanup_temp_files", return_value=[]),
    ):
        await cleanup_stale_resources(tmp_path, Config(), None)

    mock_branches.assert_called_once_with(tmp_path, None)


async def test_cleanup_stale_resources_partial_failure(tmp_path: Path) -> None:
    with (
        patch(
            "sigil.pipeline.cleanup._find_stale_worktrees",
            return_value=[
                (str(tmp_path / ".sigil" / "worktrees" / "a"), "sigil/auto/a-1"),
                (str(tmp_path / ".sigil" / "worktrees" / "b"), "sigil/auto/b-1"),
            ],
        ),
        patch("sigil.pipeline.cleanup._remove_worktree", side_effect=[True, False]),
        patch("sigil.pipeline.cleanup._find_stale_branches", return_value=[]),
        patch("sigil.pipeline.cleanup._cleanup_temp_files", return_value=[]),
    ):
        result = await cleanup_stale_resources(tmp_path, Config(), None)

    assert len(result) == 2
    assert any("a" in r for r in result)
    assert any("b" in r for r in result)
