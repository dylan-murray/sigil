import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from sigil.integrations.github import publish_results, GitHubClient
from sigil.pipeline.models import ExecutionResult
from sigil.pipeline.maintenance import Finding
from sigil.core.config import Config


@pytest.fixture
def mock_config():
    config = MagicMock(spec=Config)
    config.max_prs_per_run = 5
    config.max_github_issues = 5
    config.model_for.return_value = "gpt-4"
    return config


@pytest.fixture
def mock_item():
    return Finding(
        priority="medium",
        category="types",
        file="sigil/core.py",
        line=10,
        risk="low",
        description="Missing type hint",
        suggested_fix="Add str hint",
        disposition="pr",
        rationale="Improves type safety",
    )


@pytest.fixture
def mock_result():
    return ExecutionResult(
        success=True,
        retries=0,
        diff="diff --git a/sigil/core.py b/sigil/core.py\n+x: str = 'hi'",
        summary="Added type hint",
        hooks_passed=True,
        failed_hook=None,
        downgraded=False,
        downgrade_context=None,
    )


@pytest.mark.asyncio
async def test_publish_results_dry_run(mock_config, mock_item, mock_result):
    # Setup
    repo = Path(".")
    execution_results = [(mock_item, mock_result, "sigil/feat-1")]
    issue_items = [(mock_item, None)]

    # We use client=None to simulate dry run
    with patch(
        "sigil.integrations.github.generate_pr_summary",
        AsyncMock(return_value=("sigil: Fix types", "Fixed type hints")),
    ):
        pr_urls, issue_urls, pushed_branches = await publish_results(
            repo=repo,
            config=mock_config,
            client=None,
            execution_results=execution_results,
            issue_items=issue_items,
        )

    assert pr_urls == []
    assert issue_urls == []
    assert "sigil/feat-1" in pushed_branches


@pytest.mark.asyncio
async def test_publish_results_live_run(mock_config, mock_item, mock_result):
    # Setup
    repo = Path(".")
    execution_results = [(mock_item, mock_result, "sigil/feat-1")]
    issue_items = [(mock_item, None)]

    mock_client = MagicMock(spec=GitHubClient)

    with (
        patch(
            "sigil.integrations.github.open_pr", AsyncMock(return_value="http://github.com/pr/1")
        ),
        patch(
            "sigil.integrations.github.open_issue",
            AsyncMock(return_value="http://github.com/issue/1"),
        ),
    ):
        pr_urls, issue_urls, pushed_branches = await publish_results(
            repo=repo,
            config=mock_config,
            client=mock_client,
            execution_results=execution_results,
            issue_items=issue_items,
        )

    assert pr_urls == ["http://github.com/pr/1"]
    assert issue_urls == ["http://github.com/issue/1"]
    assert "sigil/feat-1" in pushed_branches
