import json
from dataclasses import asdict

import pytest

from sigil.attempts import AttemptRecord
from sigil.chronic import check_chronic, filter_chronic, fingerprint
from sigil.ideation import FeatureIdea
from sigil.maintenance import Finding


def _finding(**overrides) -> Finding:
    defaults = {
        "category": "dead_code",
        "file": "utils.py",
        "line": 10,
        "description": "Unused function",
        "risk": "low",
        "suggested_fix": "Remove it",
        "disposition": "pr",
        "priority": 1,
        "rationale": "Dead code",
    }
    defaults.update(overrides)
    return Finding(**defaults)


def _idea(**overrides) -> FeatureIdea:
    defaults = {
        "title": "Add Caching Layer",
        "description": "Cache API responses",
        "rationale": "Reduce latency",
        "complexity": "small",
        "disposition": "pr",
        "priority": 1,
    }
    defaults.update(overrides)
    return FeatureIdea(**defaults)


def _record(**overrides) -> AttemptRecord:
    defaults = {
        "run_id": "run1",
        "timestamp": "2026-03-23T00:00:00Z",
        "item_type": "finding",
        "item_id": "finding:dead_code:utils.py",
        "category": "dead_code",
        "complexity": "",
        "approach": "Remove unused function",
        "model": "gpt-4o",
        "retries": 0,
        "outcome": "post_hook",
        "tokens_used": 5000,
        "duration_s": 12.3,
        "failure_detail": "ruff check failed",
    }
    defaults.update(overrides)
    return AttemptRecord(**defaults)


def _write_attempts(tmp_path, records):
    sigil_dir = tmp_path / ".sigil"
    sigil_dir.mkdir(exist_ok=True)
    path = sigil_dir / "attempts.jsonl"
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(asdict(r)) + "\n")


@pytest.mark.parametrize(
    "item, expected",
    [
        (_finding(category="dead_code", file="utils.py"), "finding:dead_code:utils.py"),
        (_finding(category="security", file="src/auth.py"), "finding:security:src/auth.py"),
        (_idea(title="Add Caching Layer"), "idea:add-caching-layer"),
        (_idea(title="Fix: weird--symbols!!!"), "idea:fix-weird-symbols"),
    ],
)
def test_fingerprint(item, expected):
    assert fingerprint(item) == expected


@pytest.mark.parametrize(
    "failure_count, expected_action",
    [
        (0, "proceed"),
        (1, "inject"),
        (2, "downgrade"),
        (3, "skip"),
        (5, "skip"),
    ],
)
def test_check_chronic_thresholds(tmp_path, failure_count, expected_action):
    records = [_record(outcome="post_hook") for _ in range(failure_count)]
    _write_attempts(tmp_path, records)
    verdict = check_chronic(tmp_path, _finding())
    assert verdict.action == expected_action
    assert verdict.prior_failures == failure_count


def test_check_chronic_ignores_successes(tmp_path):
    records = [
        _record(outcome="success"),
        _record(outcome="success"),
        _record(outcome="post_hook"),
    ]
    _write_attempts(tmp_path, records)
    verdict = check_chronic(tmp_path, _finding())
    assert verdict.action == "inject"
    assert verdict.prior_failures == 1


def test_filter_chronic_routes_items(tmp_path):
    fresh = _finding(category="style", file="clean.py")
    one_fail = _finding(category="dead_code", file="utils.py")
    two_fail = _finding(category="tests", file="broken.py")
    three_fail = _finding(category="security", file="danger.py")

    records = [
        _record(item_id="finding:dead_code:utils.py", outcome="post_hook"),
        _record(item_id="finding:tests:broken.py", outcome="post_hook"),
        _record(item_id="finding:tests:broken.py", outcome="no_changes"),
        _record(item_id="finding:security:danger.py", outcome="post_hook"),
        _record(item_id="finding:security:danger.py", outcome="doom_loop"),
        _record(item_id="finding:security:danger.py", outcome="no_changes"),
    ]
    _write_attempts(tmp_path, records)

    existing_issues = [_finding(category="docs", file="readme.py")]
    execute, issues, skipped = filter_chronic(
        tmp_path, [fresh, one_fail, two_fail, three_fail], existing_issues
    )

    assert [fingerprint(i) for i in execute] == [
        "finding:style:clean.py",
        "finding:dead_code:utils.py",
    ]
    assert fingerprint(skipped[0]) == "finding:security:danger.py"
    assert any(fingerprint(i) == "finding:tests:broken.py" for i in issues)
    assert any(fingerprint(i) == "finding:docs:readme.py" for i in issues)
