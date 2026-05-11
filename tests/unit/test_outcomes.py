import json
from pathlib import Path

from sigil.state.outcomes import (
    OutcomeRecord,
    latest_outcomes,
    log_outcome,
    now_iso,
    pr_number_from_url,
    read_outcomes,
)


def _record(**overrides) -> OutcomeRecord:
    defaults = dict(
        run_id="run1",
        item_id="finding:dead_code:utils.py",
        item_type="finding",
        category="dead_code",
        outcome="open",
        pr_number=42,
        pr_url="https://github.com/owner/repo/pull/42",
        title="Remove dead code",
        opened_at="2026-04-01T00:00:00+00:00",
        closed_at=None,
        recorded_at="2026-04-01T00:00:00+00:00",
    )
    defaults.update(overrides)
    return OutcomeRecord(**defaults)


def test_log_outcome_writes_to_file(tmp_path: Path) -> None:
    record = _record()
    log_outcome(tmp_path, record)
    path = tmp_path / ".sigil" / "outcomes.jsonl"
    assert path.exists()
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["pr_number"] == 42
    assert data["outcome"] == "open"


def test_log_outcome_appends(tmp_path: Path) -> None:
    r1 = _record(pr_number=1, title="First")
    r2 = _record(pr_number=2, title="Second")
    log_outcome(tmp_path, r1)
    log_outcome(tmp_path, r2)
    records = read_outcomes(tmp_path)
    assert len(records) == 2
    assert records[0].pr_number == 1
    assert records[1].pr_number == 2


def test_read_outcomes_empty_file(tmp_path: Path) -> None:
    sigil_dir = tmp_path / ".sigil"
    sigil_dir.mkdir()
    (sigil_dir / "outcomes.jsonl").write_text("")
    assert read_outcomes(tmp_path) == []


def test_read_outcomes_missing_file(tmp_path: Path) -> None:
    assert read_outcomes(tmp_path) == []


def test_read_outcomes_skips_malformed_lines(tmp_path: Path) -> None:
    sigil_dir = tmp_path / ".sigil"
    sigil_dir.mkdir()
    path = sigil_dir / "outcomes.jsonl"
    record = _record()
    path.write_text("bad json\n" + json.dumps(record.__dict__) + "\n")
    results = read_outcomes(tmp_path)
    assert len(results) == 1
    assert results[0].pr_number == 42


def test_latest_outcomes_deduplicates(tmp_path: Path) -> None:
    r1 = _record(pr_number=10, outcome="open", title="First attempt")
    log_outcome(tmp_path, r1)
    r2 = _record(
        pr_number=10, outcome="merged", title="Merged!", closed_at="2026-04-05T00:00:00+00:00"
    )
    log_outcome(tmp_path, r2)
    result = latest_outcomes(tmp_path)
    assert len(result) == 1
    assert result[10].outcome == "merged"
    assert result[10].closed_at == "2026-04-05T00:00:00+00:00"


def test_latest_outcomes_multiple_prs(tmp_path: Path) -> None:
    r1 = _record(pr_number=1, outcome="open")
    r2 = _record(pr_number=2, outcome="open")
    log_outcome(tmp_path, r1)
    log_outcome(tmp_path, r2)
    result = latest_outcomes(tmp_path)
    assert len(result) == 2
    assert 1 in result
    assert 2 in result


def test_latest_outcomes_empty(tmp_path: Path) -> None:
    assert latest_outcomes(tmp_path) == {}


def test_pr_number_from_url_https() -> None:
    assert pr_number_from_url("https://github.com/owner/repo/pull/42") == 42


def test_pr_number_from_url_trailing_slash() -> None:
    assert pr_number_from_url("https://github.com/owner/repo/pull/42/") == 42


def test_pr_number_from_url_with_query() -> None:
    assert pr_number_from_url("https://github.com/owner/repo/pull/123?expand=1") == 123


def test_pr_number_from_url_invalid() -> None:
    assert pr_number_from_url("https://github.com/owner/repo/issues/5") is None


def test_pr_number_from_url_empty() -> None:
    assert pr_number_from_url("") is None


def test_now_iso_returns_string() -> None:
    result = now_iso()
    assert isinstance(result, str)
    assert "T" in result


def test_outcome_record_all_fields() -> None:
    record = OutcomeRecord(
        run_id="abc123",
        item_id="idea:add-caching",
        item_type="idea",
        category="feature",
        outcome="merged",
        pr_number=7,
        pr_url="https://github.com/owner/repo/pull/7",
        title="Add caching",
        opened_at="2026-04-01T00:00:00+00:00",
        closed_at="2026-04-03T00:00:00+00:00",
        recorded_at="2026-04-03T00:00:00+00:00",
    )
    assert record.outcome == "merged"
    assert record.pr_number == 7
    assert record.item_type == "idea"
