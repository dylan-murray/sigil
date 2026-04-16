import json
from sigil.pipeline.cost_tracker import load_cost_tracker
from sigil.state.attempts import AttemptRecord, log_attempt


def _make_record(category="dead_code", outcome="success", cost_usd=0.1, **kwargs):
    return AttemptRecord(
        run_id="run1",
        timestamp="2026-01-01T00:00:00Z",
        item_type="finding",
        item_id="id1",
        category=category,
        complexity="small",
        approach="fix",
        model="gpt-4o",
        retries=0,
        outcome=outcome,
        tokens_used=1000,
        duration_s=1.0,
        failure_detail="",
        cost_usd=cost_usd,
        **kwargs,
    )


def test_cost_tracker_aggregates(tmp_path):
    # Category A: 2 attempts, 1 success, total cost 0.2, avg 0.1, rate 50%
    log_attempt(tmp_path, _make_record(category="A", outcome="success", cost_usd=0.1))
    log_attempt(tmp_path, _make_record(category="A", outcome="failure", cost_usd=0.1))

    # Category B: 1 attempt, 1 success, total cost 0.05, avg 0.05, rate 100%
    log_attempt(tmp_path, _make_record(category="B", outcome="success", cost_usd=0.05))

    # Category C: 1 attempt, 0 success, total cost 0.5, avg 0.5, rate 0%
    log_attempt(tmp_path, _make_record(category="C", outcome="failure", cost_usd=0.5))

    tracker = load_cost_tracker(tmp_path)
    stats = tracker.by_category()

    assert stats["A"].attempts == 2
    assert stats["A"].successes == 1
    assert stats["A"].avg_cost == 0.1
    assert stats["A"].success_rate == 0.5

    assert stats["B"].success_rate == 1.0
    assert stats["B"].avg_cost == 0.05

    assert stats["C"].success_rate == 0.0
    assert stats["C"].avg_cost == 0.5


def test_efficiency_ranking(tmp_path):
    # B is most efficient (100% / 0.05 = 20)
    # A is middle (50% / 0.1 = 5)
    # C is least (0% / 0.5 = 0)
    log_attempt(tmp_path, _make_record(category="A", outcome="success", cost_usd=0.1))
    log_attempt(tmp_path, _make_record(category="A", outcome="failure", cost_usd=0.1))
    log_attempt(tmp_path, _make_record(category="B", outcome="success", cost_usd=0.05))
    log_attempt(tmp_path, _make_record(category="C", outcome="failure", cost_usd=0.5))

    tracker = load_cost_tracker(tmp_path)
    ranked = tracker.efficiency_ranking()

    assert ranked[0].category == "B"
    assert ranked[1].category == "A"
    assert ranked[2].category == "C"


def test_analyze_insights(tmp_path):
    # High success, low cost
    log_attempt(tmp_path, _make_record(category="Efficient", outcome="success", cost_usd=0.01))
    # Low success, high cost
    log_attempt(tmp_path, _make_record(category="Wasteful", outcome="failure", cost_usd=1.0))
    log_attempt(tmp_path, _make_record(category="Wasteful", outcome="failure", cost_usd=1.0))

    tracker = load_cost_tracker(tmp_path)
    insights = tracker.analyze()

    assert "Efficient" in insights.low_cost_high_success
    assert "Wasteful" in insights.high_cost_low_success
    assert "Prioritize Efficient" in insights.summary
    assert "Avoid/Refine Wasteful" in insights.summary


def test_empty_tracker(tmp_path):
    tracker = load_cost_tracker(tmp_path)
    assert tracker.by_category() == {}
    insights = tracker.analyze()
    assert insights.total_spend == 0.0
    assert insights.summary == ""


def test_backward_compatibility(tmp_path):
    # Manually write a record without cost_usd
    path = tmp_path / ".sigil" / "attempts.jsonl"
    path.parent.mkdir(parents=True)
    record = {
        "run_id": "run1",
        "timestamp": "t",
        "item_type": "finding",
        "item_id": "id1",
        "category": "A",
        "complexity": "s",
        "approach": "a",
        "model": "m",
        "retries": 0,
        "outcome": "success",
        "tokens_used": 100,
        "duration_s": 1.0,
        "failure_detail": "",
    }
    path.write_text(json.dumps(record) + "\n")

    tracker = load_cost_tracker(tmp_path)
    stats = tracker.by_category()
    assert stats["A"].avg_cost == 0.0
