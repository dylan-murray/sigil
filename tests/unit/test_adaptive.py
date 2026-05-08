import json
from unittest.mock import AsyncMock, patch

import pytest

from sigil.core.config import SIGIL_DIR, Config
from sigil.pipeline.adaptive import (
    FINDINGS_FILE,
    RUN_STATE_FILE,
    AdaptivePlan,
    RunState,
    StageDecision,
    classify_file,
    compute_adaptive_plan,
    load_previous_findings,
    load_run_state,
    save_findings,
    save_run_state,
)
from sigil.pipeline.models import Finding


class TestClassifyFile:
    @pytest.mark.parametrize(
        "path,expected",
        [
            ("README.md", "docs"),
            ("docs/guide.rst", "docs"),
            ("CHANGELOG.txt", "docs"),
            ("docs/api.adoc", "docs"),
            ("NOTES.org", "docs"),
            (".sigil/config.yml", "config"),
            ("pyproject.toml", "config"),
            ("setup.cfg", "config"),
            ("ruff.toml", "config"),
            ("Makefile", "config"),
            ("Dockerfile", "config"),
            (".env", "config"),
            (".env.local", "config"),
            ("docker-compose.yml", "config"),
            ("tsconfig.json", "config"),
            ("package.json", "config"),
            ("src/app.py", "code"),
            ("lib/index.ts", "code"),
            ("main.go", "code"),
            ("src/lib.rs", "code"),
            ("app.rb", "code"),
            ("App.java", "code"),
            ("main.kt", "code"),
            ("utils.c", "code"),
            ("header.h", "code"),
            ("app.cpp", "code"),
            ("app.hpp", "code"),
            ("Program.cs", "code"),
            ("app.swift", "code"),
            ("run.sh", "code"),
            ("Makefile", "config"),
            ("config.yaml", "config"),
            ("config.ini", "config"),
            (".flake8", "config"),
            ("mypy.ini", "config"),
            (".mypy.ini", "config"),
            ("tox.ini", "config"),
            ("setup.py", "config"),
            ("Gemfile", "config"),
            ("Cargo.toml", "config"),
            ("go.mod", "config"),
            ("go.sum", "config"),
            ("yarn.lock", "config"),
        ],
    )
    def test_classify_file(self, path, expected):
        assert classify_file(path) == expected

    def test_classify_unknown_extension_defaults_to_code(self):
        assert classify_file("data.xyz") == "code"

    def test_classify_no_extension_defaults_to_code(self):
        assert classify_file("Makefile") == "config"

    def test_classify_pyproject_toml_is_config(self):
        assert classify_file("pyproject.toml") == "config"


class TestRunState:
    def test_save_and_load(self, tmp_path):
        state = RunState(last_head="abc123", last_run_time="2024-01-01T00:00:00Z")
        save_run_state(tmp_path, state)
        loaded = load_run_state(tmp_path)
        assert loaded is not None
        assert loaded.last_head == "abc123"
        assert loaded.last_run_time == "2024-01-01T00:00:00Z"

    def test_load_missing_returns_none(self, tmp_path):
        assert load_run_state(tmp_path) is None

    def test_load_invalid_json_returns_none(self, tmp_path):
        sigil_dir = tmp_path / SIGIL_DIR
        sigil_dir.mkdir(parents=True)
        (sigil_dir / RUN_STATE_FILE).write_text("not json")
        assert load_run_state(tmp_path) is None

    def test_load_missing_fields_returns_none(self, tmp_path):
        sigil_dir = tmp_path / SIGIL_DIR
        sigil_dir.mkdir(parents=True)
        (sigil_dir / RUN_STATE_FILE).write_text(json.dumps({"last_head": "abc"}))
        assert load_run_state(tmp_path) is None

    def test_save_creates_directory(self, tmp_path):
        state = RunState(last_head="abc", last_run_time="2024-01-01T00:00:00Z")
        save_run_state(tmp_path, state)
        assert (tmp_path / SIGIL_DIR / RUN_STATE_FILE).exists()


class TestFindings:
    def _make_finding(self, **overrides):
        defaults = {
            "category": "dead_code",
            "file": "foo.py",
            "line": 1,
            "description": "unused import",
            "risk": "low",
            "suggested_fix": "remove it",
            "disposition": "pr",
            "priority": 1,
            "rationale": "easy fix",
        }
        defaults.update(overrides)
        return Finding(**defaults)

    def test_save_and_load(self, tmp_path):
        findings = [
            self._make_finding(),
            self._make_finding(category="security", file="bar.py", priority=2),
        ]
        save_findings(tmp_path, findings)
        loaded = load_previous_findings(tmp_path)
        assert len(loaded) == 2
        assert loaded[0].category == "dead_code"
        assert loaded[0].file == "foo.py"
        assert loaded[1].category == "security"

    def test_load_missing_returns_empty(self, tmp_path):
        assert load_previous_findings(tmp_path) == []

    def test_load_invalid_json_returns_empty(self, tmp_path):
        sigil_dir = tmp_path / SIGIL_DIR
        sigil_dir.mkdir(parents=True)
        (sigil_dir / FINDINGS_FILE).write_text("not json")
        assert load_previous_findings(tmp_path) == []

    def test_round_trip_preserves_all_fields(self, tmp_path):
        finding = self._make_finding(
            implementation_spec="remove the import",
            relevant_files=("foo.py", "bar.py"),
            boldness="bold",
        )
        save_findings(tmp_path, [finding])
        loaded = load_previous_findings(tmp_path)
        assert len(loaded) == 1
        assert loaded[0].implementation_spec == "remove the import"
        assert loaded[0].relevant_files == ("foo.py", "bar.py")
        assert loaded[0].boldness == "bold"

    def test_save_creates_directory(self, tmp_path):
        findings = [self._make_finding()]
        save_findings(tmp_path, findings)
        assert (tmp_path / SIGIL_DIR / FINDINGS_FILE).exists()


class TestAdaptivePlan:
    def test_should_skip_returns_true_for_skipped_stage(self):
        plan = AdaptivePlan(
            decisions=[
                StageDecision(stage="analysis", skip=True, rationale="No changes"),
                StageDecision(stage="ideation", skip=False, rationale="Still run"),
            ],
            changed_files=[],
            last_run_head="abc",
            current_head="def",
        )
        assert plan.should_skip("analysis") is True
        assert plan.should_skip("ideation") is False

    def test_should_skip_returns_false_for_unknown_stage(self):
        plan = AdaptivePlan(
            decisions=[],
            changed_files=[],
            last_run_head=None,
            current_head="abc",
        )
        assert plan.should_skip("unknown_stage") is False

    def test_rationale_for_returns_rationale(self):
        plan = AdaptivePlan(
            decisions=[
                StageDecision(stage="analysis", skip=True, rationale="No code changes"),
            ],
            changed_files=[],
            last_run_head="abc",
            current_head="def",
        )
        assert plan.rationale_for("analysis") == "No code changes"

    def test_rationale_for_returns_none_for_unknown_stage(self):
        plan = AdaptivePlan(
            decisions=[],
            changed_files=[],
            last_run_head=None,
            current_head="abc",
        )
        assert plan.rationale_for("unknown") is None


class TestComputeAdaptivePlan:
    async def test_force_all_returns_no_skip_plan(self, tmp_path):
        config = Config(adaptive_stages=True)
        plan = await compute_adaptive_plan(tmp_path, config, force_all=True)
        assert not plan.should_skip("discovery")
        assert not plan.should_skip("analysis")
        assert not plan.should_skip("ideation")
        assert len(plan.decisions) == 0

    async def test_disabled_returns_no_skip_plan(self, tmp_path):
        config = Config(adaptive_stages=False)
        plan = await compute_adaptive_plan(tmp_path, config, force_all=False)
        assert not plan.should_skip("discovery")
        assert not plan.should_skip("analysis")
        assert not plan.should_skip("ideation")
        assert len(plan.decisions) == 0

    async def test_no_previous_run_returns_no_skip_plan(self, tmp_path):
        config = Config(adaptive_stages=True)
        plan = await compute_adaptive_plan(tmp_path, config, force_all=False)
        assert not plan.should_skip("discovery")
        assert not plan.should_skip("analysis")
        assert not plan.should_skip("ideation")
        assert plan.last_run_head is None

    async def test_no_changes_skips_discovery_and_analysis(self, tmp_path):
        config = Config(adaptive_stages=True)
        head = "abc123def456"
        save_run_state(tmp_path, RunState(last_head=head, last_run_time="2024-01-01T00:00:00Z"))

        with patch("sigil.pipeline.adaptive.get_head", new_callable=AsyncMock, return_value=head):
            with patch(
                "sigil.pipeline.adaptive.arun",
                new_callable=AsyncMock,
                return_value=(0, "", ""),
            ):
                plan = await compute_adaptive_plan(tmp_path, config, force_all=False)

        assert plan.should_skip("discovery") is True
        assert plan.should_skip("analysis") is True
        assert plan.should_skip("ideation") is False
        assert "No files changed" in plan.rationale_for("discovery")

    async def test_docs_only_skips_analysis(self, tmp_path):
        config = Config(adaptive_stages=True)
        save_run_state(tmp_path, RunState(last_head="old", last_run_time="2024-01-01T00:00:00Z"))

        with patch("sigil.pipeline.adaptive.get_head", new_callable=AsyncMock, return_value="new"):
            with patch(
                "sigil.pipeline.adaptive.arun",
                new_callable=AsyncMock,
                return_value=(0, "README.md\nCHANGELOG.md", ""),
            ):
                plan = await compute_adaptive_plan(tmp_path, config, force_all=False)

        assert plan.should_skip("analysis") is True
        assert plan.should_skip("ideation") is False
        assert plan.should_skip("discovery") is False

    async def test_config_only_skips_analysis_and_ideation(self, tmp_path):
        config = Config(adaptive_stages=True)
        save_run_state(tmp_path, RunState(last_head="old", last_run_time="2024-01-01T00:00:00Z"))

        with patch("sigil.pipeline.adaptive.get_head", new_callable=AsyncMock, return_value="new"):
            with patch(
                "sigil.pipeline.adaptive.arun",
                new_callable=AsyncMock,
                return_value=(0, "pyproject.toml\n.sigil/config.yml", ""),
            ):
                plan = await compute_adaptive_plan(tmp_path, config, force_all=False)

        assert plan.should_skip("analysis") is True
        assert plan.should_skip("ideation") is True
        assert plan.should_skip("discovery") is False

    async def test_code_changes_no_skip(self, tmp_path):
        config = Config(adaptive_stages=True)
        save_run_state(tmp_path, RunState(last_head="old", last_run_time="2024-01-01T00:00:00Z"))

        with patch("sigil.pipeline.adaptive.get_head", new_callable=AsyncMock, return_value="new"):
            with patch(
                "sigil.pipeline.adaptive.arun",
                new_callable=AsyncMock,
                return_value=(0, "src/app.py\nsrc/lib.rs", ""),
            ):
                plan = await compute_adaptive_plan(tmp_path, config, force_all=False)

        assert plan.should_skip("analysis") is False
        assert plan.should_skip("ideation") is False
        assert plan.should_skip("discovery") is False
        assert "src/app.py" in plan.changed_files

    async def test_git_diff_failure_falls_back(self, tmp_path):
        config = Config(adaptive_stages=True)
        save_run_state(tmp_path, RunState(last_head="old", last_run_time="2024-01-01T00:00:00Z"))

        with patch("sigil.pipeline.adaptive.get_head", new_callable=AsyncMock, return_value="new"):
            with patch(
                "sigil.pipeline.adaptive.arun",
                new_callable=AsyncMock,
                return_value=(1, "", "error"),
            ):
                plan = await compute_adaptive_plan(tmp_path, config, force_all=False)

        assert plan.should_skip("analysis") is False
        assert plan.should_skip("ideation") is False
        assert plan.changed_files == []

    async def test_mixed_changes_no_skip(self, tmp_path):
        config = Config(adaptive_stages=True)
        save_run_state(tmp_path, RunState(last_head="old", last_run_time="2024-01-01T00:00:00Z"))

        with patch("sigil.pipeline.adaptive.get_head", new_callable=AsyncMock, return_value="new"):
            with patch(
                "sigil.pipeline.adaptive.arun",
                new_callable=AsyncMock,
                return_value=(0, "README.md\npyproject.toml\nsrc/app.py", ""),
            ):
                plan = await compute_adaptive_plan(tmp_path, config, force_all=False)

        assert plan.should_skip("analysis") is False
        assert plan.should_skip("ideation") is False
