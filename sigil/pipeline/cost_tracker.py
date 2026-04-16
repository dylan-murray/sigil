from dataclasses import dataclass
from pathlib import Path

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sigil.state.attempts import AttemptRecord, read_attempts


@dataclass(frozen=True)
class CategoryStats:
    category: str
    attempts: int
    successes: int
    total_cost: float
    avg_cost: float
    success_rate: float
    efficiency_score: float  # success_rate / avg_cost (if avg_cost > 0)


@dataclass(frozen=True)
class CostInsights:
    summary: str
    high_cost_low_success: list[str]
    low_cost_high_success: list[str]
    total_spend: float
    total_attempts: int


class CostTracker:
    def __init__(self, records: list[AttemptRecord]):
        self.records = records

    def by_category(self) -> dict[str, CategoryStats]:
        stats: dict[str, list[AttemptRecord]] = {}
        for r in self.records:
            stats.setdefault(r.category, []).append(r)

        results: dict[str, CategoryStats] = {}
        for cat, recs in stats.items():
            count = len(recs)
            successes = sum(1 for r in recs if r.outcome == "success")
            total_cost = sum(r.cost_usd for r in recs)
            avg_cost = total_cost / count if count > 0 else 0.0
            success_rate = successes / count if count > 0 else 0.0
            efficiency = success_rate / avg_cost if avg_cost > 0 else 0.0

            results[cat] = CategoryStats(
                category=cat,
                attempts=count,
                successes=successes,
                total_cost=total_cost,
                avg_cost=avg_cost,
                success_rate=success_rate,
                efficiency_score=efficiency,
            )
        return results

    def efficiency_ranking(self) -> list[CategoryStats]:
        return sorted(
            self.by_category().values(),
            key=lambda x: x.efficiency_score,
            reverse=True,
        )

    def analyze(self) -> CostInsights:
        cat_stats = self.by_category()
        if not cat_stats:
            return CostInsights("", [], [], 0.0, 0)

        ranked = self.efficiency_ranking()

        # High cost, low success: bottom 25% of efficiency or high avg cost with low rate
        high_cost_low_success = [
            s.category for s in ranked[-2:] if s.success_rate < 0.5 and s.avg_cost > 0.1
        ]

        # Low cost, high success: top 25%
        low_cost_high_success = [s.category for s in ranked[:2] if s.success_rate > 0.7]

        total_spend = sum(r.cost_usd for r in self.records)
        total_attempts = len(self.records)

        summary_parts = []
        if low_cost_high_success:
            summary_parts.append(f"Prioritize {', '.join(low_cost_high_success)} (high efficiency)")
        if high_cost_low_success:
            summary_parts.append(
                f"Avoid/Refine {', '.join(high_cost_low_success)} (low efficiency)"
            )

        summary = (
            " | ".join(summary_parts)
            if summary_parts
            else "No significant cost patterns identified."
        )

        return CostInsights(
            summary=summary,
            high_cost_low_success=high_cost_low_success,
            low_cost_high_success=low_cost_high_success,
            total_spend=total_spend,
            total_attempts=total_attempts,
        )

    def format_dashboard(self) -> str:
        insights = self.analyze()

        table = Table(title="Cost Efficiency by Category", expand=True)
        table.add_column("Category", style="cyan")
        table.add_column("Attempts", justify="right")
        table.add_column("Success %", justify="right")
        table.add_column("Total Cost", justify="right")
        table.add_column("Avg Cost", justify="right")
        table.add_column("Efficiency", justify="right", style="green")

        for s in self.efficiency_ranking():
            table.add_row(
                s.category,
                str(s.attempts),
                f"{s.success_rate:.1%}",
                f"${s.total_cost:.2f}",
                f"${s.avg_cost:.2f}",
                f"{s.efficiency_score:.2f}",
            )

        summary_text = Text()
        summary_text.append(f"Total Spend: ${insights.total_spend:.2f}\n", style="bold")
        summary_text.append(f"Total Attempts: {insights.total_attempts}\n")
        summary_text.append(f"Insights: {insights.summary}", style="italic")

        # We return a rich-compatible string or renderable.
        # Since the CLI uses console.print(), we can return a Group or just the table.
        # But format_dashboard is expected to return a string or renderable.
        # Let's return a Panel containing the table and summary.

        # Since we are in a method, we can't easily return a 'Group' as a 'str'.
        # I'll return the table and the summary as a combined renderable if possible,
        # but the CLI call is `console.print(tracker.format_dashboard())`.
        # I will return a rich.console.Group.

        from rich.console import Group

        return Group(
            Panel(summary_text, title="Overall Summary", border_style="magenta"),
            table,
        )


def load_cost_tracker(repo: Path) -> CostTracker:
    records = read_attempts(repo)
    return CostTracker(records)
