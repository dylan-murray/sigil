import re
from fnmatch import fnmatch
from pathlib import Path

from sigil.pipeline.models import Finding

_TIME_SLEEP_RE = re.compile(r"time\.sleep\s*\(")
_MOCK_SLEEP_RE = re.compile(
    r"monkeypatch\.setattr.*time\.sleep|patch.*time\.sleep|mock.*time\.sleep"
)
_RANDOM_USAGE_RE = re.compile(r"\brandom\.\w+\s*\(")
_RANDOM_SEED_RE = re.compile(r"\brandom\.seed\s*\(")
_PARAMETRIZE_RE = re.compile(r"@pytest\.mark\.parametrize")
_UNORDERED_ASSERT_RE = re.compile(
    r"assert\s+\S+\s*==\s*\{|assert\s+\S+\s*==\s*set\(|assert\s+set\("
)
_DATETIME_NOW_RE = re.compile(r"datetime\.now\s*\(|datetime\.utcnow\s*\(")
_FREEZE_TIME_RE = re.compile(
    r"freezegun|freeze_time|monkeypatch\.\w*time|monkeypatch\.setattr.*datetime"
)
_OS_ENVIRON_SET_RE = re.compile(
    r"os\.environ\[.[^\]]*.\]\s*=|os\.environ\.update\(|del\s+os\.environ\["
)
_OS_ENVIRON_CLEANUP_RE = re.compile(
    r"monkeypatch\.setenv|monkeypatch\.delenv|os\.environ\.pop\("
    r"|os\.environ\.popitem\(|patch\.dict.*environ|with.*environ"
)


def _is_test_file(path: str) -> bool:
    name = Path(path).name
    if name in ("conftest.py", "__init__.py"):
        return False
    return name.startswith("test_") or name.endswith("_test.py")


def _should_skip(path: str, ignore: list[str] | None) -> bool:
    if ignore and any(fnmatch(path, p) for p in ignore):
        return True
    parts = Path(path).parts
    skip_dirs = {
        "node_modules",
        "vendor",
        "dist",
        "build",
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        "target",
        ".next",
        ".sigil",
    }
    return any(p in skip_dirs for p in parts)


def _scan_file(content: str, filepath: str) -> list[Finding]:
    if not _is_test_file(filepath):
        return []

    findings: list[Finding] = []
    lines = content.splitlines()
    next_priority = 1

    has_random_seed = bool(_RANDOM_SEED_RE.search(content))
    has_parametrize = bool(_PARAMETRIZE_RE.search(content))
    has_sleep_mock = bool(_MOCK_SLEEP_RE.search(content))
    has_freeze_time = bool(_FREEZE_TIME_RE.search(content))
    has_env_cleanup = bool(_OS_ENVIRON_CLEANUP_RE.search(content))

    for line_num, line in enumerate(lines, start=1):
        if _TIME_SLEEP_RE.search(line) and not has_sleep_mock:
            findings.append(
                Finding(
                    category="flaky_test",
                    file=filepath,
                    line=line_num,
                    description="time.sleep() without mocking makes tests slow and timing-dependent",
                    risk="medium",
                    suggested_fix="Use monkeypatch or unittest.mock.patch to replace time.sleep with a no-op or controlled delay",
                    disposition="pr",
                    priority=next_priority,
                    rationale="time.sleep() causes flaky tests due to timing sensitivity",
                )
            )
            next_priority += 1

        if _RANDOM_USAGE_RE.search(line) and not has_random_seed and not has_parametrize:
            findings.append(
                Finding(
                    category="flaky_test",
                    file=filepath,
                    line=line_num,
                    description="random module usage without seeding produces non-deterministic test results",
                    risk="medium",
                    suggested_fix="Add random.seed() with a fixed value or use @pytest.mark.parametrize with a seed",
                    disposition="pr",
                    priority=next_priority,
                    rationale="Unseeded random makes tests non-reproducible",
                )
            )
            next_priority += 1

        if _UNORDERED_ASSERT_RE.search(line):
            findings.append(
                Finding(
                    category="flaky_test",
                    file=filepath,
                    line=line_num,
                    description="Assertion on unordered collection (set/dict) may produce non-deterministic comparison failures",
                    risk="low",
                    suggested_fix="Sort collections before comparison or use set equality explicitly",
                    disposition="pr",
                    priority=next_priority,
                    rationale="Unordered collection assertions fail intermittently due to hash randomization",
                )
            )
            next_priority += 1

        if _DATETIME_NOW_RE.search(line) and not has_freeze_time:
            findings.append(
                Finding(
                    category="flaky_test",
                    file=filepath,
                    line=line_num,
                    description="datetime.now()/utcnow() without time freezing makes tests time-dependent",
                    risk="medium",
                    suggested_fix="Use freezegun or monkeypatch to freeze time in tests",
                    disposition="pr",
                    priority=next_priority,
                    rationale="Unfrozen datetime calls cause tests to fail at different times",
                )
            )
            next_priority += 1

        if _OS_ENVIRON_SET_RE.search(line) and not has_env_cleanup:
            findings.append(
                Finding(
                    category="flaky_test",
                    file=filepath,
                    line=line_num,
                    description="os.environ mutation without cleanup leaks state between tests",
                    risk="high",
                    suggested_fix="Use monkeypatch.setenv/delenv or a context manager to ensure cleanup",
                    disposition="issue",
                    priority=next_priority,
                    rationale="Environment variable mutations without cleanup cause cross-test contamination",
                )
            )
            next_priority += 1

    return findings


def detect_flaky_patterns(repo: Path, *, ignore: list[str] | None = None) -> list[Finding]:
    all_findings: list[Finding] = []

    for py_file in repo.rglob("*.py"):
        rel_path = py_file.relative_to(repo)
        filepath = str(rel_path)

        if _should_skip(filepath, ignore):
            continue

        try:
            content = py_file.read_text(errors="replace")
        except OSError:
            continue

        findings = _scan_file(content, filepath)
        all_findings.extend(findings)

    all_findings.sort(key=lambda f: f.priority)
    return all_findings
