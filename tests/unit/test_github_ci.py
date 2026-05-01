import logging
from unittest.mock import MagicMock, patch

import pytest
from github import GithubException

from sigil.core.config import Config
from sigil.integrations.github import (
    CIOutcome,
    _get_combined_status_sync,
    _ensure_ci_labels_sync,
    _get_pr_head_sha_sync,
    _add_label_sync,
    _remove_label_sync,
    _post_comment_sync,
    _enable_auto_merge_sync,
    monitor_pr_ci,
    monitor_all_prs,
)


def _mock_client() -> MagicMock:
    client = MagicMock()
    client.repo = MagicMock()
    return client


def test_get_combined_status_sync_pending():
    client = _mock_client()
    mock_status = MagicMock()
    mock_status.state = "pending"
    mock_status.description = "CI running"
    mock_commit = MagicMock()
    mock_commit.get_combined_status.return_value = mock_status
    client.repo.get_commit.return_value = mock_commit

    state, desc = _get_combined_status_sync(client, "abc123")
    assert state == "pending"
    assert desc == "CI running"


def test_get_combined_status_sync_success():
    client = _mock_client()
    mock_status = MagicMock()
    mock_status.state = "success"
    mock_status.description = "All checks passed"
    mock_commit = MagicMock()
    mock_commit.get_combined_status.return_value = mock_status
    client.repo.get_commit.return_value = mock_commit

    state, desc = _get_combined_status_sync(client, "abc123")
    assert state == "success"
    assert desc == "All checks passed"


def test_get_combined_status_sync_failure():
    client = _mock_client()
    mock_status = MagicMock()
    mock_status.state = "failure"
    mock_status.description = "Tests failed"
    mock_commit = MagicMock()
    mock_commit.get_combined_status.return_value = mock_status
    client.repo.get_commit.return_value = mock_commit

    state, desc = _get_combined_status_sync(client, "abc123")
    assert state == "failure"
    assert desc == "Tests failed"


def test_get_combined_status_sync_no_ci_configured():
    client = _mock_client()
    mock_status = MagicMock()
    mock_status.state = "pending"
    mock_status.description = ""
    mock_status.statuses = []
    mock_commit = MagicMock()
    mock_commit.get_combined_status.return_value = mock_status
    client.repo.get_commit.return_value = mock_commit

    state, desc = _get_combined_status_sync(client, "abc123")
    assert state == "success"
    assert desc == "No CI checks configured"


def test_get_combined_status_sync_api_error():
    client = _mock_client()
    client.repo.get_commit.side_effect = GithubException(500, {}, {})

    with pytest.raises(GithubException):
        _get_combined_status_sync(client, "abc123")


def test_ensure_ci_labels_sync():
    client = _mock_client()
    client.repo.get_label.side_effect = GithubException(404, {}, {})

    _ensure_ci_labels_sync(client)

    assert client.repo.create_label.call_count == 3
    names = [call[1]["name"] for call in client.repo.create_label.call_args_list]
    assert "sigil/ci-pending" in names
    assert "sigil/ci-passed" in names
    assert "sigil/ci-failed" in names


def test_ensure_ci_labels_sync_already_exist():
    client = _mock_client()
    client.repo.get_label.return_value = MagicMock()

    _ensure_ci_labels_sync(client)

    client.repo.create_label.assert_not_called()


def test_get_pr_head_sha_sync():
    client = _mock_client()
    mock_pr = MagicMock()
    mock_pr.head.sha = "abc123"
    client.repo.get_pull.return_value = mock_pr

    sha = _get_pr_head_sha_sync(client, 42)
    assert sha == "abc123"
    client.repo.get_pull.assert_called_once_with(42)


def test_add_label_sync():
    client = _mock_client()
    mock_pr = MagicMock()
    client.repo.get_pull.return_value = mock_pr

    _add_label_sync(client, 42, "sigil/ci-passed")
    mock_pr.add_to_labels.assert_called_once_with("sigil/ci-passed")


def test_remove_label_sync():
    client = _mock_client()
    mock_pr = MagicMock()
    client.repo.get_pull.return_value = mock_pr

    _remove_label_sync(client, 42, "sigil/ci-pending")
    mock_pr.remove_from_labels.assert_called_once_with("sigil/ci-pending")


def test_post_comment_sync():
    client = _mock_client()
    mock_pr = MagicMock()
    client.repo.get_pull.return_value = mock_pr

    _post_comment_sync(client, 42, "CI failed")
    mock_pr.create_issue_comment.assert_called_once_with("CI failed")


def test_enable_auto_merge_sync():
    client = _mock_client()
    mock_pr = MagicMock()
    client.repo.get_pull.return_value = mock_pr

    _enable_auto_merge_sync(client, 42)
    mock_pr.enable_automerge.assert_called_once()


def test_enable_auto_merge_sync_graceful_on_error():
    client = _mock_client()
    mock_pr = MagicMock()
    mock_pr.enable_automerge.side_effect = GithubException(422, {}, {})
    client.repo.get_pull.return_value = mock_pr

    _enable_auto_merge_sync(client, 42)
    mock_pr.enable_automerge.assert_called_once()


@pytest.mark.asyncio
async def test_monitor_pr_ci_passes():
    client = _mock_client()
    config = Config(ci_monitor_timeout=600, auto_merge=False)

    with (
        patch("sigil.integrations.github._ensure_ci_labels_sync") as mock_ensure,
        patch("sigil.integrations.github._get_pr_head_sha_sync", return_value="sha1"),
        patch(
            "sigil.integrations.github._get_combined_status_sync",
            return_value=("success", "All good"),
        ),
        patch("sigil.integrations.github._add_label_sync") as mock_add,
        patch("sigil.integrations.github._remove_label_sync") as mock_remove,
        patch("sigil.integrations.github._post_comment_sync") as mock_comment,
        patch("sigil.integrations.github._enable_auto_merge_sync") as mock_merge,
        patch("asyncio.sleep"),
    ):
        outcome = await monitor_pr_ci(client, "https://github.com/owner/repo/pull/42", config)

    assert isinstance(outcome, CIOutcome)
    assert outcome.pr_url == "https://github.com/owner/repo/pull/42"
    assert outcome.status == "passed"
    assert outcome.description == "All good"
    mock_ensure.assert_called_once()
    mock_add.assert_any_call(client, 42, "sigil/ci-pending")
    mock_remove.assert_any_call(client, 42, "sigil/ci-pending")
    mock_add.assert_any_call(client, 42, "sigil/ci-passed")
    mock_comment.assert_not_called()
    mock_merge.assert_not_called()


@pytest.mark.asyncio
async def test_monitor_pr_ci_passes_with_auto_merge():
    client = _mock_client()
    config = Config(ci_monitor_timeout=600, auto_merge=True)

    with (
        patch("sigil.integrations.github._ensure_ci_labels_sync"),
        patch("sigil.integrations.github._get_pr_head_sha_sync", return_value="sha1"),
        patch(
            "sigil.integrations.github._get_combined_status_sync",
            return_value=("success", "All good"),
        ),
        patch("sigil.integrations.github._add_label_sync"),
        patch("sigil.integrations.github._remove_label_sync"),
        patch("sigil.integrations.github._post_comment_sync"),
        patch("sigil.integrations.github._enable_auto_merge_sync") as mock_merge,
        patch("asyncio.sleep"),
    ):
        outcome = await monitor_pr_ci(client, "https://github.com/owner/repo/pull/42", config)

    assert outcome.status == "passed"
    mock_merge.assert_called_once()


@pytest.mark.asyncio
async def test_monitor_pr_ci_fails():
    client = _mock_client()
    config = Config(ci_monitor_timeout=600, auto_merge=False)

    with (
        patch("sigil.integrations.github._ensure_ci_labels_sync"),
        patch("sigil.integrations.github._get_pr_head_sha_sync", return_value="sha1"),
        patch(
            "sigil.integrations.github._get_combined_status_sync",
            return_value=("failure", "Tests failed"),
        ),
        patch("sigil.integrations.github._add_label_sync") as mock_add,
        patch("sigil.integrations.github._remove_label_sync") as mock_remove,
        patch("sigil.integrations.github._post_comment_sync") as mock_comment,
        patch("sigil.integrations.github._enable_auto_merge_sync") as mock_merge,
        patch("asyncio.sleep"),
    ):
        outcome = await monitor_pr_ci(client, "https://github.com/owner/repo/pull/42", config)

    assert outcome.status == "failed"
    assert outcome.description == "Tests failed"
    mock_remove.assert_any_call(client, 42, "sigil/ci-pending")
    mock_add.assert_any_call(client, 42, "sigil/ci-failed")
    mock_comment.assert_called_once()
    call_body = mock_comment.call_args[0][2]
    assert "CI failed on this PR" in call_body
    assert "Tests failed" in call_body
    mock_merge.assert_not_called()


@pytest.mark.asyncio
async def test_monitor_pr_ci_error_state():
    client = _mock_client()
    config = Config(ci_monitor_timeout=600, auto_merge=False)

    with (
        patch("sigil.integrations.github._ensure_ci_labels_sync"),
        patch("sigil.integrations.github._get_pr_head_sha_sync", return_value="sha1"),
        patch(
            "sigil.integrations.github._get_combined_status_sync",
            return_value=("error", "Config error"),
        ),
        patch("sigil.integrations.github._add_label_sync"),
        patch("sigil.integrations.github._remove_label_sync"),
        patch("sigil.integrations.github._post_comment_sync") as mock_comment,
        patch("asyncio.sleep"),
    ):
        outcome = await monitor_pr_ci(client, "https://github.com/owner/repo/pull/42", config)

    assert outcome.status == "failed"
    assert outcome.description == "Config error"
    mock_comment.assert_called_once()


@pytest.mark.asyncio
async def test_monitor_pr_ci_timeout():
    client = _mock_client()
    config = Config(ci_monitor_timeout=1, auto_merge=False)

    with (
        patch("sigil.integrations.github._ensure_ci_labels_sync"),
        patch("sigil.integrations.github._get_pr_head_sha_sync", return_value="sha1"),
        patch(
            "sigil.integrations.github._get_combined_status_sync",
            return_value=("pending", "Still running"),
        ),
        patch("sigil.integrations.github._add_label_sync") as mock_add,
        patch("sigil.integrations.github._remove_label_sync") as mock_remove,
        patch("sigil.integrations.github._post_comment_sync") as mock_comment,
        patch("asyncio.sleep"),
    ):
        outcome = await monitor_pr_ci(client, "https://github.com/owner/repo/pull/42", config)

    assert outcome.status == "timeout"
    assert outcome.description == "CI monitoring timed out"
    mock_add.assert_called_once_with(client, 42, "sigil/ci-pending")
    mock_remove.assert_not_called()
    mock_comment.assert_not_called()


@pytest.mark.asyncio
async def test_monitor_pr_ci_invalid_url(caplog):
    client = _mock_client()
    config = Config(ci_monitor_timeout=600, auto_merge=False)

    with caplog.at_level(logging.WARNING, logger="sigil.github"):
        outcome = await monitor_pr_ci(client, "not-a-url", config)

    assert outcome.status == "timeout"
    assert "Could not parse PR number" in caplog.text


@pytest.mark.asyncio
async def test_monitor_all_prs():
    client = _mock_client()
    config = Config(ci_monitor_timeout=600, auto_merge=False)
    urls = [
        "https://github.com/owner/repo/pull/1",
        "https://github.com/owner/repo/pull/2",
    ]

    call_count = 0

    async def fake_monitor(c, url, cfg):
        nonlocal call_count
        call_count += 1
        return CIOutcome(pr_url=url, status="passed", description="OK")

    with patch("sigil.integrations.github.monitor_pr_ci", side_effect=fake_monitor):
        outcomes = await monitor_all_prs(client, urls, config)

    assert len(outcomes) == 2
    assert outcomes[0].status == "passed"
    assert outcomes[1].status == "passed"
    assert call_count == 2


@pytest.mark.asyncio
async def test_monitor_all_prs_empty():
    client = _mock_client()
    config = Config(ci_monitor_timeout=600, auto_merge=False)

    outcomes = await monitor_all_prs(client, [], config)
    assert outcomes == []
