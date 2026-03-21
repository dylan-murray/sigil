import json
from unittest.mock import MagicMock

from sigil.config import Config
from sigil.maintenance import Finding
from sigil.validation import validate


def _make_tool_call(call_id, name, args):
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = name
    tc.function.arguments = json.dumps(args)
    return tc


SAMPLE_FINDINGS = [
    Finding(
        category="dead_code",
        file="src/foo.py",
        line=12,
        description="Unused import: os",
        risk="low",
        suggested_fix="Remove it",
        disposition="pr",
        priority=1,
        rationale="Easy fix",
    ),
    Finding(
        category="security",
        file="src/bar.py",
        line=5,
        description="Hardcoded API key",
        risk="high",
        suggested_fix="Use env var",
        disposition="pr",
        priority=2,
        rationale="Important",
    ),
    Finding(
        category="tests",
        file="src/baz.py",
        line=None,
        description="No tests",
        risk="low",
        suggested_fix="Add tests",
        disposition="pr",
        priority=3,
        rationale="Coverage",
    ),
]


def _mock_validation_response(decisions):
    calls = []
    for i, (idx, action, new_disp, reason) in enumerate(decisions):
        args = {"finding_index": idx, "action": action, "reason": reason}
        if new_disp:
            args["new_disposition"] = new_disp
        calls.append(_make_tool_call(f"c{i}", "validate_finding", args))

    msg = MagicMock()
    msg.tool_calls = calls
    msg.content = None
    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = "stop"
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def test_validate_approve_all(tmp_path, monkeypatch):
    resp = _mock_validation_response(
        [
            (0, "approve", None, "Looks good"),
            (1, "approve", None, "Correct"),
            (2, "approve", None, "Fine"),
        ]
    )

    monkeypatch.setattr("sigil.validation.litellm.completion", lambda **kw: resp)
    monkeypatch.setattr("sigil.validation.select_knowledge", lambda *a, **kw: {})
    monkeypatch.setattr("sigil.validation.load_working", lambda r: "")

    config = Config(model="test-model")
    result = validate(tmp_path, config, SAMPLE_FINDINGS)

    assert len(result) == 3
    assert result[0].disposition == "pr"
    assert result[1].disposition == "pr"


def test_validate_adjust_disposition(tmp_path, monkeypatch):
    resp = _mock_validation_response(
        [
            (0, "approve", None, "Fine"),
            (1, "adjust", "issue", "Too risky for auto-fix"),
            (2, "approve", None, "Fine"),
        ]
    )

    monkeypatch.setattr("sigil.validation.litellm.completion", lambda **kw: resp)
    monkeypatch.setattr("sigil.validation.select_knowledge", lambda *a, **kw: {})
    monkeypatch.setattr("sigil.validation.load_working", lambda r: "")

    config = Config(model="test-model")
    result = validate(tmp_path, config, SAMPLE_FINDINGS)

    assert len(result) == 3
    assert result[1].disposition == "issue"


def test_validate_veto_removes(tmp_path, monkeypatch):
    resp = _mock_validation_response(
        [
            (0, "approve", None, "Good"),
            (1, "veto", None, "Hallucinated file path"),
            (2, "approve", None, "Good"),
        ]
    )

    monkeypatch.setattr("sigil.validation.litellm.completion", lambda **kw: resp)
    monkeypatch.setattr("sigil.validation.select_knowledge", lambda *a, **kw: {})
    monkeypatch.setattr("sigil.validation.load_working", lambda r: "")

    config = Config(model="test-model")
    result = validate(tmp_path, config, SAMPLE_FINDINGS)

    assert len(result) == 2
    assert all(f.file != "src/bar.py" for f in result)


def test_validate_unreviewed_defaults_to_issue(tmp_path, monkeypatch):
    resp = _mock_validation_response(
        [
            (0, "approve", None, "Good"),
        ]
    )

    monkeypatch.setattr("sigil.validation.litellm.completion", lambda **kw: resp)
    monkeypatch.setattr("sigil.validation.select_knowledge", lambda *a, **kw: {})
    monkeypatch.setattr("sigil.validation.load_working", lambda r: "")

    config = Config(model="test-model")
    result = validate(tmp_path, config, SAMPLE_FINDINGS)

    assert len(result) == 3
    assert result[0].disposition == "pr"
    assert result[1].disposition == "issue"
    assert result[2].disposition == "issue"


def test_validate_empty_findings(tmp_path, monkeypatch):
    config = Config(model="test-model")
    assert validate(tmp_path, config, []) == []
