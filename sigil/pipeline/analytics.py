import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from sigil.core.config import SIGIL_DIR, MEMORY_DIR

HISTORY_FILE = "run-history.jsonl"


@dataclass(frozen=True)
class RunHistory:
    run_id: str
    timestamp: float
    duration: float
    findings_count: int
    ideas_count: int
    prs_opened: int
    issues_opened: int
    token_input: int
    token_output: int
    cost_usd: float
    stages: dict[str, float]
    success: bool

    def to_json(self) -> str:
        return json.dumps(asdict(self))


def append_run_history(repo: Path, run: RunHistory) -> None:
    history_path = repo / SIGIL_DIR / MEMORY_DIR / HISTORY_FILE
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with open(history_path, "a", encoding="utf-8") as f:
        f.write(run.to_json() + "\n")


def load_run_history(repo: Path) -> list[RunHistory]:
    history_path = repo / SIGIL_DIR / MEMORY_DIR / HISTORY_FILE
    if not history_path.exists():
        return []

    runs = []
    with open(history_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                runs.append(RunHistory(**data))
            except (json.JSONDecodeError, TypeError):
                continue
    return runs


def build_analytics_summary(runs: list[RunHistory]) -> dict[str, Any]:
    if not runs:
        return {}

    total_runs = len(runs)
    total_findings = sum(r.findings_count for r in runs)
    total_ideas = sum(r.ideas_count for r in runs)
    total_prs = sum(r.prs_opened for r in runs)
    total_issues = sum(r.issues_opened for r in runs)
    total_cost = sum(r.cost_usd for r in runs)
    total_duration = sum(r.duration for r in runs)
    success_count = sum(1 for r in runs if r.success)

    # Stage timing aggregation
    stage_totals: dict[str, float] = {}
    for r in runs:
        for stage, duration in r.stages.items():
            stage_totals[stage] = stage_totals.get(stage, 0.0) + duration

    avg_stage_timing = {stage: total / total_runs for stage, total in stage_totals.items()}

    return {
        "total_runs": total_runs,
        "success_rate": (success_count / total_runs) * 100,
        "avg_findings": total_findings / total_runs,
        "avg_ideas": total_ideas / total_runs,
        "total_prs": total_prs,
        "total_issues": total_issues,
        "total_cost": total_cost,
        "avg_duration": total_duration / total_runs,
        "avg_stage_timing": avg_stage_timing,
    }


def generate_summary(runs: list[RunHistory]) -> str:
    summary = build_analytics_summary(runs)
    if not summary:
        return "# Sigil Run History\nNo run history available yet."

    lines = [
        "# Sigil Run History Summary",
        f"- **Total Runs:** {summary['total_runs']}",
        f"- **Success Rate:** {summary['success_rate']:.1f}%",
        f"- **Avg Findings/Run:** {summary['avg_findings']:.1f}",
        f"- **Total PRs Opened:** {summary['total_prs']}",
        f"- **Total Cost:** ${summary['total_cost']:.2f}",
        f"- **Avg Duration:** {summary['avg_duration']:.1f}s",
        "",
        "## Stage Timing (Average)",
    ]

    for stage, duration in sorted(
        summary["avg_stage_timing"].items(), key=lambda x: x[1], reverse=True
    ):
        lines.append(f"- {stage}: {duration:.1f}s")

    lines.append("\n## Recommendations")
    if summary["success_rate"] < 70:
        lines.append("- Consider adjusting `boldness` or `max_retries` to improve PR success rate.")
    if summary["avg_findings"] > 10:
        lines.append(
            "- High finding volume detected. Consider refining `focus` areas to reduce noise."
        )
    else:
        lines.append("- Run history looks stable. Continue monitoring for regressions.")

    return "\n".join(lines)
