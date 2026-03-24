import json
from unittest.mock import MagicMock

from sigil.config import Config
from sigil.github import ExistingIssue
from sigil.ideation import FeatureIdea
from sigil.maintenance import Finding
from sigil.validation import (
    _find_disagreements,
    _format_existing_issues,
    validate_all,
)


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


def _patch_async(monkeypatch, resp):
    async def fake_acompletion(**kw):
        return resp

    monkeypatch.setattr("sigil.validation.acompletion", fake_acompletion)

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

    monkeypatch.setattr("sigil.validation.acompletion", fake_acompletion)

    async def _noop_select(*a, **kw):
        return {}

    monkeypatch.setattr("sigil.validation.select_knowledge", _noop_select)
    monkeypatch.setattr("sigil.validation.load_working", lambda r: "")

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

    content = captured_prompt["messages"][0]["content"]
    prompt_text = content[0]["text"] if isinstance(content, list) else content
    assert "#99: Already tracked bug" in prompt_text
    assert "Details here" in prompt_text


def test_find_disagreements_full_agreement():
    decisions_a = {
        0: ("approve", None, "good", ""),
        1: ("veto", None, "bad", ""),
        2: ("adjust", "issue", "risky", ""),
    }
    decisions_b = {
        0: ("approve", None, "fine", ""),
        1: ("veto", None, "terrible", ""),
        2: ("adjust", "issue", "too risky", ""),
    }
    agreed, disagreed = _find_disagreements(decisions_a, decisions_b, 3)

    assert len(agreed) == 3
    assert len(disagreed) == 0


def test_find_disagreements_partial():
    decisions_a = {
        0: ("approve", None, "good", ""),
        1: ("approve", None, "fine", ""),
        2: ("adjust", "issue", "risky", ""),
    }
    decisions_b = {
        0: ("approve", None, "ok", ""),
        1: ("veto", None, "hallucinated", ""),
        2: ("adjust", "pr", "actually safe", ""),
    }
    agreed, disagreed = _find_disagreements(decisions_a, decisions_b, 3)

    assert 0 in agreed
    assert disagreed == {1, 2}


def test_find_disagreements_one_missing():
    decisions_a = {0: ("approve", None, "good", "")}
    decisions_b = {0: ("approve", None, "fine", ""), 1: ("veto", None, "bad", "")}
    agreed, disagreed = _find_disagreements(decisions_a, decisions_b, 3)

    assert 0 in agreed
    assert 1 in agreed
    assert agreed[1] == ("veto", None, "bad", "")
    assert len(disagreed) == 0


async def test_parallel_reviewers_agree(tmp_path, monkeypatch):
    resp = _mock_response(
        [
            (0, "approve", None, "good"),
            (1, "veto", None, "hallucinated"),
            (2, "approve", None, "fine"),
        ]
    )
    _patch_async(monkeypatch, resp)

    call_count = 0

    async def counting_acompletion(**kw):
        nonlocal call_count
        call_count += 1
        return resp

    monkeypatch.setattr("sigil.validation.acompletion", counting_acompletion)

    config = Config(model="test-model", validation_mode="parallel")
    result = await validate_all(tmp_path, config, SAMPLE_FINDINGS, SAMPLE_IDEAS)

    assert call_count == 2
    assert len(result.findings) == 1
    assert result.findings[0].file == "src/foo.py"
    assert len(result.ideas) == 1


async def test_parallel_disagree_runs_arbiter(tmp_path, monkeypatch):
    reviewer_resp_a = _mock_response(
        [
            (0, "approve", None, "good"),
            (1, "approve", None, "valid finding"),
            (2, "approve", None, "fine"),
        ]
    )
    reviewer_resp_b = _mock_response(
        [
            (0, "approve", None, "ok"),
            (1, "veto", None, "hallucinated"),
            (2, "approve", None, "ok"),
        ]
    )
    arbiter_resp = _mock_response(
        [(1, "veto", None, "arbiter agrees with veto")],
        tool_name="resolve_item",
    )

    call_count = 0

    async def sequenced_acompletion(**kw):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return reviewer_resp_a if call_count == 1 else reviewer_resp_b
        return arbiter_resp

    monkeypatch.setattr("sigil.validation.acompletion", sequenced_acompletion)

    async def _noop_select(*a, **kw):
        return {}

    monkeypatch.setattr("sigil.validation.select_knowledge", _noop_select)
    monkeypatch.setattr("sigil.validation.load_working", lambda r: "")

    config = Config(model="test-model", validation_mode="parallel")
    result = await validate_all(tmp_path, config, SAMPLE_FINDINGS, SAMPLE_IDEAS)

    assert call_count == 3
    assert len(result.findings) == 1
    assert result.findings[0].file == "src/foo.py"
    assert len(result.ideas) == 1


async def test_parallel_arbiter_fallback_to_veto(tmp_path, monkeypatch):
    reviewer_resp_a = _mock_response(
        [
            (0, "approve", None, "good"),
            (1, "veto", None, "hallucinated"),
            (2, "approve", None, "fine"),
        ]
    )
    reviewer_resp_b = _mock_response(
        [
            (0, "approve", None, "ok"),
            (1, "approve", None, "seems valid"),
            (2, "approve", None, "ok"),
        ]
    )

    empty_msg = MagicMock()
    empty_msg.tool_calls = None
    empty_msg.content = "I cannot resolve this."
    empty_choice = MagicMock()
    empty_choice.message = empty_msg
    empty_choice.finish_reason = "stop"
    arbiter_resp = MagicMock()
    arbiter_resp.choices = [empty_choice]

    call_count = 0

    async def sequenced_acompletion(**kw):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return reviewer_resp_a if call_count == 1 else reviewer_resp_b
        return arbiter_resp

    monkeypatch.setattr("sigil.validation.acompletion", sequenced_acompletion)

    async def _noop_select(*a, **kw):
        return {}

    monkeypatch.setattr("sigil.validation.select_knowledge", _noop_select)
    monkeypatch.setattr("sigil.validation.load_working", lambda r: "")

    config = Config(model="test-model", validation_mode="parallel")
    result = await validate_all(tmp_path, config, SAMPLE_FINDINGS, SAMPLE_IDEAS)

    assert call_count == 3
    assert len(result.findings) == 1
    assert result.findings[0].file == "src/foo.py"
