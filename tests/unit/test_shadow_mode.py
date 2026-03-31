from unittest.mock import AsyncMock, MagicMock, patch

from sigil.cli import _run_pipeline, _write_shadow_report
from sigil.core.config import Config, SIGIL_DIR, CONFIG_FILE
from sigil.pipeline.models import ExecutionResult, FailureType, ValidationResult
from sigil.pipeline.maintenance import Finding
from sigil.pipeline.ideation import FeatureIdea


def _empty_mcp():
    mgr = MagicMock()
    mgr.server_count = 0
    mgr.tool_count = 0
    return mgr


def _make_finding(
    category: str = "dead_code",
    file: str = "utils.py",
    description: str = "unused import",
    disposition: str = "pr",
    priority: int = 1,
) -> Finding:
    return Finding(
        category=category,
        file=file,
        line=10,
        description=description,
        risk="low",
        suggested_fix="remove it",
        disposition=disposition,
        priority=priority,
        rationale="test",
    )


def _make_idea(
    title: str = "Add caching",
    disposition: str = "pr",
    priority: int = 1,
) -> FeatureIdea:
    return FeatureIdea(
        title=title,
        description="Add a caching layer",
        rationale="Performance",
        complexity="small",
        disposition=disposition,
        priority=priority,
    )


class TestShadowModeConfig:
    def test_shadow_mode_defaults_false(self):
        config = Config()
        assert config.shadow_mode is False

    def test_shadow_mode_can_be_set(self):
        config = Config(shadow_mode=True)
        assert config.shadow_mode is True

    def test_shadow_mode_loads_from_yaml(self, tmp_path):
        sigil_dir = tmp_path / SIGIL_DIR
        sigil_dir.mkdir()
        config_path = sigil_dir / CONFIG_FILE
        config_path.write_text("shadow_mode: true\n")
        config = Config.load(tmp_path)
        assert config.shadow_mode is True

    def test_shadow_mode_false_in_yaml(self, tmp_path):
        sigil_dir = tmp_path / SIGIL_DIR
        sigil_dir.mkdir()
        config_path = sigil_dir / CONFIG_FILE
        config_path.write_text("shadow_mode: false\n")
        config = Config.load(tmp_path)
        assert config.shadow_mode is False


class TestShadowReport:
    def test_report_contains_findings(self, tmp_path):
        findings = [_make_finding()]
        _write_shadow_report(
            tmp_path,
            Config(),
            findings,
            [],
            [],
            [],
        )
        report = (tmp_path / ".sigil" / "traces" / "shadow_report.md").read_text()
        assert "## Findings (1)" in report
        assert "dead_code" in report
        assert "utils.py:10" in report

    def test_report_contains_ideas(self, tmp_path):
        ideas = [_make_idea()]
        _write_shadow_report(
            tmp_path,
            Config(),
            [],
            ideas,
            [],
            [],
        )
        report = (tmp_path / ".sigil" / "traces" / "shadow_report.md").read_text()
        assert "## Ideas (1)" in report
        assert "Add caching" in report

    def test_report_contains_execution_results(self, tmp_path):
        finding = _make_finding()
        result = ExecutionResult(
            success=True,
            diff="--- a/utils.py\n+++ b/utils.py\n@@ -1 +1 @@\n-old\n+new",
            hooks_passed=True,
            failed_hook=None,
            retries=0,
            failure_reason=None,
            summary="Fixed the thing",
        )
        _write_shadow_report(
            tmp_path,
            Config(),
            [finding],
            [],
            [(finding, result, "sigil/auto/test-123")],
            [],
        )
        report = (tmp_path / ".sigil" / "traces" / "shadow_report.md").read_text()
        assert "## Execution Results" in report
        assert "✅ Success" in report
        assert "sigil/auto/test-123" in report
        assert "```diff" in report
        assert "Fixed the thing" in report

    def test_report_contains_failed_execution(self, tmp_path):
        finding = _make_finding()
        result = ExecutionResult(
            success=False,
            diff="",
            hooks_passed=False,
            failed_hook="pytest",
            retries=2,
            failure_reason="Post-hooks failed after all retries",
            failure_type=FailureType.POST_HOOK,
        )
        _write_shadow_report(
            tmp_path,
            Config(),
            [finding],
            [],
            [(finding, result, "sigil/auto/test-456")],
            [],
        )
        report = (tmp_path / ".sigil" / "traces" / "shadow_report.md").read_text()
        assert "❌ Failed" in report
        assert "Post-hooks failed" in report

    def test_report_contains_issue_items(self, tmp_path):
        finding = _make_finding(disposition="issue")
        _write_shadow_report(
            tmp_path,
            Config(),
            [],
            [],
            [],
            [finding],
        )
        report = (tmp_path / ".sigil" / "traces" / "shadow_report.md").read_text()
        assert "## Items That Would Become Issues" in report
        assert "unused import" in report

    def test_report_empty_sections(self, tmp_path):
        _write_shadow_report(
            tmp_path,
            Config(),
            [],
            [],
            [],
            [],
        )
        report = (tmp_path / ".sigil" / "traces" / "shadow_report.md").read_text()
        assert "## Findings (0)" in report
        assert "_No findings._" in report
        assert "## Ideas (0)" in report
        assert "_No ideas._" in report
        assert "_No items were executed._" in report

    def test_report_contains_calibration_notes(self, tmp_path):
        _write_shadow_report(
            tmp_path,
            Config(),
            [],
            [],
            [],
            [],
        )
        report = (tmp_path / ".sigil" / "traces" / "shadow_report.md").read_text()
        assert "## Calibration Notes" in report
        assert "boldness" in report

    def test_report_contains_config_info(self, tmp_path):
        _write_shadow_report(
            tmp_path,
            Config(boldness="experimental", model="openai/gpt-4o"),
            [],
            [],
            [],
            [],
        )
        report = (tmp_path / ".sigil" / "traces" / "shadow_report.md").read_text()
        assert "experimental" in report
        assert "openai/gpt-4o" in report

    def test_report_creates_traces_dir(self, tmp_path):
        assert not (tmp_path / ".sigil" / "traces").exists()
        _write_shadow_report(tmp_path, Config(), [], [], [], [])
        assert (tmp_path / ".sigil" / "traces").is_dir()


class TestShadowModePipeline:
    async def test_shadow_mode_skips_github_client(self, tmp_path):
        (tmp_path / SIGIL_DIR).mkdir(parents=True)
        (tmp_path / SIGIL_DIR / CONFIG_FILE).write_text(Config().to_yaml())

        with (
            patch("sigil.cli.create_client", new_callable=AsyncMock) as mock_gh,
            patch("sigil.cli.is_knowledge_stale", new_callable=AsyncMock, return_value=False),
            patch("sigil.cli.analyze", new_callable=AsyncMock, return_value=[]),
            patch("sigil.cli.ideate", new_callable=AsyncMock, return_value=[]),
            patch("sigil.cli.load_index", return_value=None),
            patch("sigil.cli.detect_instructions", return_value=MagicMock(has_instructions=False)),
            patch("sigil.cli.console"),
        ):
            await _run_pipeline(
                tmp_path,
                Config(shadow_mode=True),
                dry_run=False,
                mcp_mgr=_empty_mcp(),
            )

        mock_gh.assert_not_called()

    async def test_shadow_mode_skips_publish(self, tmp_path):
        (tmp_path / SIGIL_DIR).mkdir(parents=True)
        (tmp_path / SIGIL_DIR / CONFIG_FILE).write_text(Config().to_yaml())

        finding = _make_finding()
        validation_result = ValidationResult(findings=[finding], ideas=[])

        exec_result = ExecutionResult(
            success=True,
            diff="+x",
            hooks_passed=True,
            failed_hook=None,
            retries=0,
            failure_reason=None,
        )

        with (
            patch("sigil.cli.is_knowledge_stale", new_callable=AsyncMock, return_value=False),
            patch("sigil.cli.analyze", new_callable=AsyncMock, return_value=[finding]),
            patch("sigil.cli.ideate", new_callable=AsyncMock, return_value=[]),
            patch("sigil.cli.validate_all", new_callable=AsyncMock, return_value=validation_result),
            patch(
                "sigil.cli.execute_parallel",
                new_callable=AsyncMock,
                return_value=[(finding, exec_result, "sigil/auto/test-123")],
            ),
            patch("sigil.cli.publish_results", new_callable=AsyncMock) as mock_publish,
            patch("sigil.cli.cleanup_after_push", new_callable=AsyncMock) as mock_cleanup,
            patch("sigil.cli.load_index", return_value=None),
            patch("sigil.cli.detect_instructions", return_value=MagicMock(has_instructions=False)),
            patch("sigil.cli.load_open_ideas", return_value=[]),
            patch("sigil.cli.console"),
        ):
            await _run_pipeline(
                tmp_path,
                Config(shadow_mode=True),
                dry_run=False,
                mcp_mgr=_empty_mcp(),
            )

        mock_publish.assert_not_called()
        mock_cleanup.assert_called_once()

    async def test_shadow_mode_generates_report(self, tmp_path):
        (tmp_path / SIGIL_DIR).mkdir(parents=True)
        (tmp_path / SIGIL_DIR / CONFIG_FILE).write_text(Config().to_yaml())

        finding = _make_finding()
        validation_result = ValidationResult(findings=[finding], ideas=[])

        exec_result = ExecutionResult(
            success=True,
            diff="--- a/utils.py\n+++ b/utils.py\n-old\n+new",
            hooks_passed=True,
            failed_hook=None,
            retries=0,
            failure_reason=None,
            summary="Removed unused import",
        )

        with (
            patch("sigil.cli.is_knowledge_stale", new_callable=AsyncMock, return_value=False),
            patch("sigil.cli.analyze", new_callable=AsyncMock, return_value=[finding]),
            patch("sigil.cli.ideate", new_callable=AsyncMock, return_value=[]),
            patch("sigil.cli.validate_all", new_callable=AsyncMock, return_value=validation_result),
            patch(
                "sigil.cli.execute_parallel",
                new_callable=AsyncMock,
                return_value=[(finding, exec_result, "sigil/auto/test-123")],
            ),
            patch("sigil.cli.publish_results", new_callable=AsyncMock),
            patch("sigil.cli.cleanup_after_push", new_callable=AsyncMock),
            patch("sigil.cli.load_index", return_value=None),
            patch("sigil.cli.detect_instructions", return_value=MagicMock(has_instructions=False)),
            patch("sigil.cli.load_open_ideas", return_value=[]),
            patch("sigil.cli.console"),
        ):
            await _run_pipeline(
                tmp_path,
                Config(shadow_mode=True),
                dry_run=False,
                mcp_mgr=_empty_mcp(),
            )

        report_path = tmp_path / ".sigil" / "traces" / "shadow_report.md"
        assert report_path.exists()
        report = report_path.read_text()
        assert "Sigil Shadow Report" in report
        assert "dead_code" in report
        assert "✅ Success" in report

    async def test_shadow_mode_cleans_up_all_branches(self, tmp_path):
        (tmp_path / SIGIL_DIR).mkdir(parents=True)
        (tmp_path / SIGIL_DIR / CONFIG_FILE).write_text(Config().to_yaml())

        f1 = _make_finding(file="a.py", priority=1)
        f2 = _make_finding(file="b.py", priority=2)
        validation_result = ValidationResult(findings=[f1, f2], ideas=[])

        exec_result = ExecutionResult(
            success=True,
            diff="+x",
            hooks_passed=True,
            failed_hook=None,
            retries=0,
            failure_reason=None,
        )

        cleaned_branches = []

        async def capture_cleanup(repo, results, branches):
            cleaned_branches.extend(branches)

        with (
            patch("sigil.cli.is_knowledge_stale", new_callable=AsyncMock, return_value=False),
            patch("sigil.cli.analyze", new_callable=AsyncMock, return_value=[f1, f2]),
            patch("sigil.cli.ideate", new_callable=AsyncMock, return_value=[]),
            patch("sigil.cli.validate_all", new_callable=AsyncMock, return_value=validation_result),
            patch(
                "sigil.cli.execute_parallel",
                new_callable=AsyncMock,
                return_value=[
                    (f1, exec_result, "sigil/auto/a-111"),
                    (f2, exec_result, "sigil/auto/b-222"),
                ],
            ),
            patch("sigil.cli.publish_results", new_callable=AsyncMock),
            patch(
                "sigil.cli.cleanup_after_push", new_callable=AsyncMock, side_effect=capture_cleanup
            ),
            patch("sigil.cli.load_index", return_value=None),
            patch("sigil.cli.detect_instructions", return_value=MagicMock(has_instructions=False)),
            patch("sigil.cli.load_open_ideas", return_value=[]),
            patch("sigil.cli.console"),
        ):
            await _run_pipeline(
                tmp_path,
                Config(shadow_mode=True),
                dry_run=False,
                mcp_mgr=_empty_mcp(),
            )

        assert "sigil/auto/a-111" in cleaned_branches
        assert "sigil/auto/b-222" in cleaned_branches

    async def test_non_shadow_mode_still_publishes(self, tmp_path):
        (tmp_path / SIGIL_DIR).mkdir(parents=True)
        (tmp_path / SIGIL_DIR / CONFIG_FILE).write_text(Config().to_yaml())

        finding = _make_finding()
        validation_result = ValidationResult(findings=[finding], ideas=[])

        exec_result = ExecutionResult(
            success=True,
            diff="+x",
            hooks_passed=True,
            failed_hook=None,
            retries=0,
            failure_reason=None,
        )

        with (
            patch("sigil.cli.create_client", new_callable=AsyncMock, return_value=MagicMock()),
            patch("sigil.cli.ensure_labels", new_callable=AsyncMock),
            patch("sigil.cli.fetch_existing_issues", new_callable=AsyncMock, return_value=[]),
            patch("sigil.cli.is_knowledge_stale", new_callable=AsyncMock, return_value=False),
            patch("sigil.cli.analyze", new_callable=AsyncMock, return_value=[finding]),
            patch("sigil.cli.ideate", new_callable=AsyncMock, return_value=[]),
            patch("sigil.cli.validate_all", new_callable=AsyncMock, return_value=validation_result),
            patch(
                "sigil.cli.execute_parallel",
                new_callable=AsyncMock,
                return_value=[(finding, exec_result, "sigil/auto/test-123")],
            ),
            patch(
                "sigil.cli.publish_results",
                new_callable=AsyncMock,
                return_value=(["https://github.com/pr/1"], [], {"sigil/auto/test-123"}),
            ),
            patch("sigil.cli.cleanup_after_push", new_callable=AsyncMock),
            patch("sigil.cli.load_index", return_value=None),
            patch("sigil.cli.detect_instructions", return_value=MagicMock(has_instructions=False)),
            patch("sigil.cli.load_open_ideas", return_value=[]),
            patch("sigil.cli.dedup_items", new_callable=AsyncMock) as mock_dedup,
            patch("sigil.cli.filter_chronic", return_value=([finding], [], [])),
            patch("sigil.cli.console"),
        ):
            mock_dedup.return_value = MagicMock(skipped=[], remaining=[finding])
            await _run_pipeline(
                tmp_path,
                Config(shadow_mode=False),
                dry_run=False,
                mcp_mgr=_empty_mcp(),
            )

        report_path = tmp_path / ".sigil" / "traces" / "shadow_report.md"
        assert not report_path.exists()
