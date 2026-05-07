import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.table import Table

from sigil.cli import _run_pipeline
from sigil.core.config import Config
from sigil.pipeline.ideation import FeatureIdea
from sigil.pipeline.maintenance import Finding
from sigil.pipeline.models import ValidationResult


def _empty_mcp():
    m = MagicMock()
    m.server_count = 0
    m.tool_count = 0
    return m


@pytest.fixture()
def tmp_path(tmp_path_factory):
    return tmp_path_factory.mktemp("repo")


@pytest.mark.asyncio
async def test_dry_run_summary_output(tmp_path):
    pr_finding = Finding(
        category="refactor",
        file="a.py",
        line=1,
        description="Refactor X",
        risk="low",
        suggested_fix="fix",
        disposition="pr",
        priority=1,
        rationale="rationale",
    )
    issue_finding = Finding(
        category="security",
        file="b.py",
        line=2,
        description="Security vulnerability in Y",
        risk="high",
        suggested_fix="fix",
        disposition="issue",
        priority=2,
        rationale="rationale",
    )
    skip_finding = Finding(
        category="style",
        file="c.py",
        line=3,
        description="Skip me",
        risk="low",
        suggested_fix="fix",
        disposition="skip",
        priority=3,
        rationale="rationale",
    )
    pr_idea = FeatureIdea(
        title="Add feature Z",
        description="desc",
        rationale="rationale",
        complexity="small",
        boldness="balanced",
        priority=1,
        disposition="pr",
    )
    issue_idea = FeatureIdea(
        title="Idea for issue",
        description="desc",
        rationale="rationale",
        complexity="medium",
        boldness="balanced",
        priority=2,
        disposition="issue",
    )
    validation_result = ValidationResult(
        findings=[pr_finding, issue_finding, skip_finding],
        ideas=[pr_idea, issue_idea],
    )

    printed: list[object] = []

    def capture_print(*args, **kwargs):
        printed.extend(args)

    with (
        patch("sigil.cli.create_client", new_callable=AsyncMock) as mock_gh,
        patch("sigil.cli.is_knowledge_stale", new_callable=AsyncMock, return_value=False),
        patch(
            "sigil.cli.analyze",
            new_callable=AsyncMock,
            return_value=[pr_finding, issue_finding, skip_finding],
        ),
        patch("sigil.cli.ideate", new_callable=AsyncMock, return_value=[pr_idea, issue_idea]),
        patch("sigil.cli.validate_all", new_callable=AsyncMock, return_value=validation_result),
        patch("sigil.cli.execute_parallel", new_callable=AsyncMock) as mock_exec,
        patch("sigil.cli.publish_results", new_callable=AsyncMock) as mock_publish,
        patch("sigil.cli.load_index", return_value=None),
        patch("sigil.cli.detect_instructions", return_value=MagicMock(has_instructions=False)),
        patch("sigil.cli.console") as mock_console,
    ):
        mock_console.print = capture_print
        await _run_pipeline(tmp_path, Config(), dry_run=True, mcp_mgr=_empty_mcp())

    mock_gh.assert_not_called()
    mock_exec.assert_not_called()
    mock_publish.assert_not_called()

    tables = [p for p in printed if isinstance(p, Table)]
    assert len(tables) == 1
    table = tables[0]
    rows = [tuple(str(cell) for cell in row) for row in table.rows]
    assert ("Would create PR", "Finding", "Refactor X") in rows
    assert ("Would create PR", "Idea", "Add feature Z") in rows
    assert ("Would file issue", "Finding", "Security vulnerability in Y") in rows
    assert ("Would file issue", "Idea", "Idea for issue") in rows
    assert ("Would skip", "Finding", "Skip me") in rows

    notes = [str(p) for p in printed if isinstance(p, str) and "Note:" in p]
    assert any("deduplication and chronic failure filtering" in n for n in notes)


@pytest.mark.asyncio
async def test_dry_run_with_no_candidates(tmp_path):
    validation_result = ValidationResult(findings=[], ideas=[])

    printed: list[object] = []

    def capture_print(*args, **kwargs):
        printed.extend(args)

    with (
        patch("sigil.cli.create_client", new_callable=AsyncMock) as mock_gh,
        patch("sigil.cli.is_knowledge_stale", new_callable=AsyncMock, return_value=False),
        patch("sigil.cli.analyze", new_callable=AsyncMock, return_value=[]),
        patch("sigil.cli.ideate", new_callable=AsyncMock, return_value=[]),
        patch("sigil.cli.validate_all", new_callable=AsyncMock, return_value=validation_result),
        patch("sigil.cli.execute_parallel", new_callable=AsyncMock) as mock_exec,
        patch("sigil.cli.publish_results", new_callable=AsyncMock) as mock_publish,
        patch("sigil.cli.load_index", return_value=None),
        patch("sigil.cli.detect_instructions", return_value=MagicMock(has_instructions=False)),
        patch("sigil.cli.console") as mock_console,
    ):
        mock_console.print = capture_print
        await _run_pipeline(tmp_path, Config(), dry_run=True, mcp_mgr=_empty_mcp())

    mock_gh.assert_not_called()
    mock_exec.assert_not_called()
    mock_publish.assert_not_called()

    tables = [p for p in printed if isinstance(p, Table)]
    assert len(tables) == 0

    notes = [str(p) for p in printed if isinstance(p, str) and "Note:" in p]
    assert any("deduplication and chronic failure filtering" in n for n in notes)
