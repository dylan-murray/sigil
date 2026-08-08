import json
from unittest.mock import MagicMock

from sigil.core.config import Config
from sigil.pipeline.maintenance import _cluster_findings, analyze
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


def _finding(
    category="dead_code",
    file="src/foo.py",
    line=None,
    description="",
    risk="low",
    suggested_fix="",
    disposition="pr",
    priority=1,
    rationale="",
    implementation_spec="",
):
    return Finding(
        category=category,
        file=file,
        line=line,
        description=description,
        risk=risk,
        suggested_fix=suggested_fix,
        disposition=disposition,
        priority=priority,
        rationale=rationale,
        implementation_spec=implementation_spec,
    )


def test_cluster_empty_list():
    assert _cluster_findings([]) == []


def test_cluster_single_finding_passthrough():
    f = _finding(description="solo")
    result = _cluster_findings([f])
    assert len(result) == 1
    assert result[0] is f
    assert result[0].sub_findings == ()


def test_cluster_same_file_same_category_merges():
    f1 = _finding(
        category="security",
        file="src/config.py",
        line=10,
        description="Missing error handling in parse_config",
        risk="low",
        suggested_fix="Add try/except",
        disposition="pr",
        priority=3,
        rationale="Easy fix",
    )
    f2 = _finding(
        category="security",
        file="src/config.py",
        line=50,
        description="Unhandled ValueError in parse_config",
        risk="medium",
        suggested_fix="Catch ValueError specifically",
        disposition="issue",
        priority=5,
        rationale="Needs review",
    )
    result = _cluster_findings([f1, f2])
    assert len(result) == 1
    merged = result[0]
    assert merged.file == "src/config.py"
    assert merged.category == "security"
    assert "Missing error handling" in merged.description
    assert "Unhandled ValueError" in merged.description
    assert "Add try/except" in merged.suggested_fix
    assert "Catch ValueError specifically" in merged.suggested_fix
    assert merged.priority == 3
    assert merged.risk == "medium"
    assert merged.disposition == "issue"
    assert len(merged.sub_findings) == 2
    assert "Missing error handling" in merged.sub_findings[0]
    assert "Unhandled ValueError" in merged.sub_findings[1]


def test_cluster_no_cross_file_merges():
    f1 = _finding(category="dead_code", file="src/a.py", line=1, description="A")
    f2 = _finding(category="dead_code", file="src/b.py", line=1, description="B")
    result = _cluster_findings([f1, f2])
    assert len(result) == 2
    files = {r.file for r in result}
    assert files == {"src/a.py", "src/b.py"}
    assert all(r.sub_findings == () for r in result)


def test_cluster_different_category_same_file_no_merge():
    f1 = _finding(category="dead_code", file="src/a.py", line=1, description="A")
    f2 = _finding(category="security", file="src/a.py", line=100, description="B")
    result = _cluster_findings([f1, f2])
    assert len(result) == 2


def test_cluster_line_proximity_merges():
    f1 = _finding(
        category="types",
        file="src/utils.py",
        line=20,
        description="Missing type hint on foo",
    )
    f2 = _finding(
        category="dead_code",
        file="src/utils.py",
        line=25,
        description="Unused import near foo",
    )
    result = _cluster_findings([f1, f2])
    assert len(result) == 1
    merged = result[0]
    assert "Missing type hint" in merged.description
    assert "Unused import" in merged.description
    assert len(merged.sub_findings) == 2


def test_cluster_line_proximity_threshold_not_merged():
    f1 = _finding(
        category="types",
        file="src/utils.py",
        line=20,
        description="Missing type hint on foo",
    )
    f2 = _finding(
        category="dead_code",
        file="src/utils.py",
        line=50,
        description="Unused import far away",
    )
    result = _cluster_findings([f1, f2])
    assert len(result) == 2


def test_cluster_priority_takes_min():
    f1 = _finding(category="tests", file="a.py", line=1, description="A", priority=5)
    f2 = _finding(category="tests", file="a.py", line=2, description="B", priority=2)
    result = _cluster_findings([f1, f2])
    assert len(result) == 1
    assert result[0].priority == 2


def test_cluster_risk_takes_max():
    f1 = _finding(category="security", file="a.py", line=1, description="A", risk="low")
    f2 = _finding(category="security", file="a.py", line=2, description="B", risk="high")
    result = _cluster_findings([f1, f2])
    assert len(result) == 1
    assert result[0].risk == "high"


def test_cluster_disposition_takes_most_conservative():
    f1 = _finding(category="security", file="a.py", line=1, description="A", disposition="pr")
    f2 = _finding(category="security", file="a.py", line=2, description="B", disposition="issue")
    result = _cluster_findings([f1, f2])
    assert len(result) == 1
    assert result[0].disposition == "issue"


def test_cluster_implementation_specs_combined():
    f1 = _finding(
        category="security",
        file="a.py",
        line=1,
        description="A",
        implementation_spec="Fix A: add check",
    )
    f2 = _finding(
        category="security",
        file="a.py",
        line=2,
        description="B",
        implementation_spec="Fix B: add guard",
    )
    result = _cluster_findings([f1, f2])
    assert len(result) == 1
    assert "Fix A: add check" in result[0].implementation_spec
    assert "Fix B: add guard" in result[0].implementation_spec


def test_cluster_line_takes_earliest():
    f1 = _finding(category="security", file="a.py", line=30, description="A")
    f2 = _finding(category="security", file="a.py", line=10, description="B")
    result = _cluster_findings([f1, f2])
    assert len(result) == 1
    assert result[0].line == 10


def test_cluster_null_lines_same_category_still_merge():
    f1 = _finding(category="dead_code", file="a.py", line=None, description="A")
    f2 = _finding(category="dead_code", file="a.py", line=None, description="B")
    result = _cluster_findings([f1, f2])
    assert len(result) == 1
    assert result[0].line is None


def test_cluster_three_findings_same_file_category():
    findings = [
        _finding(category="types", file="a.py", line=1, description="A", priority=1),
        _finding(category="types", file="a.py", line=5, description="B", priority=2),
        _finding(category="types", file="a.py", line=10, description="C", priority=3),
    ]
    result = _cluster_findings(findings)
    assert len(result) == 1
    assert len(result[0].sub_findings) == 3


def test_cluster_mixed_groups():
    f1 = _finding(category="dead_code", file="a.py", line=1, description="A1")
    f2 = _finding(category="dead_code", file="a.py", line=5, description="A2")
    f3 = _finding(category="security", file="b.py", line=1, description="B1")
    f4 = _finding(category="security", file="b.py", line=3, description="B2")
    result = _cluster_findings([f1, f2, f3, f4])
    assert len(result) == 2
    merged_files = {r.file for r in result}
    assert merged_files == {"a.py", "b.py"}
    for r in result:
        assert len(r.sub_findings) == 2


def test_cluster_result_sorted_by_priority():
    f1 = _finding(category="dead_code", file="a.py", line=1, description="A", priority=5)
    f2 = _finding(category="security", file="b.py", line=1, description="B", priority=1)
    result = _cluster_findings([f1, f2])
    assert result[0].priority == 1
    assert result[1].priority == 5


async def test_analyze_clusters_same_file_findings(tmp_path, monkeypatch):
    findings_args = [
        {
            "category": "security",
            "file": "src/config.py",
            "line": 10,
            "description": "Missing error handling in parse_config",
            "risk": "low",
            "suggested_fix": "Add try/except",
            "disposition": "pr",
            "priority": 1,
            "rationale": "Easy fix",
        },
        {
            "category": "security",
            "file": "src/config.py",
            "line": 50,
            "description": "Unhandled ValueError in parse_config",
            "risk": "high",
            "suggested_fix": "Catch ValueError",
            "disposition": "issue",
            "priority": 2,
            "rationale": "Needs review",
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
    merged = findings[0]
    assert merged.file == "src/config.py"
    assert "Missing error handling" in merged.description
    assert "Unhandled ValueError" in merged.description
    assert merged.risk == "high"
    assert merged.disposition == "issue"
    assert merged.priority == 1
    assert len(merged.sub_findings) == 2
