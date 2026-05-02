import json
import logging
from pathlib import Path

from sigil.core.config import SIGIL_DIR

logger = logging.getLogger(__name__)

STATE_DIR = "state"
LAST_RUN_FILE = "last_run.json"


def _state_dir(repo: Path) -> Path:
    return repo / SIGIL_DIR / STATE_DIR


def load_last_run_head(repo: Path) -> str | None:
    path = _state_dir(repo) / LAST_RUN_FILE
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.debug("Failed to read last_run.json: %s", e)
        return None
    if not isinstance(raw, dict):
        return None
    head = raw.get("head")
    if isinstance(head, str) and head.strip():
        return head.strip()
    return None


def save_last_run_head(repo: Path, head: str) -> None:
    sdir = _state_dir(repo)
    sdir.mkdir(parents=True, exist_ok=True)
    path = sdir / LAST_RUN_FILE
    try:
        path.write_text(json.dumps({"head": head}) + "\n")
    except OSError as e:
        logger.warning("Failed to write last_run.json: %s", e)
