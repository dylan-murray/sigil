import subprocess
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import typer
import yaml

from sigil.cli import _format_job_summary, _run, _run_pipeline, _write_github_summary, init
from sigil.core.config import SIGIL_DIR, CONFIG_FILE, Config
from sigil.core.models import TokenUsage
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


def _make_usage(
    calls: int = 5,
    prompt_tokens: int = 1000,
    completion_tokens: int = 500,
    cost_usd: float = 0.05,
) -> TokenUsage:
    return TokenUsage(
        calls=calls,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=cost_usd,
        by_model={
            "anthropic/claude-sonnet-4-6": TokenUsage(
                calls=calls,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=cost_usd,
                cache_read_tokens=0,
                cache_creation_tokens=0,
            )
        },
    )


def test_format_job_summary_with_results():
    usage = _make_usage(calls=10, prompt_tokens=5000, completion_tokens=2000, cost_usd=0.12)
    exec_results = [
        (
            "fix A",
            ExecutionResult(
                success=True,
                diff="+x",
                hooks_passed=True,
                failed_hook=None,
                retries=0,
                failure_reason=None,
            ),
        ),
        (
            "fix B",
            ExecutionResult(
                success=True,
                diff="+y",
                hooks_passed=True,
                failed_hook=None,
                retries=1,
                failure_reason=None,
            ),
        ),
        (
            "fix C",
            ExecutionResult(
                success=False,
                diff="",
                hooks_passed=False,
                failed_hook="pytest",
                retries=2,
                failure_reason="Tests failed",
                downgraded=True,
                downgrade_context="ctx",
            ),
        ),
    ]
    pr_urls = ["https://github.com/owner/repo/pull/1", "https://github.com/owner/repo/pull/2"]
    issue_urls = ["https://github.com/owner/repo/issues/3"]

    md = _format_job_summary(
        findings_count=5,
        ideas_count=3,
        execution_results=exec_results,
        pr_urls=pr_urls,
        issue_urls=issue_urls,
        usage=usage,
    )

    assert "## ⟡ Sigil Run Summary" in md
    assert "| Findings | 5 |" in md
    assert "| Ideas | 3 |" in md
    assert "| Executed (ok) | 2 |" in md
    assert "| Executed (fail) | 1 |" in md
    assert "| PRs opened | 2 |" in md
    assert "| Issues filed | 1 |" in md
    assert "🟡" in md
    assert "67%" in md
    assert "https://github.com/owner/repo/pull/1" in md
    assert "https://github.com/owner/repo/issues/3" in md
    assert "10" in md
    assert "$0.12" in md


def test_format_job_summary_zero_executions():
    usage = _make_usage(calls=0, prompt_tokens=0, completion_tokens=0, cost_usd=0.0)
    md = _format_job_summary(
        findings_count=0,
        ideas_count=0,
        execution_results=[],
        pr_urls=[],
        issue_urls=[],
        usage=usage,
    )

    assert "## ⟡ Sigil Run Summary" in md
    assert "| Executed (ok) | 0 |" in md
    assert "| Executed (fail) | 0 |" in md
    assert "0%" in md
    assert "None" in md
    assert "🔴" in md


def _make_usage(
    calls: int = 10,
    prompt_tokens: int = 5000,
    completion_tokens: int = 2000,
    cost_usd: float = 0.12,
) -> TokenUsage:
    return TokenUsage(
        calls=calls,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=cost_usd,
    )


def test_write_github_summary_writes_when_env_set(tmp_path, monkeypatch):
    summary_file = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))

    usage = _make_usage()
    _write_github_summary(
        findings_count=1,
        ideas_count=0,
        execution_results=[],
        pr_urls=[],
        issue_urls=[],
        usage=usage,
    )

    assert summary_file.exists()
    content = summary_file.read_text()
    assert "## ⟡ Sigil Run Summary" in content


def test_write_github_summary_noop_when_env_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    usage = _make_usage()
    _write_github_summary(
        findings_count=1,
        ideas_count=0,
        execution_results=[],
        pr_urls=[],
        issue_urls=[],
        usage=usage,
    )


def test_write_github_summary_handles_oserror(monkeypatch, tmp_path):
    bad_path = tmp_path / "nonexistent" / "dir" / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(bad_path))

    usage = _make_usage()
    _write_github_summary(
        findings_count=1,
        ideas_count=0,
        execution_results=[],
        pr_urls=[],
        issue_urls=[],
        usage=usage,
    )
