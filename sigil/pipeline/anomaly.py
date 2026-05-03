from dataclasses import dataclass

from sigil.pipeline.ideation import FeatureIdea
from sigil.pipeline.maintenance import Finding
from sigil.pipeline.models import ExecutionResult
from sigil.state.chronic import WorkItem

MIN_CATEGORY_SIZE = 3

BASELINES: dict[str, float] = {
    "high_retry_rate": 0.30,
    "low_success_rate": 0.50,
    "feature_approval_low": 0.20,
    "feature_approval_high": 0.40,
    "dominant_failure_type": 0.50,
}

SUGGESTIONS: dict[str, str] = {
    "high_retry_rate": "may indicate the analysis stage is producing low-quality specs — review validation criteria",
    "low_success_rate": "consider tightening validation filters or improving implementation specs",
    "feature_approval_low": "ideation may be producing low-quality or overly ambitious proposals — adjust ideation prompts",
    "feature_approval_high": "validation may be too permissive — review approval criteria for feature ideas",
    "dominant_failure_type": "investigate the root cause of repeated {failure_type} failures in this category",
}


@dataclass(frozen=True)
class CategoryStats:
    category: str
    total: int
    succeeded: int
    failed: int
    avg_retries: float
    high_retry_count: int
    failure_types: dict[str, int]


@dataclass(frozen=True)
class Anomaly:
    message: str
    severity: str
    suggestion: str


def compute_category_stats(
    results: list[tuple[WorkItem, ExecutionResult, str]],
) -> list[CategoryStats]:
    buckets: dict[str, list[ExecutionResult]] = {}
    for item, result, _ in results:
        if isinstance(item, Finding):
            key = item.category
        elif isinstance(item, FeatureIdea):
            key = f"feature:{item.complexity}"
        else:
            continue
        buckets.setdefault(key, []).append(result)

    stats: list[CategoryStats] = []
    for category, exec_results in sorted(buckets.items()):
        total = len(exec_results)
        succeeded = sum(1 for r in exec_results if r.success)
        failed = total - succeeded
        avg_retries = sum(r.retries for r in exec_results) / total
        high_retry_count = sum(1 for r in exec_results if r.retries >= 2)
        failure_types: dict[str, int] = {}
        for r in exec_results:
            if not r.success and r.failure_type is not None:
                ft = r.failure_type.value
                failure_types[ft] = failure_types.get(ft, 0) + 1
        stats.append(
            CategoryStats(
                category=category,
                total=total,
                succeeded=succeeded,
                failed=failed,
                avg_retries=avg_retries,
                high_retry_count=high_retry_count,
                failure_types=failure_types,
            )
        )
    return stats


def detect_anomalies(
    stats: list[CategoryStats],
    total_ideas: int,
    approved_ideas: int,
) -> list[Anomaly]:
    anomalies: list[Anomaly] = []

    for s in stats:
        if s.total < MIN_CATEGORY_SIZE:
            continue

        high_retry_rate = s.high_retry_count / s.total
        if high_retry_rate > BASELINES["high_retry_rate"]:
            pct = int(high_retry_rate * 100)
            baseline_pct = int(BASELINES["high_retry_rate"] * 100)
            anomalies.append(
                Anomaly(
                    message=(
                        f"Unusual: {pct}% of {s.category} items required 2+ retries "
                        f"(baseline: <{baseline_pct}%)"
                    ),
                    severity="warning",
                    suggestion=SUGGESTIONS["high_retry_rate"],
                )
            )

        success_rate = s.succeeded / s.total
        if success_rate < BASELINES["low_success_rate"]:
            pct = int(success_rate * 100)
            baseline_pct = int(BASELINES["low_success_rate"] * 100)
            anomalies.append(
                Anomaly(
                    message=(
                        f"Unusual: {s.category} success rate is {pct}% (baseline: >{baseline_pct}%)"
                    ),
                    severity="warning",
                    suggestion=SUGGESTIONS["low_success_rate"],
                )
            )

        if s.failed > 0 and s.failure_types:
            dominant_type, dominant_count = max(s.failure_types.items(), key=lambda x: x[1])
            dominant_rate = dominant_count / s.failed
            if dominant_rate > BASELINES["dominant_failure_type"]:
                pct = int(dominant_rate * 100)
                baseline_pct = int(BASELINES["dominant_failure_type"] * 100)
                suggestion = SUGGESTIONS["dominant_failure_type"].format(
                    failure_type=dominant_type,
                )
                anomalies.append(
                    Anomaly(
                        message=(
                            f"Unusual: {pct}% of {s.category} failures are "
                            f"'{dominant_type}' (baseline: <{baseline_pct}%)"
                        ),
                        severity="info",
                        suggestion=suggestion,
                    )
                )

    if total_ideas >= MIN_CATEGORY_SIZE:
        if total_ideas > 0:
            approval_rate = approved_ideas / total_ideas
            if approval_rate < BASELINES["feature_approval_low"]:
                pct = int(approval_rate * 100)
                baseline_pct = int(BASELINES["feature_approval_low"] * 100)
                anomalies.append(
                    Anomaly(
                        message=(
                            f"Unusual: feature idea approval rate is {pct}% "
                            f"(baseline: >{baseline_pct}%)"
                        ),
                        severity="warning",
                        suggestion=SUGGESTIONS["feature_approval_low"],
                    )
                )
            if approval_rate > BASELINES["feature_approval_high"]:
                pct = int(approval_rate * 100)
                baseline_pct = int(BASELINES["feature_approval_high"] * 100)
                anomalies.append(
                    Anomaly(
                        message=(
                            f"Unusual: feature idea approval rate is {pct}% "
                            f"(baseline: <{baseline_pct}%)"
                        ),
                        severity="info",
                        suggestion=SUGGESTIONS["feature_approval_high"],
                    )
                )

    return anomalies
