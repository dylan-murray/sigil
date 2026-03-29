import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from sigil.core.config import SIGIL_DIR

logger = logging.getLogger(__name__)

ATTEMPTS_FILE = "attempts.jsonl"
MAX_ATTEMPTS = 500


@dataclass(frozen=True)
class AttemptRecord:
    run_id: str
    timestamp: str
    item_type: str
    item_id: str
    category: str
    complexity: str
    approach: str
    model: str
    retries: int
    outcome: str
    tokens_used: int
    duration_s: float
    failure_detail: str


def _attempts_path(repo: Path) -> Path:
    return repo / SIGIL_DIR / ATTEMPTS_FILE


def log_attempt(repo: Path, record: AttemptRecord) -> None:
    path = _attempts_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(asdict(record)) + "\n")


def read_attempts(repo: Path, *, item_id: str | None = None) -> list[AttemptRecord]:
    path = _attempts_path(repo)
    if not path.exists():
        return []
    records: list[AttemptRecord] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            record = AttemptRecord(**data)
            if item_id is None or record.item_id == item_id:
                records.append(record)
        except (json.JSONDecodeError, TypeError):
            continue
    return records


def prune_attempts(repo: Path) -> int:
    path = _attempts_path(repo)
    if not path.exists():
        return 0
    lines = path.read_text().splitlines()
    if len(lines) <= MAX_ATTEMPTS:
        return 0
    pruned = len(lines) - MAX_ATTEMPTS
    path.write_text("\n".join(lines[pruned:]) + "\n")
    return pruned


def format_attempt_history(records: list[AttemptRecord]) -> str:
    if not records:
        return ""
    parts = ["Previous attempts on this item:"]
    for r in records:
        status = "SUCCESS" if r.outcome == "success" else f"FAILED ({r.outcome})"
        detail = f" — {r.failure_detail}" if r.failure_detail else ""
        parts.append(f"- [{status}] {r.approach}{detail}")
    return "\n".join(parts)
