import json

import pytest

from sigil.core.llm import (
    CallTrace,
    get_run_report_path,
    reset_traces,
    reset_usage,
    write_run_report,
    _traces,
)


@pytest.fixture(autouse=True)
def _clean_traces():
    reset_traces()
    reset_usage()
    yield
    _traces.clear()


def _make_trace(
    label: str,
    model: str = "anthropic/claude-sonnet-4-6",
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    cost_usd: float = 0.01,
    task: str | None = None,
) -> CallTrace:
    return CallTrace(
        timestamp="2025-01-01T00:00:00Z",
        label=label,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        cost_usd=cost_usd,
        task=task,
    )


def test_write_run_report_happy_path(tmp_path):
    _traces.extend(
        [
            _make_trace(
                "fix-types:architect",
                prompt_tokens=500,
                completion_tokens=100,
                cost_usd=0.05,
                task="fix-types",
            ),
            _make_trace(
                "fix-types:engineer",
                prompt_tokens=2000,
                completion_tokens=500,
                cost_usd=0.20,
                task="fix-types",
            ),
            _make_trace(
                "add-retry:architect",
                prompt_tokens=400,
                completion_tokens=80,
                cost_usd=0.04,
                task="add-retry",
            ),
            _make_trace(
                "add-retry:engineer",
                prompt_tokens=1500,
                completion_tokens=300,
                cost_usd=0.15,
                task="add-retry",
            ),
        ]
    )

    result = write_run_report(tmp_path, run_id="abc123def456")
    assert result is not None

    data = json.loads(result.read_text())
    assert data["run_id"] == "abc123def456"
    assert "started_at" in data
    assert data["aggregate"]["prompt_tokens"] == 4400
    assert data["aggregate"]["completion_tokens"] == 980
    assert data["aggregate"]["cost_usd"] == pytest.approx(0.44)

    assert "fix-types" in data["items"]
    assert "add-retry" in data["items"]

    fix_types = data["items"]["fix-types"]
    assert fix_types["prompt_tokens"] == 2500
    assert fix_types["completion_tokens"] == 600
    assert fix_types["cost_usd"] == pytest.approx(0.25)
    assert "architect" in fix_types["stages"]
    assert "engineer" in fix_types["stages"]
    assert fix_types["stages"]["architect"]["prompt_tokens"] == 500
    assert fix_types["stages"]["engineer"]["prompt_tokens"] == 2000


def test_write_run_report_pipeline_traces_grouped(tmp_path):
    _traces.extend(
        [
            _make_trace("discovery", prompt_tokens=300, cost_usd=0.03, task=None),
            _make_trace("ideation", prompt_tokens=600, cost_usd=0.06, task=None),
            _make_trace("fix-types:architect", prompt_tokens=500, cost_usd=0.05, task="fix-types"),
        ]
    )

    result = write_run_report(tmp_path, run_id="run001")
    assert result is not None

    data = json.loads(result.read_text())
    assert "_pipeline" in data["items"]
    assert "fix-types" in data["items"]

    pipeline = data["items"]["_pipeline"]
    assert pipeline["prompt_tokens"] == 900
    assert pipeline["cost_usd"] == pytest.approx(0.09)
    assert "discovery" in pipeline["stages"]
    assert "ideation" in pipeline["stages"]


def test_write_run_report_stage_extraction(tmp_path):
    _traces.extend(
        [
            _make_trace("fix-types:architect", prompt_tokens=100, task="fix-types"),
            _make_trace("fix-types:engineer", prompt_tokens=200, task="fix-types"),
            _make_trace("fix-types:engineer:summary", prompt_tokens=50, task="fix-types"),
            _make_trace("fix-types:hook_summarizer", prompt_tokens=30, task="fix-types"),
        ]
    )

    result = write_run_report(tmp_path, run_id="run002")
    data = json.loads(result.read_text())

    stages = data["items"]["fix-types"]["stages"]
    assert "architect" in stages
    assert "engineer" in stages
    assert "engineer:summary" in stages
    assert "hook_summarizer" in stages
    assert stages["architect"]["prompt_tokens"] == 100
    assert stages["engineer"]["prompt_tokens"] == 200
    assert stages["engineer:summary"]["prompt_tokens"] == 50
    assert stages["hook_summarizer"]["prompt_tokens"] == 30


def test_write_run_report_empty_traces(tmp_path):
    result = write_run_report(tmp_path, run_id="empty_run")
    assert result is None


def test_write_run_report_json_structure(tmp_path):
    _traces.extend(
        [
            _make_trace(
                "fix-types:architect",
                model="anthropic/claude-sonnet-4-6",
                prompt_tokens=500,
                completion_tokens=100,
                cost_usd=0.05,
                task="fix-types",
            ),
        ]
    )

    result = write_run_report(tmp_path, run_id="struct001")
    data = json.loads(result.read_text())

    assert "run_id" in data
    assert "started_at" in data
    assert "aggregate" in data
    assert "items" in data

    agg = data["aggregate"]
    assert "prompt_tokens" in agg
    assert "completion_tokens" in agg
    assert "cost_usd" in agg
    assert "models" in agg

    item = data["items"]["fix-types"]
    assert "prompt_tokens" in item
    assert "completion_tokens" in item
    assert "cost_usd" in item
    assert "models" in item
    assert "stages" in item


def test_write_run_report_per_model_breakdown(tmp_path):
    _traces.extend(
        [
            _make_trace(
                "fix-types:architect",
                model="anthropic/claude-sonnet-4-6",
                prompt_tokens=500,
                cost_usd=0.05,
                task="fix-types",
            ),
            _make_trace(
                "fix-types:engineer",
                model="google/gemini-2.5-pro",
                prompt_tokens=1000,
                cost_usd=0.10,
                task="fix-types",
            ),
        ]
    )

    result = write_run_report(tmp_path, run_id="model001")
    data = json.loads(result.read_text())

    models = data["items"]["fix-types"]["models"]
    assert "anthropic/claude-sonnet-4-6" in models
    assert "google/gemini-2.5-pro" in models
    assert models["anthropic/claude-sonnet-4-6"]["prompt_tokens"] == 500
    assert models["google/gemini-2.5-pro"]["prompt_tokens"] == 1000

    agg_models = data["aggregate"]["models"]
    assert "anthropic/claude-sonnet-4-6" in agg_models
    assert "google/gemini-2.5-pro" in agg_models


def test_write_run_report_item_titles(tmp_path):
    _traces.extend(
        [
            _make_trace("fix-types:architect", prompt_tokens=500, task="fix-types"),
        ]
    )

    item_titles = {"fix-types": "Fix type hints in utils.py"}
    result = write_run_report(tmp_path, run_id="title001", item_titles=item_titles)
    data = json.loads(result.read_text())

    assert data["items"]["fix-types"]["title"] == "Fix type hints in utils.py"


def test_write_run_report_item_titles_missing_slug(tmp_path):
    _traces.extend(
        [
            _make_trace("fix-types:architect", prompt_tokens=500, task="fix-types"),
        ]
    )

    item_titles = {"other-slug": "Other item"}
    result = write_run_report(tmp_path, run_id="notitle001", item_titles=item_titles)
    data = json.loads(result.read_text())

    assert "title" not in data["items"]["fix-types"]


def test_write_run_report_creates_reports_directory(tmp_path):
    _traces.extend(
        [
            _make_trace("test:architect", prompt_tokens=100, task="test"),
        ]
    )

    result = write_run_report(tmp_path, run_id="dir001")
    assert result is not None
    assert (tmp_path / ".sigil" / "reports").is_dir()
    assert result == tmp_path / ".sigil" / "reports" / "dir001.json"


def test_get_run_report_path():
    from pathlib import Path

    path = get_run_report_path(Path("/repo"), "run123")
    assert path == Path("/repo/.sigil/reports/run123.json")


def test_write_run_report_aggregate_matches_sum(tmp_path):
    _traces.extend(
        [
            _make_trace(
                "item-a:architect",
                prompt_tokens=100,
                completion_tokens=20,
                cost_usd=0.01,
                task="item-a",
            ),
            _make_trace(
                "item-a:engineer",
                prompt_tokens=200,
                completion_tokens=40,
                cost_usd=0.02,
                task="item-a",
            ),
            _make_trace(
                "item-b:architect",
                prompt_tokens=300,
                completion_tokens=60,
                cost_usd=0.03,
                task="item-b",
            ),
            _make_trace(
                "discovery", prompt_tokens=50, completion_tokens=10, cost_usd=0.005, task=None
            ),
        ]
    )

    result = write_run_report(tmp_path, run_id="agg001")
    data = json.loads(result.read_text())

    agg = data["aggregate"]
    assert agg["prompt_tokens"] == 650
    assert agg["completion_tokens"] == 130
    assert agg["cost_usd"] == pytest.approx(0.065)

    item_total_cost = sum(v["cost_usd"] for v in data["items"].values())
    assert item_total_cost == pytest.approx(agg["cost_usd"])


def test_write_run_report_pipeline_stage_labels(tmp_path):
    _traces.extend(
        [
            _make_trace("discovery", prompt_tokens=100, task=None),
            _make_trace("ideation", prompt_tokens=200, task=None),
            _make_trace("validation", prompt_tokens=150, task=None),
        ]
    )

    result = write_run_report(tmp_path, run_id="pipe001")
    data = json.loads(result.read_text())

    pipeline = data["items"]["_pipeline"]
    assert "discovery" in pipeline["stages"]
    assert "ideation" in pipeline["stages"]
    assert "validation" in pipeline["stages"]
    assert pipeline["stages"]["discovery"]["prompt_tokens"] == 100
    assert pipeline["stages"]["ideation"]["prompt_tokens"] == 200
    assert pipeline["stages"]["validation"]["prompt_tokens"] == 150
