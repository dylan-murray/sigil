from dataclasses import dataclass

from sigil.core.models import TokenUsage
from sigil.pipeline.models import ExecutionResult

EXPECTED_STAGES = ["discovery", "analysis", "ideation", "validation", "execution"]

_WEIGHTS: dict[str, float] = {
    "execution_success": 0.30,
    "avg_retries": 0.15,
    "token_efficiency": 0.15,
    "finding_to_pr": 0.20,
    "stage_completion": 0.20,
}

_RECOMMENDATION_TEMPLATES: dict[str, str] = {
    "execution_success": (
        "Low execution success rate. Consider reducing max_parallel_tasks to avoid "
        "resource contention, or review pre-hooks for false positives."
    ),
    "avg_retries": (
        "High retry count suggests post-hooks are failing repeatedly. "
        "Review post-hook commands for flakiness or tighten validation rules."
    ),
    "token_efficiency": (
        "Token usage exceeded budget proportionally. Consider using cheaper models "
        "for high-volume agents (compactor, selector, memory) or reducing max_iterations."
    ),
    "finding_to_pr": (
        "Low finding-to-PR conversion rate. Validation may be too strict — "
        "review focus areas and boldness setting, or check for chronic downgrades."
    ),
    "stage_completion": (
        "Pipeline stages were skipped. If discovery was skipped due to stale knowledge, "
        "consider running with --refresh. If execution was skipped, ensure findings "
        "survive validation with 'pr' disposition."
    ),
}


@dataclass(frozen=True)
class RunHealthScore:
    score: int
    sub_scores: dict[str, float]
    recommendations: list[str]


def compute_health_score(
    *,
    execution_results: list[ExecutionResult],
    total_findings: int,
    pr_candidates: int,
    stages_ran: list[str],
    expected_stages: list[str],
    usage: TokenUsage,
    budget_usd: float,
    threshold: int = 60,
) -> RunHealthScore:
    sub_scores: dict[str, float] = {}

    if execution_results:
        successes = sum(1 for r in execution_results if r.success)
        sub_scores["execution_success"] = successes / len(execution_results) * 100
    else:
        sub_scores["execution_success"] = 100.0

    if execution_results:
        avg_retries = sum(r.retries for r in execution_results) / len(execution_results)
        sub_scores["avg_retries"] = max(0.0, 100 - avg_retries * 25)
    else:
        sub_scores["avg_retries"] = 100.0

    if usage.cost_usd > 0:
        sub_scores["token_efficiency"] = min(100.0, budget_usd / usage.cost_usd * 100)
    else:
        sub_scores["token_efficiency"] = 100.0

    if total_findings > 0:
        sub_scores["finding_to_pr"] = pr_candidates / total_findings * 100
    else:
        sub_scores["finding_to_pr"] = 100.0

    if expected_stages:
        ran_set = set(stages_ran)
        expected_set = set(expected_stages)
        sub_scores["stage_completion"] = len(ran_set & expected_set) / len(expected_set) * 100
    else:
        sub_scores["stage_completion"] = 100.0

    raw = sum(sub_scores[k] * _WEIGHTS[k] for k in _WEIGHTS)
    score = max(0, min(100, round(raw)))

    recommendations = _generate_recommendations(sub_scores, threshold)

    return RunHealthScore(score=score, sub_scores=sub_scores, recommendations=recommendations)


def _generate_recommendations(sub_scores: dict[str, float], threshold: int) -> list[str]:
    below = sorted(
        ((k, v) for k, v in sub_scores.items() if v < threshold),
        key=lambda kv: kv[1],
    )
    recs: list[str] = []
    for key, _ in below[:3]:
        template = _RECOMMENDATION_TEMPLATES.get(key)
        if template:
            recs.append(template)
    return recs
