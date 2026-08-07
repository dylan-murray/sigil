import json

from sigil.pipeline.models import FeatureIdea, Finding, ReviewDecision
from sigil.state.chronic import fingerprint
from sigil.state.vetoes import (
    MAX_VETOES,
    VetoRecord,
    format_veto_context,
    is_vetoed,
    load_vetoes,
    record_vetoes,
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


def _decision(**overrides) -> ReviewDecision:
    defaults = {
        "action": "veto",
        "new_disposition": None,
        "reason": "Hallucinated file",
    }
    defaults.update(overrides)
    return ReviewDecision(**defaults)


def _write_vetoes(tmp_path, records: list[VetoRecord]) -> None:
    path = tmp_path / ".sigil" / "vetoes.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in records:
            f.write(
                json.dumps(
                    json.loads(
                        json.dumps(
                            {
                                "fingerprint": r.fingerprint,
                                "reason": r.reason,
                                "action": r.action,
                                "timestamp": r.timestamp,
                                "item_type": r.item_type,
                                "category": r.category,
                                "title": r.title,
                                "file": r.file,
                            }
                        )
                    )
                )
                + "\n"
            )


class TestRecordVetoes:
    def test_records_vetoed_findings(self, tmp_path):
        findings = [_finding(), _finding(category="security", file="auth.py")]
        ideas = [_idea()]
        decisions = {
            0: _decision(action="veto", reason="Hallucinated file"),
            1: _decision(action="approve", reason="Good"),
            2: _decision(action="veto", reason="Duplicate"),
        }
        record_vetoes(tmp_path, findings, ideas, decisions)

        vetoes = load_vetoes(tmp_path)
        assert len(vetoes) == 2
        assert vetoes[0].fingerprint == fingerprint(findings[0])
        assert vetoes[0].action == "veto"
        assert vetoes[0].item_type == "finding"
        assert vetoes[0].category == "dead_code"
        assert vetoes[0].file == "utils.py"
        assert vetoes[1].fingerprint == fingerprint(ideas[0])
        assert vetoes[1].item_type == "idea"
        assert vetoes[1].title == "Add Caching Layer"

    def test_records_skip_adjusted_items(self, tmp_path):
        findings = [_finding()]
        ideas = []
        decisions = {
            0: _decision(action="adjust", new_disposition="skip", reason="Too vague"),
        }
        record_vetoes(tmp_path, findings, ideas, decisions)

        vetoes = load_vetoes(tmp_path)
        assert len(vetoes) == 1
        assert vetoes[0].action == "adjust"
        assert vetoes[0].reason == "Too vague"

    def test_skips_approved_items(self, tmp_path):
        findings = [_finding()]
        ideas = [_idea()]
        decisions = {
            0: _decision(action="approve", reason="Good"),
            1: _decision(action="adjust", new_disposition="issue", reason="Risky"),
        }
        record_vetoes(tmp_path, findings, ideas, decisions)

        vetoes = load_vetoes(tmp_path)
        assert len(vetoes) == 0

    def test_skips_unreviewed_items(self, tmp_path):
        findings = [_finding()]
        ideas = []
        decisions = {}
        record_vetoes(tmp_path, findings, ideas, decisions)

        vetoes = load_vetoes(tmp_path)
        assert len(vetoes) == 0

    def test_appends_to_existing_file(self, tmp_path):
        findings = [_finding()]
        decisions = {0: _decision(reason="First veto")}
        record_vetoes(tmp_path, findings, [], decisions)

        decisions2 = {0: _decision(reason="Second veto")}
        record_vetoes(tmp_path, findings, [], decisions2)

        vetoes = load_vetoes(tmp_path)
        assert len(vetoes) == 2

    def test_creates_sigil_dir(self, tmp_path):
        repo = tmp_path / "subdir"
        repo.mkdir()
        findings = [_finding()]
        decisions = {0: _decision()}
        record_vetoes(repo, findings, [], decisions)

        assert (repo / ".sigil" / "vetoes.jsonl").exists()


class TestLoadVetoes:
    def test_returns_empty_when_no_file(self, tmp_path):
        assert load_vetoes(tmp_path) == []

    def test_filters_by_ttl(self, tmp_path):
        old_record = VetoRecord(
            fingerprint="finding:dead_code:old.py",
            reason="Old veto",
            action="veto",
            timestamp="2020-01-01T00:00:00+00:00",
            item_type="finding",
            category="dead_code",
            title="",
            file="old.py",
        )
        recent_record = VetoRecord(
            fingerprint="finding:dead_code:new.py",
            reason="Recent veto",
            action="veto",
            timestamp="2099-06-01T00:00:00+00:00",
            item_type="finding",
            category="dead_code",
            title="",
            file="new.py",
        )
        _write_vetoes(tmp_path, [old_record, recent_record])

        vetoes = load_vetoes(tmp_path, ttl_days=90)
        assert len(vetoes) == 1
        assert vetoes[0].fingerprint == "finding:dead_code:new.py"

    def test_returns_all_within_ttl(self, tmp_path):
        recent = VetoRecord(
            fingerprint="finding:tests:app.py",
            reason="Recent",
            action="veto",
            timestamp="2099-01-01T00:00:00+00:00",
            item_type="finding",
            category="tests",
            title="",
            file="app.py",
        )
        _write_vetoes(tmp_path, [recent])

        vetoes = load_vetoes(tmp_path, ttl_days=90)
        assert len(vetoes) == 1

    def test_prunes_over_max_vetoes(self, tmp_path):
        records = []
        for i in range(MAX_VETOES + 50):
            records.append(
                VetoRecord(
                    fingerprint=f"finding:dead_code:file{i}.py",
                    reason=f"Veto {i}",
                    action="veto",
                    timestamp="2099-01-01T00:00:00+00:00",
                    item_type="finding",
                    category="dead_code",
                    title="",
                    file=f"file{i}.py",
                )
            )
        _write_vetoes(tmp_path, records)

        vetoes = load_vetoes(tmp_path, ttl_days=9999)
        assert len(vetoes) == MAX_VETOES
        assert vetoes[0].fingerprint == "finding:dead_code:file50.py"
        assert vetoes[-1].fingerprint == f"finding:dead_code:file{MAX_VETOES + 49}.py"

    def test_skips_corrupt_lines(self, tmp_path):
        path = tmp_path / ".sigil" / "vetoes.jsonl"
        path.parent.mkdir(parents=True)
        good = json.dumps(
            {
                "fingerprint": "finding:dead_code:app.py",
                "reason": "Good veto",
                "action": "veto",
                "timestamp": "2099-01-01T00:00:00+00:00",
                "item_type": "finding",
                "category": "dead_code",
                "title": "",
                "file": "app.py",
            }
        )
        path.write_text(f"{good}\nNOT JSON\n{good}\n")

        vetoes = load_vetoes(tmp_path, ttl_days=9999)
        assert len(vetoes) == 2


class TestIsVetoed:
    def test_matches_finding_fingerprint(self):
        finding = _finding()
        vetoes = [
            VetoRecord(
                fingerprint=fingerprint(finding),
                reason="Hallucinated",
                action="veto",
                timestamp="2099-01-01T00:00:00+00:00",
                item_type="finding",
                category="dead_code",
                title="",
                file="utils.py",
            ),
        ]
        result = is_vetoed(finding, vetoes)
        assert result is not None
        assert result.reason == "Hallucinated"

    def test_matches_idea_fingerprint(self):
        idea = _idea()
        vetoes = [
            VetoRecord(
                fingerprint=fingerprint(idea),
                reason="Too vague",
                action="veto",
                timestamp="2099-01-01T00:00:00+00:00",
                item_type="idea",
                category="",
                title="Add Caching Layer",
                file="",
            ),
        ]
        result = is_vetoed(idea, vetoes)
        assert result is not None
        assert result.reason == "Too vague"

    def test_returns_none_for_non_vetoed(self):
        finding = _finding()
        vetoes = [
            VetoRecord(
                fingerprint="idea:some-other-thing",
                reason="Different",
                action="veto",
                timestamp="2099-01-01T00:00:00+00:00",
                item_type="idea",
                category="",
                title="Other idea",
                file="",
            ),
        ]
        assert is_vetoed(finding, vetoes) is None

    def test_returns_none_for_empty_list(self):
        finding = _finding()
        assert is_vetoed(finding, []) is None


class TestFormatVetoContext:
    def test_returns_empty_string_for_empty_list(self):
        assert format_veto_context([]) == ""

    def test_formats_findings(self):
        vetoes = [
            VetoRecord(
                fingerprint="finding:dead_code:utils.py",
                reason="File does not exist",
                action="veto",
                timestamp="2099-01-01T00:00:00+00:00",
                item_type="finding",
                category="dead_code",
                title="",
                file="utils.py",
            ),
        ]
        result = format_veto_context(vetoes)
        assert "## Previously Vetoed Items" in result
        assert "### Vetoed Findings" in result
        assert "**dead_code**" in result
        assert "`utils.py`" in result
        assert "File does not exist" in result

    def test_formats_ideas(self):
        vetoes = [
            VetoRecord(
                fingerprint="idea:add-caching-layer",
                reason="Too vague",
                action="veto",
                timestamp="2099-01-01T00:00:00+00:00",
                item_type="idea",
                category="",
                title="Add Caching Layer",
                file="",
            ),
        ]
        result = format_veto_context(vetoes)
        assert "### Vetoed Ideas" in result
        assert "**Add Caching Layer**" in result
        assert "Too vague" in result

    def test_formats_mixed_types(self):
        vetoes = [
            VetoRecord(
                fingerprint="finding:dead_code:app.py",
                reason="Duplicate",
                action="veto",
                timestamp="2099-01-01T00:00:00+00:00",
                item_type="finding",
                category="dead_code",
                title="",
                file="app.py",
            ),
            VetoRecord(
                fingerprint="idea:retry-logic",
                reason="Already implemented",
                action="adjust",
                timestamp="2099-01-01T00:00:00+00:00",
                item_type="idea",
                category="",
                title="Add retry logic",
                file="",
            ),
        ]
        result = format_veto_context(vetoes)
        assert "### Vetoed Findings" in result
        assert "### Vetoed Ideas" in result
        assert "action: veto" in result
        assert "action: adjust" in result

    def test_includes_guidance_text(self):
        vetoes = [
            VetoRecord(
                fingerprint="finding:dead_code:app.py",
                reason="Duplicate",
                action="veto",
                timestamp="2099-01-01T00:00:00+00:00",
                item_type="finding",
                category="dead_code",
                title="",
                file="app.py",
            ),
        ]
        result = format_veto_context(vetoes)
        assert "Do NOT re-propose" in result
        assert "substantively different approach" in result


class TestRoundTrip:
    def test_record_then_load_then_is_vetoed(self, tmp_path):
        finding = _finding()
        idea = _idea()
        findings = [finding]
        ideas = [idea]
        decisions = {
            0: _decision(action="veto", reason="Hallucinated file"),
            1: _decision(action="adjust", new_disposition="skip", reason="Too vague"),
        }

        record_vetoes(tmp_path, findings, ideas, decisions)
        vetoes = load_vetoes(tmp_path, ttl_days=9999)

        assert is_vetoed(finding, vetoes) is not None
        assert is_vetoed(finding, vetoes).reason == "Hallucinated file"
        assert is_vetoed(idea, vetoes) is not None
        assert is_vetoed(idea, vetoes).reason == "Too vague"

    def test_approved_item_not_vetoed(self, tmp_path):
        finding = _finding()
        decisions = {0: _decision(action="approve", reason="Good")}
        record_vetoes(tmp_path, [finding], [], decisions)

        vetoes = load_vetoes(tmp_path, ttl_days=9999)
        assert is_vetoed(finding, vetoes) is None

    def test_vetoed_finding_suppressed_on_next_run(self, tmp_path):
        finding = _finding()
        decisions = {0: _decision(action="veto", reason="Not real")}
        record_vetoes(tmp_path, [finding], [], decisions)

        vetoes = load_vetoes(tmp_path, ttl_days=9999)
        same_finding = _finding()
        assert is_vetoed(same_finding, vetoes) is not None

        different_finding = _finding(category="security", file="auth.py")
        assert is_vetoed(different_finding, vetoes) is None
