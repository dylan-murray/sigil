from sigil.core.config import Config
from sigil.state.chronic import WorkItem

PERSISTENCE_KEYWORDS = (
    "persist",
    "cross-session",
    "cross_run",
    "cross-run",
    "state track",
    "state management",
    "database",
    "sqlite",
    "leveldb",
    "redis",
)


class ComplexityVerdict:
    __slots__ = ("action", "reason")

    def __init__(self, action: str, reason: str = "") -> None:
        self.action = action
        self.reason = reason


def check_complexity(item: WorkItem, max_files: int) -> ComplexityVerdict:
    spec = getattr(item, "implementation_spec", "") or ""
    spec_lower = spec.lower()
    for keyword in PERSISTENCE_KEYWORDS:
        if keyword in spec_lower:
            return ComplexityVerdict(
                action="downgrade",
                reason=(
                    f"Complexity guardrail: implementation spec references "
                    f"cross-session persistence ({keyword!r})"
                ),
            )

    relevant_files = getattr(item, "relevant_files", ()) or ()
    if len(relevant_files) > max_files:
        return ComplexityVerdict(
            action="downgrade",
            reason=(
                f"Complexity guardrail: touches {len(relevant_files)} files "
                f"(threshold: {max_files})"
            ),
        )

    return ComplexityVerdict(action="proceed")


def filter_complexity(
    pr_items: list[WorkItem],
    issue_items: list[WorkItem],
    config: Config,
) -> tuple[list[WorkItem], list[WorkItem], list[WorkItem]]:
    max_files = config.complexity_max_files
    execute: list[WorkItem] = []
    downgraded: list[WorkItem] = []
    skipped: list[WorkItem] = []

    for item in pr_items:
        verdict = check_complexity(item, max_files)
        if verdict.action == "downgrade":
            downgraded.append(item)
        else:
            execute.append(item)

    return execute, issue_items + downgraded, skipped
