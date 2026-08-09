import json
from unittest.mock import MagicMock

from sigil.core.config import Config
from sigil.pipeline.maintenance import (
    analyze,
    filter_stale_findings,
    is_finding_stale,
)
from sigil.pipeline.models import Finding


def _make_tool_call(call_id, name, args):
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = name
    tc.function.arguments = json.dumps(args)
    return tc


def _mock_response_with_findings(findings_args):
    calls = []
    for i, args in enumerate(findings_args):
        calls.append(_make_tool_call(f"call_{i}", "report_finding", args))

    msg = MagicMock()
    msg.tool_calls = calls
    msg.content = None
    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = "tool_calls"
    resp1 = MagicMock()
    resp1.choices = [choice]

    msg2 = MagicMock()
    msg2.tool_calls = None
    msg2.content = "Done."
    choice2 = MagicMock()
    choice2.message = msg2
    choice2.finish_reason = "stop"
    resp2 = MagicMock()
    resp2.choices = [choice2]

    return [resp1, resp2]


async def test_analyze_collects_findings(tmp_path, monkeypatch):
    findings_args = [
        {
            "category": "dead_code",
            "file": "src/foo.py",
            "line": 12,
            "description": "Unused import: os",
            "risk": "low",
            "suggested_fix": "Remove it",
            "disposition": "pr",
            "priority": 1,
            "rationale": "Easy fix",
        },
        {
            "category": "security",
            "file": "src/bar.py",
            "line": 5,
            "description": "Hardcoded API key",
            "risk": "high",
            "suggested_fix": "Use env var",
            "disposition": "issue",
            "priority": 2,
            "rationale": "Needs human review",
        },
    ]

    responses = _mock_response_with_findings(findings_args)
    call_count = {"n": 0}

    async def fake_acompletion(**kwargs):
        idx = call_count["n"]
        call_count["n"] += 1
        return responses[idx]

    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)

    async def _noop_select(*a, **kw):
        return {}

    monkeypatch.setattr("sigil.pipeline.maintenance.select_memory", _noop_select)
    monkeypatch.setattr("sigil.pipeline.maintenance.load_working", lambda r: "")

    config = Config(model="test-model")
    findings = await analyze(tmp_path, config)

    assert len(findings) == 2
    assert findings[0].category == "dead_code"
    assert findings[0].risk == "low"
    assert findings[0].disposition == "pr"
    assert findings[0].priority == 1
    assert findings[1].category == "security"
    assert findings[1].disposition == "issue"
    assert findings[1].priority == 2


async def test_analyze_no_findings(tmp_path, monkeypatch):
    msg = MagicMock()
    msg.tool_calls = None
    msg.content = "Nothing found."
    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = "stop"
    resp = MagicMock()
    resp.choices = [choice]

    async def fake_acompletion(**kw):
        return resp

    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)

    async def _noop_select(*a, **kw):
        return {}

    monkeypatch.setattr("sigil.pipeline.maintenance.select_memory", _noop_select)
    monkeypatch.setattr("sigil.pipeline.maintenance.load_working", lambda r: "")

    config = Config(model="test-model")
    assert await analyze(tmp_path, config) == []


async def test_analyze_defaults_invalid_disposition(tmp_path, monkeypatch):
    findings_args = [
        {
            "category": "docs",
            "file": "README.md",
            "description": "Broken link",
            "risk": "banana",
            "suggested_fix": "Fix it",
            "disposition": "yolo",
            "priority": 1,
            "rationale": "Whatever",
        },
    ]

    responses = _mock_response_with_findings(findings_args)
    call_count = {"n": 0}

    async def fake_acompletion(**kwargs):
        idx = call_count["n"]
        call_count["n"] += 1
        return responses[idx]

    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)

    async def _noop_select(*a, **kw):
        return {}

    monkeypatch.setattr("sigil.pipeline.maintenance.select_memory", _noop_select)
    monkeypatch.setattr("sigil.pipeline.maintenance.load_working", lambda r: "")

    config = Config(model="test-model")
    findings = await analyze(tmp_path, config)

    assert len(findings) == 1
    assert findings[0].disposition == "issue"
    assert findings[0].risk == "medium"


async def test_analyze_sorts_by_priority(tmp_path, monkeypatch):
    findings_args = [
        {
            "category": "tests",
            "file": "a.py",
            "description": "No tests",
            "risk": "low",
            "suggested_fix": "Add tests",
            "disposition": "pr",
            "priority": 3,
            "rationale": "Low priority",
        },
        {
            "category": "security",
            "file": "b.py",
            "description": "SQL injection",
            "risk": "high",
            "suggested_fix": "Parameterize",
            "disposition": "issue",
            "priority": 1,
            "rationale": "Critical",
        },
    ]

    responses = _mock_response_with_findings(findings_args)
    call_count = {"n": 0}

    async def fake_acompletion(**kwargs):
        idx = call_count["n"]
        call_count["n"] += 1
        return responses[idx]

    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)

    async def _noop_select(*a, **kw):
        return {}

    monkeypatch.setattr("sigil.pipeline.maintenance.select_memory", _noop_select)
    monkeypatch.setattr("sigil.pipeline.maintenance.load_working", lambda r: "")

    config = Config(model="test-model")
    findings = await analyze(tmp_path, config)

    assert findings[0].priority == 1
    assert findings[0].category == "security"
    assert findings[1].priority == 3


def _make_raw_tool_call(call_id, name, raw_arguments):
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = name
    tc.function.arguments = raw_arguments
    return tc


def _stop_response():
    msg = MagicMock()
    msg.tool_calls = None
    msg.content = "Done."
    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = "stop"
    resp = MagicMock()
    resp.choices = [choice]
    return resp


async def test_analyze_invalid_json_arguments(tmp_path, monkeypatch):
    tc = _make_raw_tool_call("call_bad", "report_finding", "not valid json{{{")
    msg = MagicMock()
    msg.tool_calls = [tc]
    msg.content = None
    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = "tool_calls"
    resp_bad = MagicMock()
    resp_bad.choices = [choice]

    responses = [resp_bad, _stop_response()]
    call_count = {"n": 0}

    async def fake_acompletion(**kwargs):
        idx = call_count["n"]
        call_count["n"] += 1
        return responses[idx]

    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)

    async def _noop_select(*a, **kw):
        return {}

    monkeypatch.setattr("sigil.pipeline.maintenance.select_memory", _noop_select)
    monkeypatch.setattr("sigil.pipeline.maintenance.load_working", lambda r: "")

    config = Config(model="test-model")
    findings = await analyze(tmp_path, config)

    assert findings == []
    assert call_count["n"] == 2


async def test_analyze_read_file_outside_repo(tmp_path, monkeypatch):
    tc = _make_tool_call("call_escape", "read_file", {"file": "../../etc/passwd"})
    msg = MagicMock()
    msg.tool_calls = [tc]
    msg.content = None
    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = "tool_calls"
    resp1 = MagicMock()
    resp1.choices = [choice]

    responses = [resp1, _stop_response()]
    call_count = {"n": 0}
    captured_messages = []

    async def fake_acompletion(**kwargs):
        idx = call_count["n"]
        call_count["n"] += 1
        captured_messages.append(kwargs.get("messages", []))
        return responses[idx]

    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)

    async def _noop_select(*a, **kw):
        return {}

    monkeypatch.setattr("sigil.pipeline.maintenance.select_memory", _noop_select)
    monkeypatch.setattr("sigil.pipeline.maintenance.load_working", lambda r: "")

    config = Config(model="test-model")
    findings = await analyze(tmp_path, config)

    assert findings == []
    tool_responses = [
        m
        for msgs in captured_messages
        for m in msgs
        if isinstance(m, dict) and m.get("role") == "tool"
    ]
    assert any("Access denied" in m["content"] for m in tool_responses)


async def test_analyze_file_truncation(tmp_path, monkeypatch):
    big_file = tmp_path / "big.py"
    big_file.write_text("\n".join(f"line_{i}" for i in range(5000)))

    tc_read = _make_tool_call("call_read", "read_file", {"file": "big.py"})
    msg1 = MagicMock()
    msg1.tool_calls = [tc_read]
    msg1.content = None
    choice1 = MagicMock()
    choice1.message = msg1
    choice1.finish_reason = "tool_calls"
    resp1 = MagicMock()
    resp1.choices = [choice1]

    responses = [resp1, _stop_response()]
    call_count = {"n": 0}
    captured_messages = []

    async def fake_acompletion(**kwargs):
        idx = call_count["n"]
        call_count["n"] += 1
        captured_messages.append(kwargs.get("messages", []))
        return responses[idx]

    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)
    monkeypatch.setattr("sigil.core.tools.read_file", lambda p: p.read_text())

    async def _noop_select(*a, **kw):
        return {}

    monkeypatch.setattr("sigil.pipeline.maintenance.select_memory", _noop_select)
    monkeypatch.setattr("sigil.pipeline.maintenance.load_working", lambda r: "")

    config = Config(model="test-model")
    await analyze(tmp_path, config)

    tool_responses = [
        m
        for msgs in captured_messages
        for m in msgs
        if isinstance(m, dict) and m.get("role") == "tool"
    ]
    assert any("truncated" in m["content"] for m in tool_responses)
    truncated_content = next(m["content"] for m in tool_responses if "truncated" in m["content"])
    content_lines = [
        line for line in truncated_content.splitlines() if not line.startswith("[truncated")
    ]
    assert len(content_lines) <= 2000
    assert "offset=2001" in truncated_content


# --- Staleness tests ---


def _make_finding(**overrides) -> Finding:
    defaults = dict(
        category="dead_code",
        file="src/foo.py",
        line=10,
        description="Unused import",
        risk="low",
        suggested_fix="Remove it",
        disposition="pr",
        priority=1,
        rationale="Easy fix",
    )
    defaults.update(overrides)
    return Finding(**defaults)


async def test_is_finding_stale_file_deleted(tmp_path):
    finding = _make_finding(file="nonexistent.py")
    is_stale, reason = await is_finding_stale(finding, tmp_path)
    assert is_stale is True
    assert reason == "file_deleted"


async def test_is_finding_stale_line_out_of_range(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("line1\nline2\nline3\n")
    finding = _make_finding(file="src/foo.py", line=100)
    is_stale, reason = await is_finding_stale(finding, tmp_path)
    assert is_stale is True
    assert reason == "line_out_of_range"


async def test_is_finding_stale_line_in_range_no_git_changes(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("line1\nline2\nline3\n")
    finding = _make_finding(file="src/foo.py", line=2)
    is_stale, reason = await is_finding_stale(finding, tmp_path, last_head=None)
    assert is_stale is False
    assert reason == ""


async def test_is_finding_stale_lines_changed_at_finding_line(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    lines = [f"line{i}" for i in range(1, 21)]
    (tmp_path / "src" / "foo.py").write_text("\n".join(lines) + "\n")
    finding = _make_finding(file="src/foo.py", line=10)

    async def fake_arun(cmd, **kwargs):
        return 0, "@@ -8,3 +8,3 @@\n context\n-old\n+new\n context2", ""

    monkeypatch.setattr("sigil.pipeline.maintenance.arun", fake_arun)
    is_stale, reason = await is_finding_stale(finding, tmp_path, last_head="abc123")
    assert is_stale is True
    assert reason == "lines_changed"


async def test_is_finding_stale_lines_changed_elsewhere(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("line1\nline2\nline3\n")
    finding = _make_finding(file="src/foo.py", line=2)

    async def fake_arun(cmd, **kwargs):
        return 0, "@@ -50,3 +50,3 @@\n context\n-old\n+new\n context2", ""

    monkeypatch.setattr("sigil.pipeline.maintenance.arun", fake_arun)
    is_stale, reason = await is_finding_stale(finding, tmp_path, last_head="abc123")
    assert is_stale is False
    assert reason == ""


async def test_is_finding_stale_no_line_number(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("line1\nline2\nline3\n")
    finding = _make_finding(file="src/foo.py", line=None)
    is_stale, reason = await is_finding_stale(finding, tmp_path)
    assert is_stale is False
    assert reason == ""


async def test_is_finding_stale_no_line_number_deleted_file(tmp_path):
    finding = _make_finding(file="nonexistent.py", line=None)
    is_stale, reason = await is_finding_stale(finding, tmp_path)
    assert is_stale is True
    assert reason == "file_deleted"


async def test_is_finding_stale_no_index_skips_diff(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("line1\nline2\nline3\n")
    finding = _make_finding(file="src/foo.py", line=2)
    arun_calls = []

    async def fake_arun(cmd, **kwargs):
        arun_calls.append(cmd)
        return 1, "", "error"

    monkeypatch.setattr("sigil.pipeline.maintenance.arun", fake_arun)
    is_stale, reason = await is_finding_stale(finding, tmp_path, last_head=None)
    assert is_stale is False
    assert reason == ""
    assert len(arun_calls) == 0


async def test_is_finding_stale_git_diff_fails(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("line1\nline2\nline3\n")
    finding = _make_finding(file="src/foo.py", line=2)

    async def fake_arun(cmd, **kwargs):
        return 1, "", "git error"

    monkeypatch.setattr("sigil.pipeline.maintenance.arun", fake_arun)
    is_stale, reason = await is_finding_stale(finding, tmp_path, last_head="abc123")
    assert is_stale is False
    assert reason == ""


async def test_is_finding_stale_empty_diff(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("line1\nline2\nline3\n")
    finding = _make_finding(file="src/foo.py", line=2)

    async def fake_arun(cmd, **kwargs):
        return 0, "", ""

    monkeypatch.setattr("sigil.pipeline.maintenance.arun", fake_arun)
    is_stale, reason = await is_finding_stale(finding, tmp_path, last_head="abc123")
    assert is_stale is False
    assert reason == ""


async def test_filter_stale_findings_splits_correctly(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "exists.py").write_text("line1\nline2\nline3\n")

    fresh_finding = _make_finding(file="src/exists.py", line=1, priority=1)
    deleted_finding = _make_finding(file="src/deleted.py", line=1, priority=2)
    out_of_range_finding = _make_finding(file="src/exists.py", line=999, priority=3)

    async def fake_arun(cmd, **kwargs):
        return 0, "", ""

    monkeypatch.setattr("sigil.pipeline.maintenance.arun", fake_arun)

    fresh, stale = await filter_stale_findings(
        [fresh_finding, deleted_finding, out_of_range_finding],
        tmp_path,
    )

    assert len(fresh) == 1
    assert len(stale) == 2
    assert fresh[0].file == "src/exists.py"
    assert fresh[0].priority == 1
    assert stale[0].staleness_reason == "file_deleted"
    assert stale[1].staleness_reason == "line_out_of_range"


async def test_filter_stale_findings_all_fresh(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("line1\nline2\nline3\n")
    finding = _make_finding(file="src/foo.py", line=2)

    async def fake_arun(cmd, **kwargs):
        return 0, "", ""

    monkeypatch.setattr("sigil.pipeline.maintenance.arun", fake_arun)

    fresh, stale = await filter_stale_findings([finding], tmp_path)
    assert len(fresh) == 1
    assert len(stale) == 0
    assert fresh[0].staleness_reason == ""


async def test_filter_stale_findings_all_stale(tmp_path):
    f1 = _make_finding(file="deleted1.py", priority=1)
    f2 = _make_finding(file="deleted2.py", priority=2)
    fresh, stale = await filter_stale_findings([f1, f2], tmp_path)
    assert len(fresh) == 0
    assert len(stale) == 2
    assert all(s.staleness_reason == "file_deleted" for s in stale)


async def test_is_finding_stale_context_range(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    lines = [f"line{i}" for i in range(1, 21)]
    (tmp_path / "src" / "foo.py").write_text("\n".join(lines) + "\n")
    finding = _make_finding(file="src/foo.py", line=10)

    async def fake_arun(cmd, **kwargs):
        return 0, "@@ -12,2 +12,2 @@\n-old\n+new", ""

    monkeypatch.setattr("sigil.pipeline.maintenance.arun", fake_arun)

    is_stale_default, _ = await is_finding_stale(
        finding, tmp_path, last_head="abc123", context_range=5
    )
    assert is_stale_default is True

    is_stale_narrow, _ = await is_finding_stale(
        finding, tmp_path, last_head="abc123", context_range=0
    )
    assert is_stale_narrow is False
