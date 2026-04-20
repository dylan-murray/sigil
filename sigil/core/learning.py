import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sigil.core.config import memory_dir
from sigil.core.utils import read_file

logger = logging.getLogger(__name__)

LEARNING_DIR = "learning"
OUTCOMES_FILE = "outcomes.json"


@dataclass
class Outcome:
    pr_number: int
    category: str
    merged: bool
    time_to_merge_days: float | None = None
    feedback: str | None = None
    complexity: str | None = None
    risk: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pr_number": self.pr_number,
            "category": self.category,
            "merged": self.merged,
            "time_to_merge_days": self.time_to_merge_days,
            "feedback": self.feedback,
            "complexity": self.complexity,
            "risk": self.risk,
        }


class OutcomeTracker:
    def __init__(self, repo: Path):
        self.repo = repo
        self.learning_dir = memory_dir(repo) / LEARNING_DIR
        self.outcomes_path = self.learning_dir / OUTCOMES_FILE
        self.outcomes: dict[int, Outcome] = {}
        self._load()

    def _load(self) -> None:
        if not self.outcomes_path.exists():
            return
        try:
            data = json.loads(read_file(self.outcomes_path))
            self.outcomes = {int(k): Outcome(**v) for k, v in data.items()}
        except Exception as e:
            logger.error("Failed to load outcomes: %s", e)

    def save(self) -> None:
        self.learning_dir.mkdir(parents=True, exist_ok=True)
        data = {k: v.to_dict() for k, v in self.outcomes.items()}
        self.outcomes_path.write_text(json.dumps(data, indent=2))

    def record_outcome(self, pr_number: int, category: str, merged: bool, **kwargs) -> None:
        self.outcomes[pr_number] = Outcome(
            pr_number=pr_number, category=category, merged=merged, **kwargs
        )
        self.save()


class LearningEngine:
    def __init__(self, tracker: OutcomeTracker):
        self.tracker = tracker

    def get_success_rate(self, category: str) -> float:
        relevant = [o for o in self.tracker.outcomes.values() if o.category == category]
        if not relevant:
            return 0.0
        merged = [o for o in relevant if o.merged]
        return len(merged) / len(relevant)

    def get_failure_reasons(self, category: str) -> list[str]:
        relevant = [
            o for o in self.tracker.outcomes.values() if o.category == category and not o.merged
        ]
        reasons = [o.feedback for o in relevant if o.feedback]
        return reasons

    def predict_success(self, category: str) -> float:
        return self.get_success_rate(category)

    def get_prompt_guidance(self) -> str:
        if not self.tracker.outcomes:
            return "No historical outcome data available."

        categories: dict[str, list[Outcome]] = {}
        for o in self.tracker.outcomes.values():
            categories.setdefault(o.category, []).append(o)

        insights = []
        for cat, outcomes in categories.items():
            merged_count = len([o for o in outcomes if o.merged])
            rate = merged_count / len(outcomes)
            if rate >= 0.8:
                insights.append(f"- {cat}: High success rate ({rate:.0%}). Focus here.")
            elif rate <= 0.2:
                reasons = self.get_failure_reasons(cat)
                reason_str = f" Common issues: {', '.join(reasons[:2])}" if reasons else ""
                insights.append(f"- {cat}: Low success rate ({rate:.0%}). Be cautious.{reason_str}")

        if not insights:
            return "Historical data exists but no strong patterns detected."

        return "Learning Insights from Past PRs:\n" + "\n".join(insights)
