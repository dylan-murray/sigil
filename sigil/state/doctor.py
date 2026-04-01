from collections import defaultdict
from pathlib import Path

from sigil.pipeline.maintenance import Finding
from sigil.state.attempts import AttemptRecord, read_attempts

MIN_ATTEMPTS = 5
FAILURE_RATE_THRESHOLD = 0.8


def _directory_from_item_id(item_id: str) -> str:
    parts = item_id.split(":", 2)
    if len(parts) != 3:
        return ""
    path = Path(parts[2])
    parent = path.parent.as_posix()
    if parent == ".":
        return ""
    return parent


def _failure_rate(records: list[AttemptRecord]) -> float:
    if not records:
        return 0.0
    failures = sum(1 for record in records if record.outcome != "success")
    return failures / len(records)


def diagnose_config(repo: Path) -> list[Finding]:
    records = read_attempts(repo)
    grouped: dict[str, list[AttemptRecord]] = defaultdict(list)

    for record in records:
        if record.item_type != "finding":
            continue
        directory = _directory_from_item_id(record.item_id)
        if not directory:
            continue
        grouped[directory].append(record)

    findings: list[Finding] = []
    for directory, attempts in sorted(grouped.items()):
        if len(attempts) < MIN_ATTEMPTS:
            continue
        failure_rate = _failure_rate(attempts)
        if failure_rate < FAILURE_RATE_THRESHOLD:
            continue

        failures = sum(1 for record in attempts if record.outcome != "success")
        findings.append(
            Finding(
                category="config_tuning",
                file=".sigil/config.yml",
                line=None,
                description=(
                    f"High failure rate in {directory}: {failures}/{len(attempts)} attempts "
                    f"failed ({failure_rate:.0%})."
                ),
                risk="low",
                suggested_fix="Add the directory to Sigil's ignore list or route it to a stronger model.",
                disposition="pr",
                priority=1,
                rationale=(
                    "Repeated failures suggest Sigil should stop spending effort here or use a more capable model."
                ),
                implementation_spec=(
                    f"Update .sigil/config.yml to add '{directory}/**' to ignore patterns, or set an "
                    f"agents override for the relevant module to use a stronger model. Prefer the smallest "
                    f"safe configuration change that prevents repeated failures."
                ),
                relevant_files=(".sigil/config.yml",),
                boldness="balanced",
            )
        )

    return findings
