import json
import logging
import re
from collections import Counter
from pathlib import Path

from sigil.core.config import SIGIL_DIR, MEMORY_DIR
from sigil.pipeline.maintenance import Finding
from sigil.state.attempts import AttemptRecord, read_attempts
from sigil.state.chronic import WorkItem, fingerprint as item_fingerprint, slugify

logger = logging.getLogger(__name__)

PATTERNS_FILE = "patterns.md"
TRACES_FILE = "last-run.jsonl"
ATTEMPTS_FILE = "attempts.jsonl"


def _traces_path(repo: Path) -> Path:
    return repo / SIGIL_DIR / "traces" / TRACES_FILE


def _attempts_path(repo: Path) -> Path:
    return repo / SIGIL_DIR / ATTEMPTS_FILE


def _patterns_path(repo: Path) -> Path:
    return repo / SIGIL_DIR / MEMORY_DIR / PATTERNS_FILE


def _item_category(item: WorkItem) -> str:
    if isinstance(item, Finding):
        return item.category
    return "idea"


def _strip_dedup_suffix(slug: str) -> str:
    match = re.match(r"^(.+)-\d+$", slug)
    if match:
        return match.group(1)
    return slug


def mine_tool_patterns(
    repo: Path,
    items: list[WorkItem] | None = None,
    max_per_category: int = 5,
) -> dict[str, list[str]]:
    traces_path = _traces_path(repo)
    attempts_path = _attempts_path(repo)

    if not traces_path.exists() or not attempts_path.exists():
        return {}

    slug_to_category: dict[str, str] = {}
    slug_to_fingerprint: dict[str, str] = {}
    if items:
        for item in items:
            s = slugify(item)
            slug_to_category[s] = _item_category(item)
            slug_to_fingerprint[s] = item_fingerprint(item)

    attempts: list[AttemptRecord] = read_attempts(repo)
    successful_ids: set[str] = set()
    attempt_categories: dict[str, str] = {}
    for rec in attempts:
        if rec.outcome == "success":
            successful_ids.add(rec.item_id)
        if rec.category:
            attempt_categories[rec.item_id] = rec.category

    tool_sequences: dict[str, list[str]] = {}
    try:
        lines = traces_path.read_text().splitlines()
    except OSError:
        return {}

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        if event.get("type") != "tool_call":
            continue

        task = event.get("task", "")
        if not task:
            continue

        tool_name = event.get("name", "")
        if not tool_name:
            continue

        if task not in tool_sequences:
            tool_sequences[task] = []
        tool_sequences[task].append(tool_name)

    category_sequences: dict[str, list[str]] = {}

    for task_slug, sequence in tool_sequences.items():
        category = slug_to_category.get(task_slug)
        if not category:
            base_slug = _strip_dedup_suffix(task_slug)
            category = slug_to_category.get(base_slug)

        if not category:
            for rec in attempts:
                fp = rec.item_id
                slug_part = fp.split(":")[-1] if ":" in fp else fp
                if (
                    task_slug == slug_part
                    or task_slug.startswith(slug_part)
                    or slug_part.startswith(task_slug)
                ):
                    category = rec.category or "idea"
                    break

        if not category:
            for item_id, cat in attempt_categories.items():
                slug_part = item_id.split(":")[-1] if ":" in item_id else item_id
                if (
                    task_slug == slug_part
                    or task_slug.startswith(slug_part)
                    or slug_part.startswith(task_slug)
                ):
                    category = cat
                    break

        if not category:
            continue

        is_successful = False
        fp = slug_to_fingerprint.get(task_slug)
        if fp and fp in successful_ids:
            is_successful = True
        else:
            base_slug = _strip_dedup_suffix(task_slug)
            fp = slug_to_fingerprint.get(base_slug)
            if fp and fp in successful_ids:
                is_successful = True

        if not is_successful:
            for rec in attempts:
                fp = rec.item_id
                slug_part = fp.split(":")[-1] if ":" in fp else fp
                if (
                    task_slug == slug_part
                    or task_slug.startswith(slug_part)
                    or slug_part.startswith(task_slug)
                ):
                    if rec.item_id in successful_ids:
                        is_successful = True
                    break

        if not is_successful and category:
            for rec in attempts:
                if rec.category == category and rec.item_id in successful_ids:
                    is_successful = True
                    break

        if not is_successful:
            continue

        pattern = " → ".join(sequence)
        if category not in category_sequences:
            category_sequences[category] = []
        category_sequences[category].append(pattern)

    result: dict[str, list[str]] = {}
    for category, patterns in category_sequences.items():
        counter = Counter(patterns)
        ranked = [p for p, _ in counter.most_common(max_per_category)]
        result[category] = ranked

    return result


def write_tool_patterns(repo: Path, patterns: dict[str, list[str]]) -> str | None:
    if not patterns:
        return None

    patterns_path = _patterns_path(repo)
    existing: dict[str, list[str]] = {}

    if patterns_path.exists():
        existing = _parse_patterns_file(patterns_path.read_text())

    merged: dict[str, list[str]] = {}
    all_categories = set(existing.keys()) | set(patterns.keys())
    for cat in all_categories:
        existing_patterns = existing.get(cat, [])
        new_patterns = patterns.get(cat, [])

        seen: set[str] = set()
        merged_list: list[str] = []
        for p in new_patterns + existing_patterns:
            if p not in seen:
                seen.add(p)
                merged_list.append(p)

        merged[cat] = merged_list[:5]

    content = _format_patterns_content(merged)
    patterns_path.parent.mkdir(parents=True, exist_ok=True)
    patterns_path.write_text(content)
    return str(patterns_path)


def _parse_patterns_file(content: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    current_category: str | None = None

    for line in content.splitlines():
        if line.startswith("## "):
            current_category = line.removeprefix("## ").strip()
            if current_category not in result:
                result[current_category] = []
        elif line.startswith("- ") and current_category is not None:
            pattern = line.removeprefix("- ").strip()
            if pattern:
                result[current_category].append(pattern)

    return result


def _format_patterns_content(patterns: dict[str, list[str]]) -> str:
    lines = ["# Tool Sequence Patterns by Category\n"]
    for category in sorted(patterns.keys()):
        lines.append(f"## {category}\n")
        for pattern in patterns[category]:
            lines.append(f"- {pattern}")
        lines.append("")

    return "\n".join(lines)


def format_pattern_hints(patterns: dict[str, list[str]], category: str) -> str:
    if category not in patterns or not patterns[category]:
        return ""

    lines = ["## Tool Hints (learned from successful executions)\n"]
    lines.append(
        f"The following tool sequences have been successful for "
        f"**{category}** tasks in this repository. Consider following "
        f"similar patterns:\n"
    )
    for i, pattern in enumerate(patterns[category], 1):
        lines.append(f"{i}. {pattern}")
    lines.append("")

    return "\n".join(lines)


def load_tool_patterns(repo: Path, category: str) -> str:
    patterns_path = _patterns_path(repo)
    if not patterns_path.exists():
        return ""

    try:
        content = patterns_path.read_text()
    except OSError:
        return ""

    patterns = _parse_patterns_file(content)
    return format_pattern_hints(patterns, category)
