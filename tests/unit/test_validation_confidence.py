import json
from unittest.mock import MagicMock

from sigil.core.config import Config
from sigil.pipeline.ideation import FeatureIdea
from sigil.pipeline.maintenance import Finding
from sigil.pipeline.validation import _format_items, validate_all


def _make_tool_call(call_id, name, args):
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = name
    tc.function.arguments = json.dumps(args)
    return tc


async def test_validation_format_includes_confidence(tmp_path):
    findings = [
        Finding(
            category="dead_code",
            file="foo.py",
            line=None,
            description="desc",
            risk="low",
            suggested_fix="fix",
            disposition="pr",
            priority=1,
            rationale="why",
            confidence=0.6,
        ),
    ]
    ideas = [
        FeatureIdea(
            title="Idea",
            description="desc",
            rationale="why",
            complexity="small",
            disposition="pr",
            priority=1,
            confidence=0.4,
        ),
    ]
    text = _format_items(tmp_path, findings, ideas)
    assert "conf: 0.6" in text
    assert "conf: 0.4" in text


async def test_validate_all_handles_confidence_in_prompt(tmp_path, monkeypatch):
    # We just want to verify that the agent is called and the logic doesn't crash
    # since the actual "veto low confidence" is a prompt instruction.
    msg = MagicMock()
    msg.tool_calls = None
    msg.content = "Done."
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

    monkeypatch.setattr("sigil.pipeline.validation.select_memory", _noop_select)
    monkeypatch.setattr("sigil.pipeline.validation.load_working", lambda r: "")

    config = Config(model="test-model")
    findings = [
        Finding(
            category="dead_code",
            file="f.py",
            line=None,
            description="d",
            risk="low",
            suggested_fix="s",
            disposition="pr",
            priority=1,
            rationale="r",
            confidence=0.1,
        )
    ]
    result = await validate_all(tmp_path, config, findings, [])

    # If the agent just stops, it defaults to 'issue' for unreviewed items
    assert result.findings[0].disposition == "issue"
