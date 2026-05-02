import json

from sigil.pipeline.maintenance import Finding
from sigil.state.chronic import fingerprint
from sigil.state.delta import (
    FindingDelta,
    compute_finding_delta,
    load_previous_fingerprints,
    save_fingerprints,
)


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


class TestComputeFindingDelta:
    def test_first_run_all_new(self):
        findings = [
            _finding(category="dead_code", file="a.py"),
            _finding(category="security", file="b.py"),
        ]
        delta = compute_finding_delta(findings, set())
        assert len(delta.new) == 2
        assert len(delta.resolved) == 0
        assert len(delta.persistent) == 0

    def test_partial_overlap(self):
        findings = [
            _finding(category="dead_code", file="a.py"),
            _finding(category="security", file="b.py"),
        ]
        previous = {fingerprint(_finding(category="dead_code", file="a.py"))}
        delta = compute_finding_delta(findings, previous)
        assert len(delta.new) == 1
        assert len(delta.resolved) == 0
        assert len(delta.persistent) == 1

    def test_all_resolved(self):
        previous = {
            fingerprint(_finding(category="dead_code", file="a.py")),
            fingerprint(_finding(category="security", file="b.py")),
        }
        delta = compute_finding_delta([], previous)
        assert len(delta.new) == 0
        assert len(delta.resolved) == 2
        assert len(delta.persistent) == 0

    def test_full_overlap_all_persistent(self):
        findings = [
            _finding(category="dead_code", file="a.py"),
            _finding(category="security", file="b.py"),
        ]
        previous = {fingerprint(f) for f in findings}
        delta = compute_finding_delta(findings, previous)
        assert len(delta.new) == 0
        assert len(delta.resolved) == 0
        assert len(delta.persistent) == 2

    def test_mixed_new_resolved_persistent(self):
        findings = [
            _finding(category="dead_code", file="a.py"),
            _finding(category="security", file="c.py"),
        ]
        previous = {
            fingerprint(_finding(category="dead_code", file="a.py")),
            fingerprint(_finding(category="tests", file="b.py")),
        }
        delta = compute_finding_delta(findings, previous)
        assert len(delta.new) == 1
        assert len(delta.resolved) == 1
        assert len(delta.persistent) == 1

    def test_empty_current_and_previous(self):
        delta = compute_finding_delta([], set())
        assert len(delta.new) == 0
        assert len(delta.resolved) == 0
        assert len(delta.persistent) == 0


class TestFindingDeltaSummary:
    def test_summary_first_run(self):
        delta = FindingDelta(
            new=["finding:dead_code:a.py", "finding:security:b.py"],
            resolved=[],
            persistent=[],
        )
        summary = delta.summary()
        assert "**NEW:** 2" in summary
        assert "**RESOLVED:** 0" in summary
        assert "**PERSISTENT:** 0" in summary

    def test_summary_with_all_categories(self):
        delta = FindingDelta(
            new=["finding:dead_code:a.py"],
            resolved=["finding:tests:b.py"],
            persistent=["finding:security:c.py"],
        )
        summary = delta.summary()
        assert "**NEW:** 1" in summary
        assert "**RESOLVED:** 1" in summary
        assert "**PERSISTENT:** 1" in summary

    def test_summary_empty(self):
        delta = FindingDelta(new=[], resolved=[], persistent=[])
        summary = delta.summary()
        assert "**NEW:** 0" in summary
        assert "**RESOLVED:** 0" in summary
        assert "**PERSISTENT:** 0" in summary


class TestLoadPreviousFingerprints:
    def test_missing_file_returns_empty_set(self, tmp_path):
        result = load_previous_fingerprints(tmp_path)
        assert result == set()

    def test_existing_file_returns_fingerprints(self, tmp_path):
        sigil_dir = tmp_path / ".sigil" / "memory"
        sigil_dir.mkdir(parents=True)
        data = {"fingerprints": ["finding:dead_code:a.py", "finding:security:b.py"]}
        (sigil_dir / "last-findings.json").write_text(json.dumps(data))
        result = load_previous_fingerprints(tmp_path)
        assert result == {"finding:dead_code:a.py", "finding:security:b.py"}

    def test_corrupted_file_returns_empty_set(self, tmp_path):
        sigil_dir = tmp_path / ".sigil" / "memory"
        sigil_dir.mkdir(parents=True)
        (sigil_dir / "last-findings.json").write_text("not json")
        result = load_previous_fingerprints(tmp_path)
        assert result == set()


class TestSaveFingerprints:
    def test_round_trip(self, tmp_path):
        findings = [
            _finding(category="dead_code", file="a.py"),
            _finding(category="security", file="b.py"),
        ]
        save_fingerprints(tmp_path, findings)
        loaded = load_previous_fingerprints(tmp_path)
        expected = {fingerprint(f) for f in findings}
        assert loaded == expected

    def test_creates_directory(self, tmp_path):
        findings = [_finding()]
        save_fingerprints(tmp_path, findings)
        assert (tmp_path / ".sigil" / "memory" / "last-findings.json").exists()

    def test_overwrites_previous(self, tmp_path):
        findings1 = [_finding(category="dead_code", file="a.py")]
        save_fingerprints(tmp_path, findings1)
        findings2 = [_finding(category="security", file="b.py")]
        save_fingerprints(tmp_path, findings2)
        loaded = load_previous_fingerprints(tmp_path)
        assert loaded == {"finding:security:b.py"}

    def test_empty_findings_saves_empty_list(self, tmp_path):
        save_fingerprints(tmp_path, [])
        loaded = load_previous_fingerprints(tmp_path)
        assert loaded == set()
