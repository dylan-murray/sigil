from pathlib import Path

import pytest
from typer import Exit

from sigil.core.config import Config
from sigil.core.models import TokenUsage
from sigil.core.report import display_report, write_run_report
from sigil.pipeline.models import ExecutionResult, FeatureIdea, Finding


def _make_finding(**overrides) -> Finding:
    defaults = dict(
        category="dead_code",
        file="src/foo.py",
        line=10,
        description="Unused import",
        risk="low",
        suggested_fix="Remove the import",
        disposition="pr",
        priority=1,
        rationale="Cleanup",
    )
    defaults.update(overrides)
    return Finding(**defaults)


def _make_idea(**overrides) -> FeatureIdea:
    defaults = dict(
        title="Add caching layer",
        description="Cache LLM responses",
        rationale="Reduce costs",
        complexity="medium",
        disposition="pr",
        priority=2,
    )
    defaults.update(overrides)
    return FeatureIdea(**defaults)


def _make_usage() -> TokenUsage:
    usage = TokenUsage()
    usage.record("anthropic/claude-sonnet-4-6", 1000, 500, 100, 50, 0.05)
    usage.record("anthropic/claude-haiku-4-5", 2000, 300, 0, 0, 0.01)
    return usage


def _make_exec_result(**overrides) -> ExecutionResult:
    defaults = dict(
        success=True,
        diff="+x\n",
        hooks_passed=True,
        failed_hook=None,
        retries=0,
        failure_reason=None,
    )
    defaults.update(overrides)
    return ExecutionResult(**defaults)


class TestWriteRunReport:
    def test_creates_report_file(self, tmp_path: Path) -> None:
        repo = tmp_path / "myrepo"
        repo.mkdir()
        findings = [_make_finding()]
        ideas = [_make_idea()]
        usage = _make_usage()
        exec_result = _make_exec_result()
        parallel_results = [
            (findings[0], exec_result, "sigil/auto/dead-code-foo-1234"),
        ]

        result = write_run_report(
            repo=repo,
            config=Config(),
            findings=findings,
            ideas=ideas,
            parallel_results=parallel_results,
            pr_urls=["https://github.com/org/repo/pull/1"],
            issue_urls=["https://github.com/org/repo/issues/5"],
            usage=usage,
            run_id="abc123",
            duration_s=42.5,
        )

        assert result is not None
        assert result.parent.name == "reports"
        assert result.parent.parent.name == ".sigil"
        assert result.suffix == ".md"

        content = result.read_text()
        assert "## Summary" in content
        assert "## Findings" in content
        assert "## Ideas" in content
        assert "## Execution Results" in content
        assert "## PRs Opened" in content
        assert "## Issues Opened" in content
        assert "## Token Usage" in content
        assert "abc123" in content
        assert "42.5s" in content
        assert "anthropic/claude-sonnet-4-6" in content
        assert "anthropic/claude-haiku-4-5" in content
        assert "dead_code" in content
        assert "src/foo.py" in content
        assert "Add caching layer" in content
        assert "https://github.com/org/repo/pull/1" in content
        assert "https://github.com/org/repo/issues/5" in content

    def test_empty_findings_and_ideas(self, tmp_path: Path) -> None:
        repo = tmp_path / "myrepo"
        repo.mkdir()
        usage = _make_usage()

        result = write_run_report(
            repo=repo,
            config=Config(),
            findings=[],
            ideas=[],
            parallel_results=[],
            pr_urls=[],
            issue_urls=[],
            usage=usage,
            run_id="empty123",
            duration_s=5.0,
        )

        assert result is not None
        content = result.read_text()
        assert "## Findings" in content
        assert "## Ideas" in content
        assert "_No findings._" in content
        assert "_No ideas._" in content
        assert "_No items executed._" in content
        assert "_None._" in content

    def test_dry_run_no_execution_results(self, tmp_path: Path) -> None:
        repo = tmp_path / "myrepo"
        repo.mkdir()
        findings = [_make_finding()]
        usage = _make_usage()

        result = write_run_report(
            repo=repo,
            config=Config(),
            findings=findings,
            ideas=[],
            parallel_results=[],
            pr_urls=[],
            issue_urls=[],
            usage=usage,
            run_id="dry456",
            duration_s=10.0,
        )

        assert result is not None
        content = result.read_text()
        assert "_No items executed._" in content
        assert "_None._" in content
        assert "dead_code" in content

    def test_failed_execution_result(self, tmp_path: Path) -> None:
        repo = tmp_path / "myrepo"
        repo.mkdir()
        finding = _make_finding()
        failed_result = ExecutionResult(
            success=False,
            diff="",
            hooks_passed=False,
            failed_hook="pytest",
            retries=3,
            failure_reason="Tests failed",
            downgraded=True,
            downgrade_context="Execution failed",
        )
        parallel_results = [(finding, failed_result, "")]

        result = write_run_report(
            repo=repo,
            config=Config(),
            findings=[finding],
            ideas=[],
            parallel_results=parallel_results,
            pr_urls=[],
            issue_urls=["https://github.com/org/repo/issues/10"],
            usage=TokenUsage(),
            run_id="fail789",
            duration_s=60.0,
        )

        assert result is not None
        content = result.read_text()
        assert "No" in content
        assert "Tests failed" in content

    def test_returns_none_when_nothing_to_report(self, tmp_path: Path) -> None:
        repo = tmp_path / "myrepo"
        repo.mkdir()
        usage = TokenUsage()

        result = write_run_report(
            repo=repo,
            config=Config(),
            findings=[],
            ideas=[],
            parallel_results=[],
            pr_urls=[],
            issue_urls=[],
            usage=usage,
            run_id="nothing",
            duration_s=1.0,
        )

        assert result is None

    def test_report_filename_format(self, tmp_path: Path) -> None:
        repo = tmp_path / "myrepo"
        repo.mkdir()

        result = write_run_report(
            repo=repo,
            config=Config(),
            findings=[_make_finding()],
            ideas=[],
            parallel_results=[],
            pr_urls=[],
            issue_urls=[],
            usage=_make_usage(),
            run_id="fmt123",
            duration_s=5.0,
        )

        assert result is not None
        filename = result.name
        assert filename.endswith(".md")
        parts = filename.replace(".md", "").split("-")
        assert len(parts) == 4
        assert len(parts[0]) == 4
        assert len(parts[1]) == 2
        assert len(parts[2]) == 2
        assert len(parts[3]) == 6

    def test_config_model_and_boldness_in_summary(self, tmp_path: Path) -> None:
        repo = tmp_path / "myrepo"
        repo.mkdir()
        config = Config(model="openai/gpt-4o", boldness="conservative")

        result = write_run_report(
            repo=repo,
            config=config,
            findings=[_make_finding()],
            ideas=[],
            parallel_results=[],
            pr_urls=[],
            issue_urls=[],
            usage=_make_usage(),
            run_id="cfg123",
            duration_s=5.0,
        )

        assert result is not None
        content = result.read_text()
        assert "openai/gpt-4o" in content
        assert "conservative" in content


class TestDisplayReport:
    def test_displays_most_recent_report(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / ".sigil" / "reports"
        reports_dir.mkdir(parents=True)

        (reports_dir / "2026-04-25-100000.md").write_text("# Old Report\nOld content")
        (reports_dir / "2026-04-26-120000.md").write_text("# New Report\nNew content")

        display_report(tmp_path, None)

    def test_displays_specific_date_report(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / ".sigil" / "reports"
        reports_dir.mkdir(parents=True)

        (reports_dir / "2026-04-25-100000.md").write_text("# April 25 Report")
        (reports_dir / "2026-04-26-120000.md").write_text("# April 26 Report")

        display_report(tmp_path, "2026-04-25")

    def test_no_reports_exits(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / ".sigil" / "reports"
        reports_dir.mkdir(parents=True)

        with pytest.raises(Exit):
            display_report(tmp_path, None)

    def test_no_matching_date_exits(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / ".sigil" / "reports"
        reports_dir.mkdir(parents=True)

        (reports_dir / "2026-04-25-100000.md").write_text("# Report")

        with pytest.raises(Exit):
            display_report(tmp_path, "2026-05-01")

    def test_no_sigil_dir_exits(self, tmp_path: Path) -> None:
        with pytest.raises(Exit):
            display_report(tmp_path, None)
