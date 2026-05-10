import subprocess
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import typer
import yaml

from sigil.cli import _run, _run_pipeline, config_show, init
from sigil.core.config import AGENT_NAMES, SIGIL_DIR, CONFIG_FILE, Config
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
        patch("sigil.cli.publish_issues", new_callable=AsyncMock) as mock_publish,
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
        patch("sigil.cli.publish_issues", new_callable=AsyncMock) as mock_publish,
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

    async def capture_publish(client, issue_tuples, *, max_issues):
        published_issue_tuples.extend(issue_tuples)
        return []

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
        patch("sigil.cli.publish_issues", new_callable=AsyncMock, side_effect=capture_publish),
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
        config = Config(agents={"compactor": [{"model": "openai/gpt-4o-mini"}]})
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
    downgrade_callback_calls: list[tuple] = []

    async def capture_publish(client, issue_tuples, *, max_issues):
        published_issue_tuples.extend(issue_tuples)
        return []

    async def fake_execute(*args, **kwargs):
        cb = kwargs.get("on_issue_downgrade")
        assert cb is not None, "execute_parallel must receive an on_issue_downgrade callback"
        for it, res, _branch in exec_results:
            if res.downgraded and not res.diff:
                cb(it, res.downgrade_context)
                downgrade_callback_calls.append((it, res.downgrade_context))
        return exec_results

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
        patch("sigil.cli.execute_parallel", new_callable=AsyncMock, side_effect=fake_execute),
        patch("sigil.cli.publish_issues", new_callable=AsyncMock, side_effect=capture_publish),
        patch("sigil.cli.load_index", return_value=None),
        patch("sigil.cli.detect_instructions", return_value=MagicMock(has_instructions=False)),
        patch("sigil.cli.console"),
    ):
        await _run_pipeline(
            tmp_path, Config(max_prs_per_run=5), dry_run=False, mcp_mgr=_empty_mcp()
        )

    assert downgrade_callback_calls == [(pr_finding, downgrade_ctx)], (
        "execute_parallel should fire on_issue_downgrade for diff-less downgrades"
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
    downgrade_callback_calls: list[tuple] = []

    async def capture_publish(client, issue_tuples, *, max_issues):
        published_issue_tuples.extend(issue_tuples)
        return []

    async def fake_execute(*args, **kwargs):
        cb = kwargs.get("on_issue_downgrade")
        assert cb is not None, "execute_parallel must receive an on_issue_downgrade callback"
        for it, res, _branch in exec_results:
            if res.downgraded and not res.diff:
                cb(it, res.downgrade_context)
                downgrade_callback_calls.append((it, res.downgrade_context))
        return exec_results

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
        patch("sigil.cli.execute_parallel", new_callable=AsyncMock, side_effect=fake_execute),
        patch("sigil.cli.publish_issues", new_callable=AsyncMock, side_effect=capture_publish),
        patch("sigil.cli.save_ideas"),
        patch("sigil.cli.load_index", return_value=None),
        patch("sigil.cli.detect_instructions", return_value=MagicMock(has_instructions=False)),
        patch("sigil.cli.console"),
    ):
        await _run_pipeline(
            tmp_path, Config(max_prs_per_run=5), dry_run=False, mcp_mgr=_empty_mcp()
        )

    assert downgrade_callback_calls == [(idea, downgrade_ctx)], (
        "execute_parallel should fire on_issue_downgrade for diff-less downgrades"
    )

    assert len(published_issue_tuples) == 1
    published_item, published_ctx = published_issue_tuples[0]
    assert published_item is idea
    assert published_ctx == downgrade_ctx


def _extract_printed(mock_console):
    return [call[0][0] for call in mock_console.print.call_args_list if call[0]]


def test_config_show_default(tmp_path):
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True)

    with patch("sigil.cli.console") as mock_console:
        config_show(repo=tmp_path)

    printed = _extract_printed(mock_console)

    core_table = next(p for p in printed if getattr(p, "title", None) == "Core Settings")
    rows = core_table.rows
    model_row = next(r for r in rows if r.cells[0].text == "Model")
    assert model_row.cells[1].text == Config().model
    assert model_row.cells[2].text == "default"

    boldness_row = next(r for r in rows if r.cells[0].text == "Boldness")
    assert boldness_row.cells[1].text == "bold"
    assert boldness_row.cells[2].text == "default"

    agent_table = next(p for p in printed if getattr(p, "title", None) == "Agent Resolution")
    agent_names_in_table = {r.cells[0].text for r in agent_table.rows}
    for name in sorted(AGENT_NAMES):
        assert name in agent_names_in_table

    computed_panel = next(p for p in printed if getattr(p, "title", None) == "Computed Values")
    assert "Effective max retries" in computed_panel.renderable


def test_config_show_with_config(tmp_path):
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True)
    sigil_dir = tmp_path / SIGIL_DIR
    sigil_dir.mkdir(parents=True)
    config_data = {
        "model": "openai/gpt-4o",
        "boldness": "experimental",
        "max_prs_per_run": 10,
    }
    (sigil_dir / CONFIG_FILE).write_text(yaml.dump(config_data))

    with patch("sigil.cli.console") as mock_console:
        config_show(repo=tmp_path)

    printed = _extract_printed(mock_console)
    core_table = next(p for p in printed if getattr(p, "title", None) == "Core Settings")
    model_row = next(r for r in core_table.rows if r.cells[0].text == "Model")
    assert model_row.cells[1].text == "openai/gpt-4o"
    assert model_row.cells[2].text == "config"

    boldness_row = next(r for r in core_table.rows if r.cells[0].text == "Boldness")
    assert boldness_row.cells[1].text == "experimental"
    assert boldness_row.cells[2].text == "config"

    prs_row = next(r for r in core_table.rows if r.cells[0].text == "Max PRs/run")
    assert prs_row.cells[1].text == "10"
    assert prs_row.cells[2].text == "config"

    retries_row = next(r for r in core_table.rows if r.cells[0].text == "Max retries")
    assert retries_row.cells[2].text == "default"


def test_config_show_agent_resolution(tmp_path):
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True)
    sigil_dir = tmp_path / SIGIL_DIR
    sigil_dir.mkdir(parents=True)
    config_data = {
        "agents": {
            "engineer": [{"model": "anthropic/claude-opus-4-7", "max_iterations": 30}],
            "ideator": [
                {"model": "anthropic/claude-opus-4-7"},
                {"model": "openai/gpt-4o"},
            ],
        },
    }
    (sigil_dir / CONFIG_FILE).write_text(yaml.dump(config_data))

    with patch("sigil.cli.console") as mock_console:
        config_show(repo=tmp_path)

    printed = _extract_printed(mock_console)
    agent_table = next(p for p in printed if getattr(p, "title", None) == "Agent Resolution")

    engineer_row = next(r for r in agent_table.rows if r.cells[0].text == "engineer")
    assert engineer_row.cells[1].text == "anthropic/claude-opus-4-7"
    assert engineer_row.cells[2].text == "30"
    assert engineer_row.cells[5].text == "config"

    ideator_rows = [r for r in agent_table.rows if "ideator" in r.cells[0].text]
    assert len(ideator_rows) == 2
    assert ideator_rows[0].cells[1].text == "anthropic/claude-opus-4-7"
    assert ideator_rows[1].cells[1].text == "openai/gpt-4o"

    auditor_row = next(r for r in agent_table.rows if r.cells[0].text == "auditor")
    assert auditor_row.cells[5].text == "default"


def test_config_show_invalid_config(tmp_path):
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True)
    sigil_dir = tmp_path / SIGIL_DIR
    sigil_dir.mkdir(parents=True)
    (sigil_dir / CONFIG_FILE).write_text("boldness: not_a_real_value\n")

    with (
        patch("sigil.cli.console") as mock_console,
        pytest.raises(typer.Exit) as exc_info,
    ):
        config_show(repo=tmp_path)

    assert exc_info.value.exit_code == 1
    printed = _extract_printed(mock_console)
    error_msg = next(p for p in printed if isinstance(p, str) and "Config error" in p)
    assert error_msg is not None


def test_config_show_computed_values(tmp_path):
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True)
    sigil_dir = tmp_path / SIGIL_DIR
    sigil_dir.mkdir(parents=True)
    config_data = {
        "max_retries": 5,
        "post_hooks": ["uv run ruff format .", "uv run pytest tests/ -x -q"],
        "ignore": ["vendor/**", "*.generated.*"],
    }
    (sigil_dir / CONFIG_FILE).write_text(yaml.dump(config_data))

    with patch("sigil.cli.console") as mock_console:
        config_show(repo=tmp_path)

    printed = _extract_printed(mock_console)
    computed_panel = next(p for p in printed if getattr(p, "title", None) == "Computed Values")
    panel_text = computed_panel.renderable
    assert "Effective max retries: 5" in panel_text
    assert "User ignore patterns: vendor/**, *.generated.*" in panel_text
    assert "Model overrides: (none)" in panel_text
