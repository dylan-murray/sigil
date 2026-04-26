import json

import pytest

from sigil.state.attempts import (
    MAX_ATTEMPTS,
    AttemptRecord,
    format_attempt_history,
    log_attempt,
    prune_attempts,
    read_attempts,
)


def _make_record(**overrides) -> AttemptRecord:
    defaults = {
        "run_id": "abc123",
        "timestamp": "2026-03-23T00:00:00Z",
        "item_type": "finding",
        "item_id": "finding:dead_code:utils.py",
        "category": "dead_code",
        "complexity": "",
        "approach": "Remove unused function",
        "model": "gpt-4o",
        "retries": 0,
        "outcome": "success",
        "tokens_used": 5000,
        "duration_s": 12.3,
        "failure_detail": "",
    }
    defaults.update(overrides)
    return AttemptRecord(**defaults)


def test_log_and_read_roundtrip(tmp_path):
    assert read_attempts(tmp_path) == []

    record = _make_record(retries=2, outcome="post_hook", failure_detail="ruff failed")
    log_attempt(tmp_path, record)

    results = read_attempts(tmp_path)
    assert len(results) == 1
    assert results[0] == record

    raw = (tmp_path / ".sigil" / "attempts.jsonl").read_text()
    parsed = json.loads(raw.strip())
    assert parsed["item_id"] == "finding:dead_code:utils.py"


def test_read_filters_by_item_id(tmp_path):
    log_attempt(tmp_path, _make_record(item_id="finding:dead_code:a.py"))
    log_attempt(tmp_path, _make_record(item_id="idea:add-caching"))
    log_attempt(tmp_path, _make_record(item_id="finding:dead_code:a.py", outcome="post_hook"))

    matched = read_attempts(tmp_path, item_id="finding:dead_code:a.py")
    assert len(matched) == 2
    assert all(r.item_id == "finding:dead_code:a.py" for r in matched)

    all_records = read_attempts(tmp_path)
    assert len(all_records) == 3


def test_read_skips_corrupt_lines(tmp_path):
    path = tmp_path / ".sigil" / "attempts.jsonl"
    path.parent.mkdir(parents=True)
    good = json.dumps(
        {
            "run_id": "a",
            "timestamp": "t",
            "item_type": "finding",
            "item_id": "x",
            "category": "dead_code",
            "complexity": "",
            "approach": "fix",
            "model": "m",
            "retries": 0,
            "outcome": "success",
            "tokens_used": 1,
            "duration_s": 1.0,
            "failure_detail": "",
        }
    )
    path.write_text(f"{good}\nNOT JSON\n{good}\n")

    results = read_attempts(tmp_path)
    assert len(results) == 2


@pytest.mark.parametrize(
    "num_lines, expected_pruned",
    [
        (MAX_ATTEMPTS, 0),
        (MAX_ATTEMPTS + 100, 100),
    ],
    ids=["at_cap_noop", "over_cap_keeps_newest"],
)
def test_prune(tmp_path, num_lines, expected_pruned):
    path = tmp_path / ".sigil" / "attempts.jsonl"
    path.parent.mkdir(parents=True)
    lines = []
    for i in range(num_lines):
        lines.append(
            json.dumps(
                {
                    "run_id": f"run-{i}",
                    "timestamp": "t",
                    "item_type": "finding",
                    "item_id": "x",
                    "category": "dc",
                    "complexity": "",
                    "approach": "a",
                    "model": "m",
                    "retries": 0,
                    "outcome": "success",
                    "tokens_used": 1,
                    "duration_s": 1.0,
                    "failure_detail": "",
                }
            )
        )
    path.write_text("\n".join(lines) + "\n")

    pruned = prune_attempts(tmp_path)
    assert pruned == expected_pruned

    remaining = read_attempts(tmp_path)
    assert len(remaining) == min(num_lines, MAX_ATTEMPTS)

    if expected_pruned > 0:
        assert remaining[0].run_id == f"run-{expected_pruned}"
        assert remaining[-1].run_id == f"run-{num_lines - 1}"


def test_format_history():
    assert format_attempt_history([]) == ""

    records = [
        _make_record(outcome="success", approach="Remove unused import"),
        _make_record(
            outcome="post_hook", approach="Refactor loop", failure_detail="ruff check failed"
        ),
    ]
    output = format_attempt_history(records)
    assert "[SUCCESS] Remove unused import" in output
    assert "[FAILED (post_hook)] Refactor loop — ruff check failed" in output
    assert output.startswith("Previous attempts on this item:")


def test_read_attempts_empty_file(tmp_path):
    path = tmp_path / ".sigil" / "attempts.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("")
    assert read_attempts(tmp_path) == []


def test_prune_no_op_when_below_cap(tmp_path):
    assert prune_attempts(tmp_path) == 0


def test_prune_no_op_when_file_missing(tmp_path):
    assert prune_attempts(tmp_path) == 0


def test_read_attempts_filters_empty_lines(tmp_path):
    path = tmp_path / ".sigil" / "attempts.jsonl"
    path.parent.mkdir(parents=True)
    record = _make_record()
    import json
    from dataclasses import asdict

    path.write_text(f"\n{json.dumps(asdict(record))}\n\n")
    results = read_attempts(tmp_path)
    assert len(results) == 1
    assert results[0] == record
