import json
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.table import Table

from sigil.core.config import Config
from sigil.state.performance import (
    BASELINE_FILE,
    PERF_FILE,
    PerfBaseline,
    PerfTracker,
    RunPerf,
    StagePerf,
    check_deviations,
    compute_baselines,
    config_hash,
    format_perf_table,
    log_perf_run,
    prune_perf_runs,
    read_perf_runs,
    write_baseline_markdown,
)


def _make_stage(
    stage: str = "discovery", duration_s: float = 1.0, tokens: int = 100, llm_calls: int = 1
) -> StagePerf:
    return StagePerf(stage=stage, duration_s=duration_s, tokens=tokens, llm_calls=llm_calls)


def _make_run(
    run_id: str = "r1",
    config_hash: str = "abc",
    stages: list[StagePerf] | None = None,
    timestamp: str = "2026-01-01T00:00:00Z",
) -> RunPerf:
    return RunPerf(run_id=run_id, timestamp=timestamp, config_hash=config_hash, stages=stages or [])


def _write_perf_jsonl(repo: Path, runs: list[RunPerf]) -> None:
    path = repo / ".sigil" / PERF_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            json.loads(
                json.dumps(
                    {
                        "run_id": r.run_id,
                        "timestamp": r.timestamp,
                        "config_hash": r.config_hash,
                        "stages": [
                            {
                                "stage": s.stage,
                                "duration_s": s.duration_s,
                                "tokens": s.tokens,
                                "llm_calls": s.llm_calls,
                            }
                            for s in r.stages
                        ],
                    }
                )
            )
        )
        for r in runs
    ]
    path.write_text("\n".join(lines) + "\n")


class TestConfigHash:
    def test_config_hash_stability(self):
        config = Config(
            model="anthropic/claude-sonnet-4-6", boldness="balanced", focus=("tests", "security")
        )
        h1 = config_hash(config)
        h2 = config_hash(config)
        assert h1 == h2

    def test_config_hash_changes_on_model_change(self):
        c1 = Config(model="anthropic/claude-sonnet-4-6")
        c2 = Config(model="openai/gpt-4o")
        assert config_hash(c1) != config_hash(c2)

    def test_config_hash_changes_on_focus_change(self):
        c1 = Config(focus=("tests",))
        c2 = Config(focus=("tests", "security"))
        assert config_hash(c1) != config_hash(c2)

    def test_config_hash_changes_on_boldness_change(self):
        c1 = Config(boldness="conservative")
        c2 = Config(boldness="bold")
        assert config_hash(c1) != config_hash(c2)

    def test_config_hash_changes_on_agents_change(self):
        c1 = Config()
        c2 = Config(agents={"ideator": {"model": "openai/gpt-4o"}})
        assert config_hash(c1) != config_hash(c2)

    def test_config_hash_ignores_non_perf_fields(self):
        c1 = Config(model="m1", max_spend_usd=10.0)
        c2 = Config(model="m1", max_spend_usd=100.0)
        assert config_hash(c1) == config_hash(c2)

    def test_config_hash_focus_order_invariant(self):
        c1 = Config(focus=("security", "tests"))
        c2 = Config(focus=("tests", "security"))
        assert config_hash(c1) == config_hash(c2)


class TestLogAndReadPerfRuns:
    def test_log_and_read_roundtrip(self, tmp_path):
        stages = [_make_stage("discovery", 1.5, 200, 2)]
        run = _make_run(stages=stages)
        log_perf_run(tmp_path, run)

        results = read_perf_runs(tmp_path, run.config_hash)
        assert len(results) == 1
        assert results[0].run_id == run.run_id
        assert len(results[0].stages) == 1
        assert results[0].stages[0].stage == "discovery"
        assert results[0].stages[0].duration_s == 1.5

    def test_read_filters_by_config_hash(self, tmp_path):
        r1 = _make_run(run_id="r1", config_hash="hash_a", stages=[_make_stage("discovery")])
        r2 = _make_run(run_id="r2", config_hash="hash_b", stages=[_make_stage("discovery")])
        log_perf_run(tmp_path, r1)
        log_perf_run(tmp_path, r2)

        results = read_perf_runs(tmp_path, "hash_a")
        assert len(results) == 1
        assert results[0].run_id == "r1"

    def test_read_respects_limit(self, tmp_path):
        for i in range(10):
            log_perf_run(
                tmp_path, _make_run(run_id=f"r{i}", config_hash="h", stages=[_make_stage()])
            )
        results = read_perf_runs(tmp_path, "h", limit=3)
        assert len(results) == 3

    def test_read_returns_most_recent_last(self, tmp_path):
        for i in range(5):
            log_perf_run(
                tmp_path, _make_run(run_id=f"r{i}", config_hash="h", stages=[_make_stage()])
            )
        results = read_perf_runs(tmp_path, "h", limit=5)
        assert results[0].run_id == "r0"
        assert results[4].run_id == "r4"

    def test_log_creates_directory(self, tmp_path):
        run = _make_run()
        log_perf_run(tmp_path, run)
        assert (tmp_path / ".sigil" / PERF_FILE).exists()

    def test_read_empty_dir(self, tmp_path):
        results = read_perf_runs(tmp_path, "any")
        assert results == []


class TestPrunePerfRuns:
    def test_prune_under_limit(self, tmp_path):
        for i in range(10):
            log_perf_run(tmp_path, _make_run(run_id=f"r{i}"))
        pruned = prune_perf_runs(tmp_path)
        assert pruned == 0

    def test_prune_over_limit(self, tmp_path):
        from sigil.state.performance import MAX_PERF_RUNS

        for i in range(MAX_PERF_RUNS + 50):
            log_perf_run(tmp_path, _make_run(run_id=f"r{i}"))
        pruned = prune_perf_runs(tmp_path)
        assert pruned == 50

    def test_prune_nonexistent(self, tmp_path):
        assert prune_perf_runs(tmp_path) == 0


class TestComputeBaselines:
    def test_compute_baselines_median(self):
        runs = []
        for i, dur in enumerate([1.0, 2.0, 3.0, 4.0, 5.0]):
            runs.append(
                _make_run(
                    run_id=f"r{i}",
                    stages=[
                        _make_stage(
                            "discovery", duration_s=dur, tokens=100 * (i + 1), llm_calls=i + 1
                        )
                    ],
                )
            )
        baselines = compute_baselines(runs)
        assert "discovery" in baselines
        assert baselines["discovery"].median_duration_s == 3.0
        assert baselines["discovery"].median_tokens == 300.0
        assert baselines["discovery"].median_calls == 3.0

    def test_compute_baselines_empty(self):
        assert compute_baselines([]) == {}

    def test_compute_baselines_multiple_stages(self):
        runs = [
            _make_run(
                run_id="r1",
                stages=[
                    _make_stage("discovery", duration_s=2.0),
                    _make_stage("validation", duration_s=5.0),
                ],
            ),
            _make_run(
                run_id="r2",
                stages=[
                    _make_stage("discovery", duration_s=4.0),
                    _make_stage("validation", duration_s=7.0),
                ],
            ),
        ]
        baselines = compute_baselines(runs)
        assert baselines["discovery"].median_duration_s == 3.0
        assert baselines["validation"].median_duration_s == 6.0


class TestCheckDeviations:
    def test_check_deviations_warning_duration_2x(self):
        run = _make_run(stages=[_make_stage("discovery", duration_s=10.0)])
        baselines = {"discovery": PerfBaseline("discovery", 4.0, 100.0, 1.0)}
        deviations = check_deviations(run, baselines)
        assert len(deviations) == 1
        assert deviations[0].severity == "warning"
        assert deviations[0].metric == "duration_s"
        assert deviations[0].ratio == pytest.approx(2.5)

    def test_check_deviations_issue_duration_5x(self):
        run = _make_run(stages=[_make_stage("discovery", duration_s=25.0)])
        baselines = {"discovery": PerfBaseline("discovery", 4.0, 100.0, 1.0)}
        deviations = check_deviations(run, baselines)
        assert len(deviations) == 1
        assert deviations[0].severity == "issue"
        assert deviations[0].ratio == pytest.approx(6.25)

    def test_check_deviations_tokens_warning(self):
        run = _make_run(stages=[_make_stage("discovery", tokens=200)])
        baselines = {"discovery": PerfBaseline("discovery", 1.0, 100.0, 1.0)}
        deviations = check_deviations(run, baselines)
        token_devs = [d for d in deviations if d.metric == "tokens"]
        assert len(token_devs) == 1
        assert token_devs[0].severity == "warning"

    def test_check_deviations_calls_warning(self):
        run = _make_run(stages=[_make_stage("discovery", llm_calls=10)])
        baselines = {"discovery": PerfBaseline("discovery", 1.0, 100.0, 3.0)}
        deviations = check_deviations(run, baselines)
        call_devs = [d for d in deviations if d.metric == "llm_calls"]
        assert len(call_devs) == 1
        assert call_devs[0].severity == "warning"

    def test_check_deviations_no_baseline(self):
        run = _make_run(stages=[_make_stage("discovery", duration_s=10.0)])
        deviations = check_deviations(run, {})
        assert deviations == []

    def test_check_deviations_within_normal(self):
        run = _make_run(stages=[_make_stage("discovery", duration_s=1.5, tokens=110, llm_calls=2)])
        baselines = {"discovery": PerfBaseline("discovery", 1.0, 100.0, 2.0)}
        deviations = check_deviations(run, baselines)
        assert deviations == []


class TestFormatPerfTable:
    def test_format_perf_table_renders(self):
        run = _make_run(
            stages=[
                _make_stage("discovery", duration_s=2.5, tokens=500, llm_calls=3),
                _make_stage("validation", duration_s=5.0, tokens=1000, llm_calls=5),
            ]
        )
        baselines = {
            "discovery": PerfBaseline("discovery", 2.0, 400.0, 2.0),
        }
        deviations = check_deviations(run, baselines)
        table = format_perf_table(run, baselines, deviations)
        assert isinstance(table, Table)

    def test_format_perf_table_no_baselines(self):
        run = _make_run(stages=[_make_stage("discovery", duration_s=2.5)])
        table = format_perf_table(run, {}, [])
        assert isinstance(table, Table)


class TestWriteBaselineMarkdown:
    def test_write_baseline_markdown(self, tmp_path):
        baselines = {
            "discovery": PerfBaseline("discovery", 2.5, 500.0, 3.0),
            "validation": PerfBaseline("validation", 5.0, 1000.0, 5.0),
        }
        write_baseline_markdown(tmp_path, baselines)
        path = tmp_path / ".sigil" / "memory" / BASELINE_FILE
        assert path.exists()
        content = path.read_text()
        assert content.startswith("---")
        assert "discovery" in content
        assert "validation" in content

    def test_write_baseline_markdown_empty(self, tmp_path):
        write_baseline_markdown(tmp_path, {})
        path = tmp_path / ".sigil" / "memory" / BASELINE_FILE
        assert path.exists()
        content = path.read_text()
        assert "No baseline data" in content


class TestPerfTracker:
    def test_tracker_stage_timing(self):
        tracker = PerfTracker()
        with patch("sigil.state.performance.get_usage_snapshot", return_value=(0, 0, 0.0)):
            tracker.start_stage("discovery")
        with patch("sigil.state.performance.get_usage_snapshot", return_value=(2, 500, 0.01)):
            tracker.finish_stage("discovery")

        run = tracker.build_run_perf("r1", "abc", "2026-01-01T00:00:00Z")
        assert len(run.stages) == 1
        assert run.stages[0].stage == "discovery"
        assert run.stages[0].tokens == 500
        assert run.stages[0].llm_calls == 2

    def test_tracker_multiple_stages(self):
        tracker = PerfTracker()
        with patch("sigil.state.performance.get_usage_snapshot", return_value=(0, 0, 0.0)):
            tracker.start_stage("discovery")
        with patch("sigil.state.performance.get_usage_snapshot", return_value=(2, 500, 0.01)):
            tracker.finish_stage("discovery")
        with patch("sigil.state.performance.get_usage_snapshot", return_value=(2, 500, 0.01)):
            tracker.start_stage("validation")
        with patch("sigil.state.performance.get_usage_snapshot", return_value=(5, 1200, 0.03)):
            tracker.finish_stage("validation")

        run = tracker.build_run_perf("r1", "abc", "2026-01-01T00:00:00Z")
        assert len(run.stages) == 2
        assert run.stages[0].stage == "discovery"
        assert run.stages[0].tokens == 500
        assert run.stages[1].stage == "validation"
        assert run.stages[1].tokens == 700
        assert run.stages[1].llm_calls == 3

    def test_tracker_finish_nonexistent_stage(self):
        tracker = PerfTracker()
        tracker.finish_stage("nonexistent")
        run = tracker.build_run_perf("r1", "abc", "2026-01-01T00:00:00Z")
        assert len(run.stages) == 0
