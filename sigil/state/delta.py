import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from sigil.core.config import SIGIL_DIR
from sigil.pipeline.maintenance import Finding
from sigil.state.chronic import fingerprint

logger = logging.getLogger(__name__)

FINDINGS_FILE = "last-findings.json"


@dataclass
class FindingDelta:
    new: list[str] = field(default_factory=list)
    resolved: list[str] = field(default_factory=list)
    persistent: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"**NEW:** {len(self.new)}",
            f"**RESOLVED:** {len(self.resolved)}",
            f"**PERSISTENT:** {len(self.persistent)}",
        ]
        if self.new:
            lines.append("")
            lines.append("### New findings")
            for fp in self.new:
                lines.append(f"- {fp}")
        if self.resolved:
            lines.append("")
            lines.append("### Resolved findings")
            for fp in self.resolved:
                lines.append(f"- {fp}")
        if self.persistent:
            lines.append("")
            lines.append("### Persistent findings")
            for fp in self.persistent:
                lines.append(f"- {fp}")
        return "\n".join(lines)


def compute_finding_delta(
    current_findings: list[Finding],
    previous_fingerprints: set[str],
) -> FindingDelta:
    current_fps = {fingerprint(f) for f in current_findings}
    new = sorted(current_fps - previous_fingerprints)
    resolved = sorted(previous_fingerprints - current_fps)
    persistent = sorted(current_fps & previous_fingerprints)
    return FindingDelta(new=new, resolved=resolved, persistent=persistent)


def _findings_path(repo: Path) -> Path:
    return repo / SIGIL_DIR / "memory" / FINDINGS_FILE


def load_previous_fingerprints(repo: Path) -> set[str]:
    path = _findings_path(repo)
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return set(data.get("fingerprints", []))
    except (json.JSONDecodeError, OSError):
        logger.warning("Failed to read previous findings file, starting fresh")
        return set()


def save_fingerprints(repo: Path, findings: list[Finding]) -> None:
    path = _findings_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    fps = sorted(fingerprint(f) for f in findings)
    data = {"fingerprints": fps}
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
