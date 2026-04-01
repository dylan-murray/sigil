from unittest.mock import patch

from sigil.state.attempts import AttemptRecord
from sigil.state.doctor import diagnose_config


def _record(**overrides) -> AttemptRecord:
    defaults = {
        "run_id": "run1",
        "timestamp": "2026-03-23T00:00:00Z",
        "item_type": "finding",
        "item_id": "finding:dead_code:src/foo.py",
        "category": "dead_code",
        "complexity": "",
        "approach": "fix",
        "model": "gpt-4o",
        "retries": 0,
        "outcome": "post_hook",
        "tokens_used": 100,
        "duration_s": 1.0,
        "failure_detail": "ruff failed",
    }
    defaults.update(overrides)
    return AttemptRecord(**defaults)


def test_diagnose_config_flags_chronic_directory(tmp_path):
    records = [
        _record(item_id="finding:tests:src/foo.py", outcome="success"),
        _record(item_id="finding:tests:src/foo.py"),
        _record(item_id="finding:tests:src/foo.py"),
        _record(item_id="finding:tests:src/foo.py"),
        _record(item_id="finding:tests:src/foo.py"),
        _record(item_id="finding:tests:src/foo.py"),
    ]
    with patch("sigil.state.doctor.read_attempts", return_value=records):
        findings = diagnose_config(tmp_path)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.category == "config_tuning"
    assert finding.file == ".sigil/config.yml"
    assert finding.disposition == "pr"
    assert "src" in finding.description
    assert "ignore patterns" in finding.implementation_spec


def test_diagnose_config_requires_minimum_attempts(tmp_path):
    records = [_record() for _ in range(4)]
    with patch("sigil.state.doctor.read_attempts", return_value=records):
        findings = diagnose_config(tmp_path)

    assert findings == []


def test_diagnose_config_requires_failure_rate_threshold(tmp_path):
    records = [_record() for _ in range(5)] + [_record(outcome="success") for _ in range(5)]
    with patch("sigil.state.doctor.read_attempts", return_value=records):
        findings = diagnose_config(tmp_path)

    assert findings == []
