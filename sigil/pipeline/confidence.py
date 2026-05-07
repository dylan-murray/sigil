import re

from sigil.pipeline.models import FileTracker


def _diff_size_score(diff: str) -> float:
    if not diff:
        return 0.0
    changed_lines = 0
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            changed_lines += 1
        elif line.startswith("-") and not line.startswith("---"):
            changed_lines += 1
    if changed_lines <= 0:
        return 0.0
    if changed_lines <= 5:
        return 0.9
    if changed_lines <= 20:
        t = (changed_lines - 5) / 15.0
        return 0.9 - t * 0.3
    if changed_lines <= 50:
        t = (changed_lines - 20) / 30.0
        return 0.6 - t * 0.3
    t = min((changed_lines - 50) / 50.0, 1.0)
    return 0.3 - t * 0.1


def _additivity_score(diff: str) -> float:
    if not diff:
        return 0.0
    additions = 0
    removals = 0
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            removals += 1
    total = additions + removals
    if total == 0:
        return 0.0
    if removals == 0:
        return 0.9
    ratio = additions / total
    return 0.3 + ratio * 0.6


def _test_file_score(tracker: FileTracker) -> float:
    test_patterns = ("test_", "_test.", "tests/", "spec/", "_spec.", "specs/")
    all_files = tracker.modified | tracker.created
    for f in all_files:
        normalized = f.replace("\\", "/")
        for pattern in test_patterns:
            if pattern in normalized:
                return 0.15
    return 0.0


_UNUSED_IMPORT_RE = re.compile(r"^-\s*import\s+\w+", re.MULTILINE)
_UNUSED_FROM_IMPORT_RE = re.compile(r"^-\s*from\s+[\w.]+\s+import\s+", re.MULTILINE)
_DEAD_CODE_RE = re.compile(r"^-\s*(pass|\.\.\.)\s*$", re.MULTILINE)
_TYPE_HINT_RE = re.compile(r"^\+.*:\s*\w+\s*=\s*|^\+.*->\s*\w+", re.MULTILINE)
_NOQA_RE = re.compile(r"^\+.*#\s*noqa", re.MULTILINE)


def _pattern_score(diff: str) -> float:
    if not diff:
        return 0.0
    score = 0.0
    if _UNUSED_IMPORT_RE.search(diff) or _UNUSED_FROM_IMPORT_RE.search(diff):
        score += 0.1
    if _DEAD_CODE_RE.search(diff):
        score += 0.1
    if _TYPE_HINT_RE.search(diff):
        score += 0.1
    if _NOQA_RE.search(diff):
        score += 0.1
    return min(score, 0.3)


def _dependency_risk_score(diff: str) -> float:
    if not diff:
        return 0.0
    new_imports = 0
    removed_imports = 0
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            stripped = line[1:].strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                new_imports += 1
        elif line.startswith("-") and not line.startswith("---"):
            stripped = line[1:].strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                removed_imports += 1
    net_new = new_imports - removed_imports
    if net_new <= 0:
        return 0.0
    penalty = min(net_new, 3) * 0.1
    return penalty


def estimate_confidence(diff: str, tracker: FileTracker) -> float:
    if not diff:
        return 0.0
    size = _diff_size_score(diff)
    additivity = _additivity_score(diff)
    test = _test_file_score(tracker)
    pattern = _pattern_score(diff)
    dep_risk = _dependency_risk_score(diff)
    weighted = (
        size * 0.25 + additivity * 0.20 + test * 0.20 + pattern * 0.20 + (1.0 - dep_risk) * 0.15
    )
    return max(0.0, min(1.0, weighted))
