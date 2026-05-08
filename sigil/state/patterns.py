import json
import logging
from pathlib import Path

from sigil.core.config import SIGIL_DIR

logger = logging.getLogger(__name__)

PATTERNS_FILE = "patterns.json"
MAX_PATTERNS_PER_CATEGORY = 5


def _patterns_path(repo: Path) -> Path:
    return repo / SIGIL_DIR / PATTERNS_FILE


def load_patterns(repo: Path) -> dict:
    path = _patterns_path(repo)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def save_patterns(repo: Path, patterns: dict) -> None:
    path = _patterns_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(patterns, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def extract_tool_sequence(messages: list[dict]) -> list[str]:
    sequence: list[str] = []
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            continue
        for tc in tool_calls:
            if isinstance(tc, dict):
                func = tc.get("function", {})
                name = func.get("name", "")
            else:
                name = getattr(getattr(tc, "function", None), "name", "") or ""
            if name:
                sequence.append(name)
    return sequence


def normalize_sequence(sequence: list[str]) -> list[str]:
    if not sequence:
        return []
    result: list[str] = [sequence[0]]
    for item in sequence[1:]:
        if item != result[-1]:
            result.append(item)
    return result


def record_pattern(repo: Path, category: str, sequence: list[str]) -> None:
    if not sequence or not category:
        return
    try:
        patterns = load_patterns(repo)
        category_patterns: list[dict] = patterns.get(category, [])
        key = " → ".join(sequence)
        found = False
        for entry in category_patterns:
            if entry.get("sequence") == key:
                entry["count"] = entry.get("count", 0) + 1
                entry["last_seen"] = _timestamp()
                found = True
                break
        if not found:
            category_patterns.append({"sequence": key, "count": 1, "last_seen": _timestamp()})
        category_patterns.sort(key=lambda e: e.get("count", 0), reverse=True)
        patterns[category] = category_patterns[:MAX_PATTERNS_PER_CATEGORY]
        save_patterns(repo, patterns)
    except Exception:
        logger.warning("Failed to record pattern for category %s", category, exc_info=True)


def get_pattern_hints(repo: Path, category: str) -> str:
    patterns = load_patterns(repo)
    category_patterns = patterns.get(category, [])
    if not category_patterns:
        return ""
    lines = ["## Learned Tool Patterns", ""]
    for i, entry in enumerate(category_patterns, 1):
        seq = entry.get("sequence", "")
        count = entry.get("count", 0)
        lines.append(f"{i}. {seq} ({count} success{'es' if count != 1 else ''})")
    lines.append("")
    return "\n".join(lines)


def _timestamp() -> str:
    from sigil.core.utils import now_utc

    return now_utc()
