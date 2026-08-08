import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from sigil.core.config import CONFIG_FILE, SIGIL_DIR
from sigil.core.utils import get_head

RUN_STATE_FILE = "last-run-state.json"


@dataclass(frozen=True, slots=True)
class RunState:
    state_hash: str
    had_failures: bool


async def compute_state_hash(repo: Path) -> str:
    head = await get_head(repo)
    config_path = repo / SIGIL_DIR / CONFIG_FILE
    config_contents = config_path.read_text() if config_path.exists() else ""
    combined = f"{head}\0{config_contents}"
    return hashlib.sha256(combined.encode()).hexdigest()


def load_last_run_state(repo: Path) -> RunState | None:
    path = repo / SIGIL_DIR / RUN_STATE_FILE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return RunState(state_hash=data["state_hash"], had_failures=data["had_failures"])
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def save_run_state(repo: Path, state: RunState) -> None:
    path = repo / SIGIL_DIR / RUN_STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2) + "\n")