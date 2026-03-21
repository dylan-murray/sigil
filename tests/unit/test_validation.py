import json
from unittest.mock import MagicMock

from sigil.config import Config
from sigil.ideation import FeatureIdea
from sigil.maintenance import Finding
from sigil.validation import validate_all


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
]

SAMPLE_IDEAS = [
    FeatureIdea(
        title="Add retry logic",
        description="Implement retries for flaky API calls",
        rationale="Improves reliability",
        complexity="small",
        disposition="pr",
        priority=3,
    ),
]


def _mock_response(decisions):
    calls = []
    for i, (idx, action, new_disp, reason) in enumerate(decisions):
        args = {"index": idx, "action": action, "reason": reason}
        if new_disp:
            args["new_disposition"] = new_disp
        calls.append(_make_tool_call(f"c{i}", "review_item", args))

    msg = MagicMock()
    msg.tool_calls = calls
    msg.content = None
    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = "stop"
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _patch_async(monkeypatch, resp):
    async def fake_acompletion(**kw):
        return resp

    monkeypatch.setattr("sigil.validation.litellm.acompletion", fake_acompletion)

    async def _noop_select(*a, **kw):
        return {}

    monkeypatch.setattr("sigil.validation.select_knowledge", _noop_select)
    monkeypatch.setattr("sigil.validation.load_working", lambda r: "")


async def test_validate_all_approve_all(tmp_path, monkeypatch):
    resp = _mock_response(
        [
            (0, "approve", None, "Looks good"),
            (1, "approve", None, "Correct"),
            (2, "approve", None, "Fine"),
        ]
    )
    _patch_async(monkeypatch, resp)

    config = Config(model="test-model")
    result = await validate_all(tmp_path, config, SAMPLE_FINDINGS, SAMPLE_IDEAS)

    assert len(result.findings) == 2
    assert len(result.ideas) == 1
    assert result.findings[0].disposition == "pr"
    assert result.ideas[0].title == "Add retry logic"


async def test_validate_all_adjust_disposition(tmp_path, monkeypatch):
    resp = _mock_response(
        [
            (0, "approve", None, "Fine"),
            (1, "adjust", "issue", "Too risky for auto-fix"),
            (2, "adjust", "issue", "Too complex"),
        ]
    )
    _patch_async(monkeypatch, resp)

    config = Config(model="test-model")
    result = await validate_all(tmp_path, config, SAMPLE_FINDINGS, SAMPLE_IDEAS)

    assert result.findings[1].disposition == "issue"
    assert result.ideas[0].disposition == "issue"


async def test_validate_all_veto_removes(tmp_path, monkeypatch):
    resp = _mock_response(
        [
            (0, "approve", None, "Good"),
            (1, "veto", None, "Hallucinated file path"),
            (2, "veto", None, "Duplicate of finding 1"),
        ]
    )
    _patch_async(monkeypatch, resp)

    config = Config(model="test-model")
    result = await validate_all(tmp_path, config, SAMPLE_FINDINGS, SAMPLE_IDEAS)

    assert len(result.findings) == 1
    assert result.findings[0].file == "src/foo.py"
    assert len(result.ideas) == 0


async def test_validate_all_unreviewed_findings_default_to_issue(tmp_path, monkeypatch):
    resp = _mock_response(
        [
            (0, "approve", None, "Good"),
        ]
    )
    _patch_async(monkeypatch, resp)

    config = Config(model="test-model")
    result = await validate_all(tmp_path, config, SAMPLE_FINDINGS, SAMPLE_IDEAS)

    assert result.findings[0].disposition == "pr"
    assert result.findings[1].disposition == "issue"
    assert len(result.ideas) == 1


async def test_validate_all_empty(tmp_path, monkeypatch):
    config = Config(model="test-model")
    result = await validate_all(tmp_path, config, [], [])
    assert result.findings == []
    assert result.ideas == []


async def test_validate_all_findings_only(tmp_path, monkeypatch):
    resp = _mock_response(
        [
            (0, "approve", None, "Good"),
            (1, "approve", None, "Good"),
        ]
    )
    _patch_async(monkeypatch, resp)

    config = Config(model="test-model")
    result = await validate_all(tmp_path, config, SAMPLE_FINDINGS, [])

    assert len(result.findings) == 2
    assert result.ideas == []


async def test_validate_all_ideas_only(tmp_path, monkeypatch):
    resp = _mock_response(
        [
            (0, "approve", None, "Good"),
        ]
    )
    _patch_async(monkeypatch, resp)

    config = Config(model="test-model")
    result = await validate_all(tmp_path, config, [], SAMPLE_IDEAS)

    assert result.findings == []
    assert len(result.ideas) == 1
