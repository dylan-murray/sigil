import json
from unittest.mock import MagicMock

from sigil.core.config import Config
from sigil.pipeline.maintenance import analyze, check_suppression


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


# ---------------------------------------------------------------------------
# check_suppression tests
# ---------------------------------------------------------------------------


def test_check_suppression_file_level(tmp_path):
    src = tmp_path / "src" / "app.py"
    src.parent.mkdir(parents=True)
    src.write_text("# sigil-ignore: security\nimport os\n")
    result = check_suppression(tmp_path, "src/app.py", 5, "security")
    assert result is not None
    assert "security" in result.lower()


def test_check_suppression_file_level_all(tmp_path):
    src = tmp_path / "src" / "app.py"
    src.parent.mkdir(parents=True)
    src.write_text("# sigil-ignore: all\nimport os\n")
    result = check_suppression(tmp_path, "src/app.py", 5, "dead_code")
    assert result is not None
    assert "all" in result.lower()


def test_check_suppression_line_level(tmp_path):
    src = tmp_path / "src" / "app.py"
    src.parent.mkdir(parents=True)
    src.write_text("import os\n# sigil-ignore-next: dead_code\nunused = 42\n")
    result = check_suppression(tmp_path, "src/app.py", 3, "dead_code")
    assert result is not None
    assert "dead_code" in result.lower()


def test_check_suppression_line_level_all(tmp_path):
    src = tmp_path / "src" / "app.py"
    src.parent.mkdir(parents=True)
    src.write_text("import os\n# sigil-ignore-next: all\nunused = 42\n")
    result = check_suppression(tmp_path, "src/app.py", 3, "security")
    assert result is not None
    assert "all" in result.lower()


def test_check_suppression_no_annotation(tmp_path):
    src = tmp_path / "src" / "app.py"
    src.parent.mkdir(parents=True)
    src.write_text("import os\nunused = 42\n")
    result = check_suppression(tmp_path, "src/app.py", 2, "dead_code")
    assert result is None


def test_check_suppression_case_insensitive(tmp_path):
    src = tmp_path / "src" / "app.py"
    src.parent.mkdir(parents=True)
    src.write_text("# sigil-ignore: Security\nimport os\n")
    result = check_suppression(tmp_path, "src/app.py", 5, "security")
    assert result is not None


def test_check_suppression_nonexistent_file(tmp_path):
    result = check_suppression(tmp_path, "nonexistent.py", 1, "security")
    assert result is None


def test_check_suppression_file_level_beyond_header(tmp_path):
    lines = ["import os\n"] * 20 + ["# sigil-ignore: security\n"]
    src = tmp_path / "src" / "app.py"
    src.parent.mkdir(parents=True)
    src.write_text("".join(lines))
    result = check_suppression(tmp_path, "src/app.py", 25, "security")
    assert result is None


def test_check_suppression_line_level_wrong_line(tmp_path):
    src = tmp_path / "src" / "app.py"
    src.parent.mkdir(parents=True)
    src.write_text("# sigil-ignore-next: dead_code\nimport os\nunused = 42\n")
    result = check_suppression(tmp_path, "src/app.py", 3, "dead_code")
    assert result is None


def test_check_suppression_line_level_wrong_category(tmp_path):
    src = tmp_path / "src" / "app.py"
    src.parent.mkdir(parents=True)
    src.write_text("# sigil-ignore-next: dead_code\nunused = 42\n")
    result = check_suppression(tmp_path, "src/app.py", 2, "security")
    assert result is None


async def test_analyze_suppresses_findings(tmp_path, monkeypatch):
    src = tmp_path / "src" / "app.py"
    src.parent.mkdir(parents=True)
    src.write_text("# sigil-ignore: security\nimport os\n")

    findings_args = [
        {
            "category": "security",
            "file": "src/app.py",
            "line": 2,
            "description": "Hardcoded secret",
            "risk": "high",
            "suggested_fix": "Use env var",
            "disposition": "issue",
            "priority": 1,
            "rationale": "Security risk",
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

    assert len(findings) == 0
