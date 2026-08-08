import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from sigil.core.config import SIGIL_DIR
from sigil.pipeline.models import FeatureIdea, Finding, ReviewDecision

logger = logging.getLogger(__name__)

VETOES_FILE = "vetoes.jsonl"
MAX_VETOES = 500
DEFAULT_VETO_TTL_DAYS = 90
MAX_CONTEXT_VETOES = 50


@dataclass(frozen=True)
class VetoRecord:
    fingerprint: str
    reason: str
    action: str
    timestamp: str
    item_type: str
    category: str
    title: str
    file: str


def _vetoes_path(repo: Path) -> Path:
    return repo / SIGIL_DIR / VETOES_FILE


def record_vetoes(
    repo: Path,
    findings: list[Finding],
    ideas: list[FeatureIdea],
    decisions: dict[int, ReviewDecision],
) -> None:
    from sigil.state.chronic import fingerprint as _fingerprint

    path = _vetoes_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    offset = len(findings)
    new_records: list[VetoRecord] = []

    for i, finding in enumerate(findings):
        d = decisions.get(i)
        if d is None:
            continue
        if d.action == "veto" or (d.action == "adjust" and d.new_disposition == "skip"):
            fp = _fingerprint(finding)
            new_records.append(
                VetoRecord(
                    fingerprint=fp,
                    reason=d.reason,
                    action=d.action,
                    timestamp=ts,
                    item_type="finding",
                    category=finding.category,
                    title="",
                    file=finding.file,
                )
            )

    for j, idea in enumerate(ideas):
        idx = offset + j
        d = decisions.get(idx)
        if d is None:
            continue
        if d.action == "veto" or (d.action == "adjust" and d.new_disposition == "skip"):
            fp = _fingerprint(idea)
            new_records.append(
                VetoRecord(
                    fingerprint=fp,
                    reason=d.reason,
                    action=d.action,
                    timestamp=ts,
                    item_type="idea",
                    category="",
                    title=idea.title,
                    file="",
                )
            )

    if not new_records:
        return

    with path.open("a") as f:
        for record in new_records:
            f.write(json.dumps(asdict(record)) + "\n")

    logger.info("Recorded %d veto(s)", len(new_records))


def load_vetoes(repo: Path, ttl_days: int = DEFAULT_VETO_TTL_DAYS) -> list[VetoRecord]:
    path = _vetoes_path(repo)
    if not path.exists():
        return []

    now = datetime.now(timezone.utc)
    records: list[VetoRecord] = []

    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            record = VetoRecord(**data)
        except (json.JSONDecodeError, TypeError):
            continue
        try:
            ts = datetime.fromisoformat(record.timestamp.replace("Z", "+00:00"))
            age_days = (now - ts).days
            if age_days > ttl_days:
                continue
        except (ValueError, TypeError):
            pass
        records.append(record)

    if len(records) > MAX_VETOES:
        pruned = records[-MAX_VETOES:]
        _rewrite_vetoes(path, pruned)
        return pruned

    return records


def _rewrite_vetoes(path: Path, records: list[VetoRecord]) -> None:
    lines = [json.dumps(asdict(r)) for r in records]
    path.write_text("\n".join(lines) + "\n")


def is_vetoed(item: Finding | FeatureIdea, vetoes: list[VetoRecord]) -> VetoRecord | None:
    from sigil.state.chronic import fingerprint as _fingerprint

    fp = _fingerprint(item)
    for v in vetoes:
        if v.fingerprint == fp:
            return v
    return None


def format_veto_context(vetoes: list[VetoRecord]) -> str:
    if not vetoes:
        return ""

    recent = vetoes[-MAX_CONTEXT_VETOES:]
    lines = ["## Previously Vetoed Items", ""]
    lines.append("The following items were vetoed or skipped in previous runs.")
    lines.append(
        "Do NOT re-propose these items unless you have a substantively different approach."
    )
    lines.append(
        "If the veto reason was fixable (e.g. 'too vague'), you may rephrase with more detail."
    )
    lines.append("")

    findings = [v for v in recent if v.item_type == "finding"]
    ideas = [v for v in recent if v.item_type == "idea"]

    if findings:
        lines.append("### Vetoed Findings")
        for v in findings:
            lines.append(f"- **{v.category}** in `{v.file}`: {v.reason} (action: {v.action})")
        lines.append("")

    if ideas:
        lines.append("### Vetoed Ideas")
        for v in ideas:
            lines.append(f"- **{v.title}**: {v.reason} (action: {v.action})")
        lines.append("")

    return "\n".join(lines)
