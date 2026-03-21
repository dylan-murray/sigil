import json
from unittest.mock import MagicMock

import yaml

from sigil.config import Config
from sigil.ideation import (
    TEMP_RANGES,
    FeatureIdea,
    _deduplicate,
    _format_existing_ideas,
    _load_existing_ideas,
    _save_idea,
    _slug,
    ideate,
    save_ideas,
)


def _make_tool_call(call_id, name, args):
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = name
    tc.function.arguments = json.dumps(args)
    return tc


def _mock_idea_response(ideas_args):
    calls = []
    for i, args in enumerate(ideas_args):
        calls.append(_make_tool_call(f"call_{i}", "report_idea", args))

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


IDEA_ARGS_1 = {
    "title": "Add retry logic to LLM calls",
    "description": "Wrap litellm calls with exponential backoff",
    "rationale": "LLM APIs fail transiently, retries improve reliability",
    "complexity": "small",
    "disposition": "pr",
    "priority": 1,
}

IDEA_ARGS_2 = {
    "title": "Dashboard for run history",
    "description": "Web UI showing past sigil runs and their outcomes",
    "rationale": "Users need visibility into what sigil has done",
    "complexity": "large",
    "disposition": "issue",
    "priority": 2,
}

SAMPLE_IDEAS = [
    FeatureIdea(
        title="Add retry logic",
        description="Wrap calls with backoff",
        rationale="Transient failures",
        complexity="small",
        disposition="pr",
        priority=1,
    ),
    FeatureIdea(
        title="Dashboard",
        description="Web UI for runs",
        rationale="Visibility",
        complexity="large",
        disposition="issue",
        priority=2,
    ),
]


async def test_ideate_collects_ideas_from_two_passes(tmp_path, monkeypatch):
    focused_resp = _mock_idea_response([IDEA_ARGS_1])
    creative_resp = _mock_idea_response([IDEA_ARGS_2])
    all_responses = focused_resp + creative_resp
    call_count = {"n": 0}

    async def fake_acompletion(**kwargs):
        idx = call_count["n"]
        call_count["n"] += 1
        return all_responses[idx]

    monkeypatch.setattr("sigil.ideation.litellm.acompletion", fake_acompletion)

    async def _noop_select(*a, **kw):
        return {}

    monkeypatch.setattr("sigil.ideation.select_knowledge", _noop_select)
    monkeypatch.setattr("sigil.ideation.load_working", lambda r: "")

    config = Config(model="test-model", boldness="bold", max_ideas_per_run=15)
    ideas = await ideate(tmp_path, config)

    assert len(ideas) == 2
    assert ideas[0].title == "Add retry logic to LLM calls"
    assert ideas[1].title == "Dashboard for run history"
    assert call_count["n"] == 4


async def test_ideate_variable_temperature(tmp_path, monkeypatch):
    temps_seen = []

    async def fake_acompletion(**kwargs):
        temps_seen.append(kwargs.get("temperature"))
        msg = MagicMock()
        msg.tool_calls = None
        msg.content = "No ideas."
        choice = MagicMock()
        choice.message = msg
        choice.finish_reason = "stop"
        resp = MagicMock()
        resp.choices = [choice]
        return resp

    monkeypatch.setattr("sigil.ideation.litellm.acompletion", fake_acompletion)

    async def _noop_select(*a, **kw):
        return {}

    monkeypatch.setattr("sigil.ideation.select_knowledge", _noop_select)
    monkeypatch.setattr("sigil.ideation.load_working", lambda r: "")

    config = Config(model="test-model", boldness="bold")
    await ideate(tmp_path, config)

    assert len(temps_seen) == 2
    low, high = TEMP_RANGES["bold"]
    assert temps_seen[0] == low
    assert temps_seen[1] == high


async def test_ideate_conservative_skips(tmp_path):
    config = Config(model="test-model", boldness="conservative")
    assert await ideate(tmp_path, config) == []


async def test_ideate_does_not_save_to_disk(tmp_path, monkeypatch):
    responses = _mock_idea_response([IDEA_ARGS_1]) * 2
    call_count = {"n": 0}

    async def fake_acompletion(**kwargs):
        idx = call_count["n"]
        call_count["n"] += 1
        return responses[idx]

    monkeypatch.setattr("sigil.ideation.litellm.acompletion", fake_acompletion)

    async def _noop_select(*a, **kw):
        return {}

    monkeypatch.setattr("sigil.ideation.select_knowledge", _noop_select)
    monkeypatch.setattr("sigil.ideation.load_working", lambda r: "")

    config = Config(model="test-model", boldness="bold")
    await ideate(tmp_path, config)

    ideas_dir = tmp_path / ".sigil" / "ideas"
    assert not ideas_dir.exists()


def test_save_ideas_writes_to_disk(tmp_path, monkeypatch):
    monkeypatch.setattr("sigil.ideation.now_utc", lambda: "2026-01-01T00:00:00Z")

    paths = save_ideas(tmp_path, SAMPLE_IDEAS)
    assert len(paths) == 2

    ideas_dir = tmp_path / ".sigil" / "ideas"
    assert ideas_dir.exists()
    files = list(ideas_dir.glob("*.md"))
    assert len(files) == 2

    content = paths[0].read_text()
    parts = content.split("---", 2)
    meta = yaml.safe_load(parts[1])
    assert meta["title"] == "Add retry logic"
    assert meta["status"] == "open"
    assert meta["summary"] == "Wrap calls with backoff"


def test_dedup_loads_existing_with_summary(tmp_path):
    ideas_dir = tmp_path / ".sigil" / "ideas"
    ideas_dir.mkdir(parents=True)
    (ideas_dir / "old-idea.md").write_text(
        "---\ntitle: Old idea\nsummary: Does old stuff\nstatus: open\ncomplexity: small\n---\n\n# Old idea\n"
    )

    existing = _load_existing_ideas(tmp_path)
    assert len(existing) == 1
    assert existing[0]["title"] == "Old idea"

    formatted = _format_existing_ideas(existing)
    assert "[open] Old idea" in formatted
    assert "Does old stuff" in formatted


def test_ttl_expires_old_ideas(tmp_path):
    ideas_dir = tmp_path / ".sigil" / "ideas"
    ideas_dir.mkdir(parents=True)
    (ideas_dir / "old.md").write_text(
        "---\ntitle: Ancient\nstatus: open\ncreated: '2020-01-01T00:00:00Z'\n---\n\n# Ancient\n"
    )
    (ideas_dir / "new.md").write_text(
        "---\ntitle: Fresh\nstatus: open\ncreated: '2099-01-01T00:00:00Z'\n---\n\n# Fresh\n"
    )

    ideas = _load_existing_ideas(tmp_path, ttl_days=180)

    assert len(ideas) == 1
    assert ideas[0]["title"] == "Fresh"
    assert not (ideas_dir / "old.md").exists()


def test_slug():
    assert _slug("Add Retry Logic!") == "add-retry-logic"
    assert _slug("foo---bar") == "foo-bar"
    assert _slug("a" * 100) == "a" * 60


def test_save_idea_collision(tmp_path, monkeypatch):
    monkeypatch.setattr("sigil.ideation.now_utc", lambda: "2026-01-01T00:00:00Z")

    idea = FeatureIdea(
        title="My Feature",
        description="desc",
        rationale="why",
        complexity="small",
        disposition="pr",
        priority=1,
    )

    p1 = _save_idea(tmp_path, idea)
    p2 = _save_idea(tmp_path, idea)

    assert p1.name == "my-feature.md"
    assert p2.name == "my-feature-2.md"


def test_deduplicate():
    ideas = [
        FeatureIdea("Add Foo", "d", "r", "small", "pr", 1),
        FeatureIdea("Add foo", "d2", "r2", "medium", "issue", 2),
        FeatureIdea("Add Bar", "d3", "r3", "small", "pr", 3),
    ]
    result = _deduplicate(ideas)
    assert len(result) == 2
    assert result[0].title == "Add Foo"
    assert result[1].title == "Add Bar"
