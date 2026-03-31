import subprocess
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import typer
import yaml

from sigil.cli import _run, _run_pipeline, init, status
from sigil.core.config import SIGIL_DIR, CONFIG_FILE, Config
from sigil.pipeline.models import ExecutionResult
from sigil.integrations.github import DedupResult
from sigil.pipeline.ideation import FeatureIdea
from sigil.pipeline.maintenance import Finding
from sigil.core.mcp import MCPManager
from sigil.pipeline.validation import ValidationResult


@asynccontextmanager
async def _noop_mcp_ctx(config):
    yield MCPManager()


def _empty_mcp() -> MCPManager:
    return MCPManager()


def test_init_creates_config(tmp_path):
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True)
    config_path = tmp_path / SIGIL_DIR / CONFIG_FILE
    assert not config_path.exists()

    with patch("sigil.cli.console"):
        init(repo=tmp_path)

    assert config_path.exists()
    parsed = yaml.safe_load(config_path.read_text())
    assert parsed["model"] == Config().model
    assert parsed["boldness"] == "bold"


def test_init_rejects_non_git_directory(tmp_path):
    from click.exceptions import Exit

    with patch("sigil.cli.console"), pytest.raises(Exit):
        init(repo=tmp_path)


def test_init_exits_if_already_initialized(tmp_path):
    from click.exceptions import Exit

    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True)
    (tmp_path / SIGIL_DIR).mkdir(parents=True)
    (tmp_path / SIGIL_DIR / CONFIG_FILE).write_text(Config().to_yaml())

    with patch("sigil.cli.console"), pytest.raises(Exit):
        init(repo=tmp_path)


async def test_run_exits_without_init(tmp_path):
    from click.exceptions import Exit

    with patch("sigil.cli.console"), pytest.raises(Exit):
        await _run(tmp_path, dry_run=True, trace=False)


async def test_dry_run_with_findings_skips_execution(tmp_path):
    (tmp_path / SIGIL_DIR).mkdir(parents=True)
    (tmp_path / SIGIL_DIR / CONFIG_FILE).write_text(Config().to_yaml())

    finding = Finding(
        category="dead_code",
        file="foo.py",
        line=1,
        description="unused",
        risk="low",
        suggested_fix="remove",
        disposition="pr",
        priority=1,
        rationale="test",
    )
    validation_result = ValidationResult(findings=[finding], ideas=[])

    with (
        patch("sigil.cli.create_client", new_callable=AsyncMock) as mock_gh,
        patch("sigil.cli.is_knowledge_stale", new_callable=AsyncMock, return_value=False),
        patch("sigil.cli.analyze", new_callable=AsyncMock, return_value=[finding]),
        patch("sigil.cli.ideate", new_callable=AsyncMock, return_value=[]),
        patch("sigil.cli.validate_all", new_callable=AsyncMock, return_value=validation_result),
        patch("sigil.cli.execute_parallel", new_callable=AsyncMock) as mock_exec,
        patch("sigil.cli.publish_results", new_callable=AsyncMock) as mock_publish,
        patch("sigil.cli.load_index", return_value=None),
        patch("sigil.cli.detect_instructions", return_value=MagicMock(has_instructions=False)),
        patch("sigil.cli.console"),
    ):
        await _run_pipeline(tmp_path, Config(), dry_run=True, mcp_mgr=_empty_mcp())

    mock_gh.assert_not_called()
    mock_exec.assert_not_called()
    mock_publish.assert_not_called()


async def test_missing_github_token_exits(tmp_path):
    (tmp_path / SIGIL_DIR).mkdir(parents=True)
    (tmp_path / SIGIL_DIR / CONFIG_FILE).write_text(Config().to_yaml())

    with (
        patch("sigil.cli.create_client", new_callable=AsyncMock, return_value=None),
        patch("sigil.cli.console"),
        pytest.raises(typer.Exit) as exc_info,
    ):
        await _run_pipeline(tmp_path, Config(), dry_run=False, mcp_mgr=_empty_mcp())

    assert exc_info.value.exit_code == 1


async def test_no_findings_early_return(tmp_path):
    (tmp_path / SIGIL_DIR).mkdir(parents=True)
    (tmp_path / SIGIL_DIR / CONFIG_FILE).write_text(Config().to_yaml())

    with (
        patch("sigil.cli.create_client", new_callable=AsyncMock, return_value=MagicMock()),
        patch("sigil.cli.ensure_labels", new_callable=AsyncMock),
        patch("sigil.cli.fetch_existing_issues", new_callable=AsyncMock, return_value=[]),
        patch("sigil.cli.is_knowledge_stale", new_callable=AsyncMock, return_value=False),
        patch("sigil.cli.analyze", new_callable=AsyncMock, return_value=[]),
        patch("sigil.cli.ideate", new_callable=AsyncMock, return_value=[]),
        patch("sigil.cli.validate_all", new_callable=AsyncMock) as mock_validate,
        patch("sigil.cli.execute_parallel", new_callable=AsyncMock) as mock_exec,
        patch("sigil.cli.publish_results", new_callable=AsyncMock) as mock_publish,
        patch("sigil.cli.load_index", return_value=None),
        patch("sigil.cli.detect_instructions", return_value=MagicMock(has_instructions=False)),
        patch("sigil.cli.console"),
    ):
        await _run_pipeline(tmp_path, Config(), dry_run=False, mcp_mgr=_empty_mcp())

    mock_validate.assert_not_called()
    mock_exec.assert_not_called()
    mock_publish.assert_not_called()


async def test_pr_cap_overflow_moves_to_issues(tmp_path):
    (tmp_path / SIGIL_DIR).mkdir(parents=True)
    (tmp_path / SIGIL_DIR / CONFIG_FILE).write_text(Config().to_yaml())

    findings = [
        Finding(
            category="dead_code",
            file=f"file{i}.py",
            line=1,
            description=f"finding {i}",
            risk="low",
            suggested_fix="fix",
            disposition="pr",
            priority=i,
            rationale="test",
        )
        for i in range(5)
    ]
    issue_finding = Finding(
        category="docs",
        file="README.md",
        line=None,
        description="bad docs",
        risk="low",
        suggested_fix="fix",
        disposition="issue",
        priority=10,
        rationale="test",
    )

    validation_result = ValidationResult(findings=findings + [issue_finding], ideas=[])

    config = Config(max_prs_per_run=2)

    published_issue_tuples = []

    async def capture_publish(resolved, cfg, gh, parallel_results, issue_tuples, **kw):
        published_issue_tuples.extend(issue_tuples)
        return [], [], []

    exec_results = [
        (
            f,
            ExecutionResult(
                success=True,
                diff="+x",
                hooks_passed=True,
                failed_hook=None,
                retries=0,
                failure_reason=None,
            ),
            f"branch-{i}",
        )
        for i, f in enumerate(findings[:2])
    ]

    with (
        patch("sigil.cli.create_client", new_callable=AsyncMock, return_value=MagicMock()),
        patch("sigil.cli.ensure_labels", new_callable=AsyncMock),
        patch("sigil.cli.fetch_existing_issues", new_callable=AsyncMock, return_value=[]),
        patch("sigil.cli.is_knowledge_stale", new_callable=AsyncMock, return_value=False),
        patch("sigil.cli.analyze", new_callable=AsyncMock, return_value=findings + [issue_finding]),
        patch("sigil.cli.ideate", new_callable=AsyncMock, return_value=[]),
        patch("sigil.cli.validate_all", new_callable=AsyncMock, return_value=validation_result),
        patch(
            "sigil.cli.dedup_items",
            new_callable=AsyncMock,
            side_effect=lambda gh, items: DedupResult(skipped=[], remaining=list(items)),
        ),
        patch("sigil.cli.execute_parallel", new_callable=AsyncMock, return_value=exec_results),
        patch("sigil.cli.publish_results", new_callable=AsyncMock, side_effect=capture_publish),
        patch("sigil.cli.cleanup_after_push", new_callable=AsyncMock),
        patch("sigil.cli.load_index", return_value=None),
        patch("sigil.cli.detect_instructions", return_value=MagicMock(has_instructions=False)),
        patch("sigil.cli.console"),
    ):
        await _run_pipeline(tmp_path, config, dry_run=False, mcp_mgr=_empty_mcp())

    issue_items_published = [item for item, ctx in published_issue_tuples]
    assert issue_finding in issue_items_published
    overflow_in_issues = [f for f in findings[2:] if f in issue_items_published]
    assert len(overflow_in_issues) == 3


async def test_stale_knowledge_uses_per_agent_model(tmp_path):
    (tmp_path / SIGIL_DIR).mkdir(parents=True)
    (tmp_path / SIGIL_DIR / CONFIG_FILE).write_text(Config().to_yaml())

    captured_compact_model = {}

    async def capture_compact(repo, model, context, **kw):
        captured_compact_model["model"] = model

    with (
        patch("sigil.cli.create_client", new_callable=AsyncMock, return_value=MagicMock()),
        patch("sigil.cli.ensure_labels", new_callable=AsyncMock),
        patch("sigil.cli.fetch_existing_issues", new_callable=AsyncMock, return_value=[]),
        patch("sigil.cli.is_knowledge_stale", new_callable=AsyncMock, return_value=True),
        patch("sigil.cli.discover", new_callable=AsyncMock, return_value="discovery context"),
        patch("sigil.cli.compact_knowledge", new_callable=AsyncMock, side_effect=capture_compact),
        patch("sigil.cli.analyze", new_callable=AsyncMock, return_value=[]),
        patch("sigil.cli.ideate", new_callable=AsyncMock, return_value=[]),
        patch("sigil.cli.load_index", return_value=None),
        patch("sigil.cli.detect_instructions", return_value=MagicMock(has_instructions=False)),
        patch("sigil.cli.console"),
    ):
        config = Config(agents={"compactor": {"model": "openai/gpt-4o-mini"}})
        await _run_pipeline(tmp_path, config, dry_run=False, mcp_mgr=_empty_mcp())

    assert captured_compact_model["model"] == "openai/gpt-4o-mini"


async def test_downgraded_item_gets_context_in_issue(tmp_path):
    (tmp_path / SIGIL_DIR).mkdir(parents=True)
    (tmp_path / SIGIL_DIR / CONFIG_FILE).write_text(Config().to_yaml())

    pr_finding = Finding(
        category="dead_code",
        file="foo.py",
        line=1,
        description="unused import",
        risk="low",
        suggested_fix="remove",
        disposition="pr",
        priority=1,
        rationale="test",
    )
    issue_finding = Finding(
        category="docs",
        file="README.md",
        line=None,
        description="bad link",
        risk="low",
        suggested_fix="fix",
        disposition="issue",
        priority=2,
        rationale="test",
    )

    validation_result = ValidationResult(findings=[pr_finding, issue_finding], ideas=[])

    downgrade_ctx = "Execution failed after 3 retries.\nReason: Tests failed\nTask: unused import"
    failed_result = ExecutionResult(
        success=False,
        diff="",
        hooks_passed=False,
        failed_hook="pytest",
        retries=3,
        failure_reason="Tests failed",
        downgraded=True,
        downgrade_context=downgrade_ctx,
    )
    exec_results = [(pr_finding, failed_result, "sigil/fix-unused-import")]

    published_issue_tuples = []

    async def capture_publish(resolved, cfg, gh, parallel_results, issue_tuples, **kw):
        published_issue_tuples.extend(issue_tuples)
        return [], [], []

    with (
        patch("sigil.cli.create_client", new_callable=AsyncMock, return_value=MagicMock()),
        patch("sigil.cli.ensure_labels", new_callable=AsyncMock),
        patch("sigil.cli.fetch_existing_issues", new_callable=AsyncMock, return_value=[]),
        patch("sigil.cli.is_knowledge_stale", new_callable=AsyncMock, return_value=False),
        patch(
            "sigil.cli.analyze", new_callable=AsyncMock, return_value=[pr_finding, issue_finding]
        ),
        patch("sigil.cli.ideate", new_callable=AsyncMock, return_value=[]),
        patch("sigil.cli.validate_all", new_callable=AsyncMock, return_value=validation_result),
        patch(
            "sigil.cli.dedup_items",
            new_callable=AsyncMock,
            side_effect=lambda gh, items: DedupResult(skipped=[], remaining=list(items)),
        ),
        patch("sigil.cli.execute_parallel", new_callable=AsyncMock, return_value=exec_results),
        patch("sigil.cli.publish_results", new_callable=AsyncMock, side_effect=capture_publish),
        patch("sigil.cli.cleanup_after_push", new_callable=AsyncMock),
        patch("sigil.cli.load_index", return_value=None),
        patch("sigil.cli.detect_instructions", return_value=MagicMock(has_instructions=False)),
        patch("sigil.cli.console"),
    ):
        await _run_pipeline(
            tmp_path, Config(max_prs_per_run=5), dry_run=False, mcp_mgr=_empty_mcp()
        )

    tuples_by_item = {id(item): ctx for item, ctx in published_issue_tuples}
    assert id(pr_finding) in tuples_by_item, "downgraded PR finding should appear in issue tuples"
    assert tuples_by_item[id(pr_finding)] == downgrade_ctx
    assert id(issue_finding) in tuples_by_item, (
        "original issue finding should appear in issue tuples"
    )
    assert tuples_by_item[id(issue_finding)] is None


async def test_downgraded_idea_gets_context_in_issue(tmp_path):
    (tmp_path / SIGIL_DIR).mkdir(parents=True)
    (tmp_path / SIGIL_DIR / CONFIG_FILE).write_text(Config().to_yaml())

    idea = FeatureIdea(
        title="Add caching layer",
        description="Cache LLM responses to reduce costs",
        rationale="Save money",
        complexity="medium",
        disposition="pr",
        priority=1,
    )

    validation_result = ValidationResult(findings=[], ideas=[idea])

    downgrade_ctx = "Execution failed after 2 retries.\nReason: Lint failed"
    failed_result = ExecutionResult(
        success=False,
        diff="",
        hooks_passed=False,
        failed_hook="ruff check .",
        retries=2,
        failure_reason="Lint failed",
        downgraded=True,
        downgrade_context=downgrade_ctx,
    )
    exec_results = [(idea, failed_result, "sigil/add-caching-layer")]

    published_issue_tuples = []

    async def capture_publish(resolved, cfg, gh, parallel_results, issue_tuples, **kw):
        published_issue_tuples.extend(issue_tuples)
        return [], [], []

    with (
        patch("sigil.cli.create_client", new_callable=AsyncMock, return_value=MagicMock()),
        patch("sigil.cli.ensure_labels", new_callable=AsyncMock),
        patch("sigil.cli.fetch_existing_issues", new_callable=AsyncMock, return_value=[]),
        patch("sigil.cli.is_knowledge_stale", new_callable=AsyncMock, return_value=False),
        patch("sigil.cli.analyze", new_callable=AsyncMock, return_value=[]),
        patch("sigil.cli.ideate", new_callable=AsyncMock, return_value=[idea]),
        patch("sigil.cli.validate_all", new_callable=AsyncMock, return_value=validation_result),
        patch(
            "sigil.cli.dedup_items",
            new_callable=AsyncMock,
            side_effect=lambda gh, items: DedupResult(skipped=[], remaining=list(items)),
        ),
        patch("sigil.cli.execute_parallel", new_callable=AsyncMock, return_value=exec_results),
        patch("sigil.cli.publish_results", new_callable=AsyncMock, side_effect=capture_publish),
        patch("sigil.cli.cleanup_after_push", new_callable=AsyncMock),
        patch("sigil.cli.save_ideas"),
        patch("sigil.cli.load_index", return_value=None),
        patch("sigil.cli.detect_instructions", return_value=MagicMock(has_instructions=False)),
        patch("sigil.cli.console"),
    ):
        await _run_pipeline(
            tmp_path, Config(max_prs_per_run=5), dry_run=False, mcp_mgr=_empty_mcp()
        )

    assert len(published_issue_tuples) == 1
    published_item, published_ctx = published_issue_tuples[0]
    assert published_item is idea
    assert published_ctx == downgrade_ctx


def test_status_renders_dashboard(tmp_path):
    (tmp_path / ".issues").mkdir(parents=True)
    (tmp_path / ".sigil" / "worktrees").mkdir(parents=True)
    (tmp_path / ".sigil" / "memory").mkdir(parents=True)
    (tmp_path / ".issues" / "current-sprint.md").write_text("# Sprint 12\nstatus: active\n")
    (tmp_path / ".sigil" / "worktrees" / "dead-code-utils").mkdir(parents=True)
    (tmp_path / ".sigil" / "memory" / "working.md").write_text(
        "# Working Memory\n\n## Pipeline State\n- PR opened\n- Issue filed\n"
    )

    mock_pr = MagicMock()
    mock_pr.number = 42
    mock_pr.title = "Fix dead code"
    mock_pr.html_url = "https://example.com/pr/42"
    mock_pr.labels = [MagicMock(name="sigil")]

    with (
        patch(
            "sigil.cli.create_client",
            new_callable=AsyncMock,
            return_value=MagicMock(repo=MagicMock(get_pulls=MagicMock(return_value=[mock_pr]))),
        ),
        patch("sigil.cli.console"),
        patch.dict("os.environ", {"GITHUB_TOKEN": "token"}, clear=False),
    ):
        status(repo=tmp_path)


def test_status_handles_missing_state(tmp_path):
    (tmp_path / ".sigil" / "memory").mkdir(parents=True)
    (tmp_path / ".sigil" / "memory" / "working.md").write_text("")

    with (
        patch("sigil.cli.create_client", new_callable=AsyncMock, return_value=None),
        patch("sigil.cli.console"),
        patch.dict("os.environ", {}, clear=True),
    ):
        status(repo=tmp_path)


def test_status_skips_prs_without_token(tmp_path):
    (tmp_path / ".sigil" / "memory").mkdir(parents=True)
    (tmp_path / ".sigil" / "memory" / "working.md").write_text("## Pipeline State\n- idle\n")

    with (
        patch("sigil.cli.create_client", new_callable=AsyncMock) as mock_client,
        patch("sigil.cli.console"),
        patch.dict("os.environ", {}, clear=True),
    ):
        status(repo=tmp_path)

    mock_client.assert_not_called()
