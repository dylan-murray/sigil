import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from sigil.core.config import SIGIL_DIR

logger = logging.getLogger(__name__)

OUTCOMES_FILE = "outcomes.jsonl"


@dataclass(frozen=True)
class OutcomeRecord:
    run_id: str
    item_id: str
    item_type: str
    category: str
    outcome: str
    pr_number: int
    pr_url: str
    title: str
    opened_at: str
    closed_at: str | None
    recorded_at: str


def _outcomes_path(repo: Path) -> Path:
    return repo / SIGIL_DIR / OUTCOMES_FILE


def log_outcome(repo: Path, record: OutcomeRecord) -> None:
    path = _outcomes_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(asdict(record)) + "\n")


def read_outcomes(repo: Path) -> list[OutcomeRecord]:
    path = _outcomes_path(repo)
    if not path.exists():
        return []
    records: list[OutcomeRecord] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            records.append(OutcomeRecord(**data))
        except (json.JSONDecodeError, TypeError):
            continue
    return records


def latest_outcomes(repo: Path) -> dict[int, OutcomeRecord]:
    records = read_outcomes(repo)
    by_pr: dict[int, OutcomeRecord] = {}
    for record in records:
        by_pr[record.pr_number] = record
    return by_pr


def pr_number_from_url(url: str) -> int | None:
    m = re.search(r"/pull/(\d+)", url)
    if m:
        return int(m.group(1))
    return None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
