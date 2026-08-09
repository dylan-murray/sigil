import json
import logging
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel

from sigil.core.config import memory_dir

logger = logging.getLogger(__name__)

PERSISTENT_FILE = "persistent.json"


class PersistentState(BaseModel):
    vetoed_fingerprints: set[str] = set()
    failed_patterns: dict[str, int] = {}
    lessons: list[str] = []


def _persistent_path(repo: Path) -> Path:
    return memory_dir(repo) / PERSISTENT_FILE


def load_persistent_state(repo: Path) -> PersistentState:
    path = _persistent_path(repo)
    if not path.exists():
        return PersistentState()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return PersistentState.model_validate(data)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Corrupted persistent state, resetting: %s", exc)
        return PersistentState()


def save_persistent_state(repo: Path, state: PersistentState) -> Path:
    path = _persistent_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = state.model_dump(mode="json")
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def record_veto(repo: Path, fingerprints: Iterable[str]) -> Path:
    state = load_persistent_state(repo)
    state.vetoed_fingerprints.update(fingerprints)
    return save_persistent_state(repo, state)


def record_failure(repo: Path, pattern: str) -> Path:
    state = load_persistent_state(repo)
    state.failed_patterns[pattern] = state.failed_patterns.get(pattern, 0) + 1
    return save_persistent_state(repo, state)


def add_lesson(repo: Path, lesson: str) -> Path:
    state = load_persistent_state(repo)
    if lesson not in state.lessons:
        state.lessons.append(lesson)
    return save_persistent_state(repo, state)
