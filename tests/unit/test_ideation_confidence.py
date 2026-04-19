import json
from unittest.mock import MagicMock

from sigil.core.config import Config
from sigil.pipeline.ideation import (
    FeatureIdea,
    ideate,
    load_open_ideas,
    save_ideas,
)


def _make_tool_call(call_id, name, args):
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = name
    tc.function.arguments = json.dumps(args)
    return tc


def _mock_idea_response(idea_args):
    calls = []
    for i, args in enumerate(idea_args):
        calls.append(_make_tool_call(f"call_{i}", "report_idea", args))

    msg = MagicMock()
    msg.tool_calls = calls
    msg.content = None
    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = "stop"
    resp = MagicMock()
    resp.choices = [choice]
    return [resp]


async def test_ideate_collects_confidence(tmp_path, monkeypatch):
    idea_args = [
        {
            "title": "Add retry logic",
            "description": "Wrap calls with backoff",
            "rationale": "Transient failures",
            "complexity": "small",
            "disposition": "pr",
            "priority": 1,
            "confidence": 0.8,
        },
    ]

    responses = _mock_idea_response(idea_args)
    call_count = {"n": 0}

    async def fake_acompletion(**kwargs):
        idx = call_count["n"]
        call_count["n"] += 1
        return responses[idx] if idx < len(responses) else _stop_response()

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

    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)

    async def _noop_select(*a, **kw):
        return {}

    monkeypatch.setattr("sigil.pipeline.ideation.select_memory", _noop_select)
    monkeypatch.setattr("sigil.pipeline.ideation.load_working", lambda r: "")

    config = Config(model="test-model", boldness="bold")
    ideas = await ideate(tmp_path, config)

    # Find the one we mocked
    target = next((i for i in ideas if i.title == "Add retry logic"), None)
    assert target is not None
    assert target.confidence == 0.8


def test_save_load_confidence_persistence(tmp_path):
    idea = FeatureIdea(
        title="Confidence Test",
        description="desc",
        rationale="why",
        complexity="small",
        disposition="pr",
        priority=1,
        confidence=0.75,
    )

    save_ideas(tmp_path, [idea])
    loaded = load_open_ideas(tmp_path)

    assert len(loaded) == 1
    assert loaded[0].confidence == 0.75


def test_load_idea_defaults_confidence(tmp_path):
    ideas_dir = tmp_path / ".sigil" / "ideas"
    ideas_dir.mkdir(parents=True)
    (ideas_dir / "old.md").write_text(
        "---\ntitle: Old Idea\nstatus: open\ndisposition: pr\n---\n\n# Old Idea"
    )

    loaded = load_open_ideas(tmp_path)
    assert len(loaded) == 1
    assert loaded[0].confidence == 1.0
