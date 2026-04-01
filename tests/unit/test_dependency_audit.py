import json
from unittest.mock import MagicMock

from sigil.core.config import Config
from sigil.pipeline.maintenance import _parse_dependency_audit_output
from sigil.pipeline.maintenance import analyze


async def _noop_select(*args, **kwargs):
    return {}


async def _stop_response():
    msg = MagicMock()
    msg.tool_calls = None
    msg.content = "Done."
    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = "stop"
    resp = MagicMock()
    resp.choices = [choice]
    return resp


async def test_analyze_emits_dependency_vulnerability_findings(tmp_path, monkeypatch):
    audit_output = json.dumps(
        {
            "vulnerabilities": [
                {
                    "package": "urllib3",
                    "advisory": "urllib3 is vulnerable to request smuggling",
                    "severity": "high",
                }
            ]
        }
    )

    async def fake_arun(cmd, *, cwd=None, timeout=30):
        if cmd == ["uv", "pip", "audit"]:
            return 1, "", "unrecognized subcommand 'audit'"
        if cmd == ["pip-audit"]:
            return 0, audit_output, ""
        return 1, "", "unexpected command"

    async def fake_acompletion(**kwargs):
        return await _stop_response()

    monkeypatch.setattr("sigil.pipeline.maintenance.arun", fake_arun)
    monkeypatch.setattr("sigil.pipeline.maintenance.select_memory", _noop_select)
    monkeypatch.setattr("sigil.pipeline.maintenance.load_working", lambda repo: "")
    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)

    findings = await analyze(tmp_path, Config(model="test-model"))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.category == "security"
    assert finding.file == "dependency-audit"
    assert finding.risk == "high"
    assert finding.suggested_fix == "uv add package@latest"
    assert "urllib3" in finding.description


async def test_analyze_skips_when_audit_output_absent(tmp_path, monkeypatch):
    async def fake_arun(cmd, *, cwd=None, timeout=30):
        if cmd == ["uv", "pip", "audit"]:
            return 1, "", "unrecognized subcommand 'audit'"
        if cmd == ["pip-audit"]:
            return 1, "", "command not found"
        return 1, "", "unexpected command"

    async def fake_acompletion(**kwargs):
        return await _stop_response()

    monkeypatch.setattr("sigil.pipeline.maintenance.arun", fake_arun)
    monkeypatch.setattr("sigil.pipeline.maintenance.select_memory", _noop_select)
    monkeypatch.setattr("sigil.pipeline.maintenance.load_working", lambda repo: "")
    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)

    findings = await analyze(tmp_path, Config(model="test-model"))

    assert findings == []


def test_parse_dependency_audit_output_handles_malformed_output():
    assert _parse_dependency_audit_output("not json") == []
    assert _parse_dependency_audit_output(json.dumps({"vulnerabilities": ["bad"]})) == []
    assert _parse_dependency_audit_output(json.dumps({"unexpected": []})) == []
