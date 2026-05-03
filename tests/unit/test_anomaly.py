import pytest

from sigil.pipeline.anomaly import (
    CategoryStats,
    compute_category_stats,
    detect_anomalies,
)
from sigil.pipeline.maintenance import Finding
from sigil.pipeline.ideation import FeatureIdea
from sigil.pipeline.models import ExecutionResult, FailureType


def _make_finding(category: str, file: str = "a.py") -> Finding:
    return Finding(
        category=category,
        file=file,
        line=None,
        description="test",
        risk="low",
        suggested_fix="fix it",
        disposition="pr",
        priority=1,
        rationale="test",
    )


def _make_idea(complexity: str = "medium") -> FeatureIdea:
    return FeatureIdea(
        title="test idea",
        description="test",
        rationale="test",
        complexity=complexity,
        disposition="pr",
        priority=1,
    )


def _make_result(
    success: bool = True,
    retries: int = 0,
    failure_type: FailureType | None = None,
) -> ExecutionResult:
    return ExecutionResult(
        success=success,
        diff="diff" if success else "",
        hooks_passed=success,
        failed_hook=None,
        retries=retries,
        failure_reason=None if success else "failed",
        failure_type=failure_type,
    )


def test_compute_category_stats_groups_findings_by_category():
    items = [
        (_make_finding("dead_code", "a.py"), _make_result(success=True), "b1"),
        (
            _make_finding("dead_code", "b.py"),
            _make_result(success=False, failure_type=FailureType.POST_HOOK),
            "b2",
        ),
        (_make_finding("type_error", "c.py"), _make_result(success=True), "b3"),
    ]
    stats = compute_category_stats(items)
    assert len(stats) == 2
    by_cat = {s.category: s for s in stats}
    assert by_cat["dead_code"].total == 2
    assert by_cat["dead_code"].succeeded == 1
    assert by_cat["dead_code"].failed == 1
    assert by_cat["type_error"].total == 1
    assert by_cat["type_error"].succeeded == 1


def test_compute_category_stats_groups_ideas_by_complexity():
    items = [
        (_make_idea("low"), _make_result(success=True), "b1"),
        (
            _make_idea("medium"),
            _make_result(success=False, failure_type=FailureType.NO_CHANGES),
            "b2",
        ),
        (_make_idea("low"), _make_result(success=True, retries=3), "b3"),
    ]
    stats = compute_category_stats(items)
    assert len(stats) == 2
    by_cat = {s.category: s for s in stats}
    assert by_cat["feature:low"].total == 2
    assert by_cat["feature:low"].succeeded == 2
    assert by_cat["feature:low"].high_retry_count == 1
    assert by_cat["feature:medium"].total == 1
    assert by_cat["feature:medium"].failed == 1


def test_compute_category_stats_empty():
    assert compute_category_stats([]) == []


def test_compute_category_stats_returns_all_groups():
    items = [
        (_make_finding("dead_code", "a.py"), _make_result(success=True), "b1"),
        (_make_finding("dead_code", "b.py"), _make_result(success=True), "b2"),
        (_make_finding("type_error", "c.py"), _make_result(success=True), "b3"),
    ]
    stats = compute_category_stats(items)
    assert len(stats) == 2
    categories = {s.category for s in stats}
    assert categories == {"dead_code", "type_error"}


def test_compute_category_stats_avg_retries():
    items = [
        (_make_finding("dead_code", "a.py"), _make_result(success=True, retries=0), "b1"),
        (_make_finding("dead_code", "b.py"), _make_result(success=True, retries=2), "b2"),
        (_make_finding("dead_code", "c.py"), _make_result(success=True, retries=4), "b3"),
    ]
    stats = compute_category_stats(items)
    assert len(stats) == 1
    assert stats[0].avg_retries == pytest.approx(2.0)


def test_compute_category_stats_failure_type_breakdown():
    items = [
        (
            _make_finding("dead_code", "a.py"),
            _make_result(success=False, failure_type=FailureType.POST_HOOK),
            "b1",
        ),
        (
            _make_finding("dead_code", "b.py"),
            _make_result(success=False, failure_type=FailureType.POST_HOOK),
            "b2",
        ),
        (
            _make_finding("dead_code", "c.py"),
            _make_result(success=False, failure_type=FailureType.NO_CHANGES),
            "b3",
        ),
    ]
    stats = compute_category_stats(items)
    assert len(stats) == 1
    assert stats[0].failure_types == {"post_hook": 2, "no_changes": 1}


def test_detect_anomalies_high_retry_rate():
    stats = [
        CategoryStats(
            category="dead_code",
            total=5,
            succeeded=3,
            failed=2,
            avg_retries=1.8,
            high_retry_count=4,
            failure_types={},
        )
    ]
    anomalies = detect_anomalies(stats, total_ideas=0, approved_ideas=0)
    messages = [a.message for a in anomalies]
    assert any("retries" in m.lower() for m in messages)
    assert any("80%" in m for m in messages)


def test_detect_anomalies_low_success_rate():
    stats = [
        CategoryStats(
            category="type_error",
            total=5,
            succeeded=1,
            failed=4,
            avg_retries=0.5,
            high_retry_count=0,
            failure_types={},
        )
    ]
    anomalies = detect_anomalies(stats, total_ideas=0, approved_ideas=0)
    messages = [a.message for a in anomalies]
    assert any("success" in m.lower() for m in messages)
    assert any("20%" in m for m in messages)


def test_detect_anomalies_feature_approval_low():
    stats = []
    anomalies = detect_anomalies(stats, total_ideas=10, approved_ideas=0)
    messages = [a.message for a in anomalies]
    assert any("approval" in m.lower() for m in messages)


def test_detect_anomalies_feature_approval_high():
    stats = []
    anomalies = detect_anomalies(stats, total_ideas=10, approved_ideas=5)
    messages = [a.message for a in anomalies]
    assert any("approval rate" in m.lower() for m in messages)
    assert any("50%" in m for m in messages)


def test_detect_anomalies_dominant_failure_type():
    stats = [
        CategoryStats(
            category="dead_code",
            total=5,
            succeeded=1,
            failed=4,
            avg_retries=0.5,
            high_retry_count=0,
            failure_types={"post_hook": 4},
        )
    ]
    anomalies = detect_anomalies(stats, total_ideas=0, approved_ideas=0)
    messages = [a.message for a in anomalies]
    assert any("post_hook" in m.lower() for m in messages)
    assert any("100%" in m for m in messages)


def test_detect_anomalies_no_anomalies():
    stats = [
        CategoryStats(
            category="dead_code",
            total=5,
            succeeded=4,
            failed=1,
            avg_retries=0.2,
            high_retry_count=1,
            failure_types={},
        )
    ]
    anomalies = detect_anomalies(stats, total_ideas=10, approved_ideas=3)
    assert anomalies == []


def test_detect_anomalies_empty_results():
    anomalies = detect_anomalies([], total_ideas=0, approved_ideas=0)
    assert anomalies == []


def test_detect_anomalies_none_failure_type_handled():
    items = [
        (_make_finding("dead_code", "a.py"), _make_result(success=False, failure_type=None), "b1"),
        (_make_finding("dead_code", "b.py"), _make_result(success=False, failure_type=None), "b2"),
        (_make_finding("dead_code", "c.py"), _make_result(success=True), "b3"),
    ]
    stats = compute_category_stats(items)
    assert len(stats) == 1
    assert stats[0].failure_types == {}
    assert stats[0].failed == 2


def test_detect_anomalies_severity():
    stats = [
        CategoryStats(
            category="dead_code",
            total=5,
            succeeded=0,
            failed=5,
            avg_retries=3.0,
            high_retry_count=5,
            failure_types={"post_hook": 5},
        )
    ]
    anomalies = detect_anomalies(stats, total_ideas=0, approved_ideas=0)
    severities = {a.severity for a in anomalies}
    assert "warning" in severities


def test_detect_anomalies_skips_small_groups():
    stats = [
        CategoryStats(
            category="dead_code",
            total=2,
            succeeded=0,
            failed=2,
            avg_retries=3.0,
            high_retry_count=2,
            failure_types={"post_hook": 2},
        ),
    ]
    anomalies = detect_anomalies(stats, total_ideas=0, approved_ideas=0)
    assert anomalies == []


def test_detect_anomalies_feature_approval_edge_cases():
    anomalies = detect_anomalies([], total_ideas=0, approved_ideas=0)
    assert anomalies == []

    anomalies = detect_anomalies([], total_ideas=5, approved_ideas=1)
    messages = [a.message for a in anomalies]
    assert not any("approval" in m.lower() for m in messages)
