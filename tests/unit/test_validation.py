import json
from unittest.mock import MagicMock

import pytest

from sigil.core.config import Config
from sigil.core.llm import StructuredOutputError
from sigil.integrations.github import ExistingIssue
from sigil.pipeline.ideation import FeatureIdea
from sigil.pipeline.maintenance import Finding
from sigil.pipeline.validation import (
    ReviewDecision,
    _apply_decisions,
    _format_existing_issues,
    validate_all,
)


@pytest.fixture(autouse=True)
def _default_mock_structured_completion(monkeypatch):
    async def failing_structured(**kw):
        raise StructuredOutputError("no rebalance in this test")

    monkeypatch.setattr("sigil.pipeline.validation.structured_completion", failing_structured)


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


def _mock_response(decisions, tool_name="review_item"):
    calls = []
    for i, (idx, action, new_disp, reason) in enumerate(decisions):
        args = {"index": idx, "action": action, "reason": reason}
        if new_disp:
            args["new_disposition"] = new_disp
        calls.append(_make_tool_call(f"c{i}", tool_name, args))

    msg = MagicMock()
    msg.tool_calls = calls
    msg.content = None
    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = "stop"
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _plain_stop_response():
    msg = MagicMock()
    msg.tool_calls = None
    msg.content = "done."
    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = "stop"
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _patch_async(monkeypatch, resp):
    stop_resp = _plain_stop_response()
    call_count = {"n": 0}

    async def fake_acompletion(**kw):
        call_count["n"] += 1
        return resp if call_count["n"] == 1 else stop_resp

    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)

    async def _noop_select(*a, **kw):
        return {}

    monkeypatch.setattr("sigil.pipeline.validation.select_memory", _noop_select)
    monkeypatch.setattr("sigil.pipeline.validation.load_working", lambda r: "")


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


async def test_validate_all_unreviewed_defaults(tmp_path, monkeypatch):
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
    assert result.ideas[0].disposition == "pr"


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


def test_format_existing_issues_empty():
    assert _format_existing_issues([]) == ""


def test_format_existing_issues_with_directive():
    issues = [
        ExistingIssue(
            number=10,
            title="Fix flaky test",
            body="The CI test fails intermittently",
            labels=["sigil"],
            is_open=True,
            has_directive=True,
        ),
        ExistingIssue(
            number=11,
            title="Remove dead code",
            body="",
            labels=["sigil"],
            is_open=True,
            has_directive=False,
        ),
    ]
    result = _format_existing_issues(issues)

    assert "[DIRECTIVE] #10: Fix flaky test" in result
    assert "The CI test fails intermittently" in result
    assert "#11: Remove dead code" in result
    assert "[DIRECTIVE]" not in result.split("#11")[1]


def test_format_existing_issues_no_body():
    issues = [
        ExistingIssue(
            number=5,
            title="Stub issue",
            body="",
            labels=["sigil"],
            is_open=True,
            has_directive=False,
        ),
    ]
    result = _format_existing_issues(issues)

    assert "#5: Stub issue" in result
    lines = [line for line in result.splitlines() if line.strip()]
    body_lines = [line for line in lines if line.startswith("  ")]
    assert len(body_lines) == 0


async def test_validate_all_receives_existing_issues(tmp_path, monkeypatch):
    resp = _mock_response(
        [
            (0, "approve", None, "Good"),
        ]
    )

    captured_prompt = {}

    async def fake_acompletion(**kw):
        captured_prompt["messages"] = kw["messages"]
        return resp

    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)

    async def _noop_select(*a, **kw):
        return {}

    monkeypatch.setattr("sigil.pipeline.validation.select_memory", _noop_select)
    monkeypatch.setattr("sigil.pipeline.validation.load_working", lambda r: "")

    existing = [
        ExistingIssue(
            number=99,
            title="Already tracked bug",
            body="Details here",
            labels=["sigil"],
            is_open=True,
            has_directive=False,
        ),
    ]

    config = Config(model="test-model")
    await validate_all(tmp_path, config, [], SAMPLE_IDEAS, existing_issues=existing)

    all_text = " ".join(
        m["content"]
        if isinstance(m["content"], str)
        else " ".join(p.get("text", "") for p in m["content"] if isinstance(p, dict))
        for m in captured_prompt["messages"]
    )
    assert "#99: Already tracked bug" in all_text
    assert "Details here" in all_text


def _rd(action, new_disposition=None, reason="", spec="", relevant_files=None):
    return ReviewDecision(
        action=action,
        new_disposition=new_disposition,
        reason=reason,
        spec=spec,
        relevant_files=relevant_files,
    )


def test_apply_decisions_propagates_relevant_files():
    findings = [SAMPLE_FINDINGS[0]]
    ideas = [SAMPLE_IDEAS[0]]
    decisions = {
        0: _rd(
            "approve",
            reason="good",
            spec="modify src/foo.py",
            relevant_files=["src/foo.py", "tests/test_foo.py"],
        ),
        1: _rd("approve", reason="fine", spec="add retry", relevant_files=["src/api.py"]),
    }
    result = _apply_decisions(decisions, findings, ideas)

    assert result.findings[0].relevant_files == ("src/foo.py", "tests/test_foo.py")
    assert result.findings[0].implementation_spec == "modify src/foo.py"
    assert result.ideas[0].relevant_files == ("src/api.py",)
    assert result.ideas[0].implementation_spec == "add retry"


async def test_validate_all_auto_vetoes_persistent_fingerprints(tmp_path, monkeypatch):
    from sigil.state.chronic import fingerprint
    from sigil.state.persistent import load_persistent_state, save_persistent_state

    state = load_persistent_state(tmp_path)
    fp = fingerprint(SAMPLE_FINDINGS[1])
    state.vetoed_fingerprints.add(fp)
    save_persistent_state(tmp_path, state)

    resp = _mock_response(
        [
            (0, "approve", None, "Good"),
            (1, "approve", None, "Also good"),
            (2, "approve", None, "Fine"),
        ]
    )
    _patch_async(monkeypatch, resp)

    config = Config(model="test-model")
    result = await validate_all(tmp_path, config, SAMPLE_FINDINGS, SAMPLE_IDEAS)

    assert len(result.findings) == 1
    assert result.findings[0].file == "src/foo.py"

    updated_state = load_persistent_state(tmp_path)
    assert fp in updated_state.vetoed_fingerprints
    assert fingerprint(SAMPLE_FINDINGS[0]) not in updated_state.vetoed_fingerprints


async def test_validate_all_records_newly_vetoed_fingerprints(tmp_path, monkeypatch):
    from sigil.state.chronic import fingerprint
    from sigil.state.persistent import load_persistent_state

    resp = _mock_response(
        [
            (0, "approve", None, "Good"),
            (1, "veto", None, "Bad"),
            (2, "veto", None, "Duplicate"),
        ]
    )
    _patch_async(monkeypatch, resp)

    config = Config(model="test-model")
    result = await validate_all(tmp_path, config, SAMPLE_FINDINGS, SAMPLE_IDEAS)

    assert len(result.findings) == 1
    assert len(result.ideas) == 0

    state = load_persistent_state(tmp_path)
    assert fingerprint(SAMPLE_FINDINGS[1]) in state.vetoed_fingerprints
    assert fingerprint(SAMPLE_IDEAS[0]) in state.vetoed_fingerprints


async def test_validate_all_captures_relevant_files(tmp_path, monkeypatch):
    def _make_review_call(call_id, idx, action, reason, spec="", files=None):
        args = {"index": idx, "action": action, "reason": reason}
        if spec:
            args["spec"] = spec
        if files:
            args["relevant_files"] = files
        tc = MagicMock()
        tc.id = call_id
        tc.function.name = "review_item"
        tc.function.arguments = json.dumps(args)
        return tc

    msg = MagicMock()
    msg.tool_calls = [
        _make_review_call("c0", 0, "approve", "good", spec="fix dead code", files=["src/foo.py"]),
        _make_review_call(
            "c1", 1, "approve", "ok", spec="fix security", files=["src/bar.py", "tests/test_bar.py"]
        ),
        _make_review_call("c2", 2, "approve", "fine", spec="add retry", files=["src/api.py"]),
    ]
    msg.content = None
    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = "stop"
    resp = MagicMock()
    resp.choices = [choice]

    _patch_async(monkeypatch, resp)

    config = Config(model="test-model")
    result = await validate_all(tmp_path, config, SAMPLE_FINDINGS, SAMPLE_IDEAS)

    assert result.findings[0].relevant_files == ("src/foo.py",)
    assert result.findings[1].relevant_files == ("src/bar.py", "tests/test_bar.py")
    assert result.ideas[0].relevant_files == ("src/api.py",)
