import logging
import re
from dataclasses import dataclass
from pathlib import Path
from sigil.state.attempts import AttemptRecord, read_attempts
from sigil.pipeline.ideation import FeatureIdea
from sigil.pipeline.maintenance import Finding

log = logging.getLogger(__name__)

WorkItem = Finding | FeatureIdea

CHRONIC_INJECT_THRESHOLD = 1
CHRONIC_DOWNGRADE_THRESHOLD = 2
CHRONIC_SKIP_THRESHOLD = 3


@dataclass(frozen=True)
class ChronicVerdict:
    action: str
    prior_failures: int
    context: str


def fingerprint(item: WorkItem) -> str:
    if isinstance(item, Finding):
        return f"finding:{item.category}:{item.file}"
    return f"idea:{slugify(item)}"


def slugify(item: WorkItem) -> str:
    if isinstance(item, Finding):
        raw = f"{item.category}-{Path(item.file).stem}"
    else:
        raw = item.title
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return slug[:50]


def _count_failures(records: list[AttemptRecord]) -> int:
    return sum(1 for r in records if r.outcome != "success")


def _last_failure_detail(records: list[AttemptRecord]) -> str:
    for r in reversed(records):
        if r.outcome != "success" and r.failure_detail:
            return r.failure_detail
    return ""


def check_chronic(repo: Path, item: WorkItem) -> ChronicVerdict:
    fp = fingerprint(item)
    records = read_attempts(repo, item_id=fp)
    failures = _count_failures(records)

    if failures >= CHRONIC_SKIP_THRESHOLD:
        log.info(f"Chronic skip: {fp} has {failures} prior failures")
        return ChronicVerdict(
            action="skip",
            prior_failures=failures,
            context=f"Skipped: {failures} prior failed attempts. Last failure: {_last_failure_detail(records)}",
        )

    if failures >= CHRONIC_DOWNGRADE_THRESHOLD:
        log.info(f"Chronic downgrade: {fp} has {failures} prior failures")
        return ChronicVerdict(
            action="downgrade",
            prior_failures=failures,
            context=f"Downgraded to issue after {failures} failed attempts. Last failure: {_last_failure_detail(records)}",
        )

    if failures >= CHRONIC_INJECT_THRESHOLD:
        detail = _last_failure_detail(records)
        ctx = f"This item failed {failures} {'time' if failures == 1 else 'times'} before."
        if detail:
            ctx += f" Last failure: {detail}"
        ctx += " Try a fundamentally different approach."
        return ChronicVerdict(
            action="inject",
            prior_failures=failures,
            context=ctx,
        )

    return ChronicVerdict(action="proceed", prior_failures=0, context="")


def filter_chronic(
    repo: Path,
    pr_items: list[WorkItem],
    issue_items: list[WorkItem],
) -> tuple[list[WorkItem], list[WorkItem], list[WorkItem]]:
    execute: list[WorkItem] = []
    downgraded: list[WorkItem] = []
    skipped: list[WorkItem] = []

    for item in pr_items:
        verdict = check_chronic(repo, item)
        if verdict.action == "skip":
            skipped.append(item)
        elif verdict.action == "downgrade":
            downgraded.append(item)
        else:
            execute.append(item)

    return execute, issue_items + downgraded, skipped
