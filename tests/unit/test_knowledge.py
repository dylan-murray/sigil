import json
from unittest.mock import MagicMock


from sigil.knowledge import (
    _knowledge_budget,
    _load_existing_knowledge,
    compact_knowledge,
    is_knowledge_stale,
    select_knowledge,
)


def test_knowledge_budget_scales_with_context(monkeypatch):
    monkeypatch.setattr("sigil.knowledge.get_context_window", lambda m: 128_000)
    assert _knowledge_budget("test-model") == 128_000

    monkeypatch.setattr("sigil.knowledge.get_context_window", lambda m: 8_000)
    assert _knowledge_budget("small-model") == 16_000


def test_load_existing_knowledge_skips_index_and_working(tmp_path):
    mdir = tmp_path / ".sigil" / "memory"
    mdir.mkdir(parents=True)
    (mdir / "INDEX.md").write_text("index stuff")
    (mdir / "working.md").write_text("working stuff")
    (mdir / "architecture.md").write_text("arch content")
    (mdir / "patterns.md").write_text("pattern content")

    result = _load_existing_knowledge(mdir)
    assert "architecture.md" in result
    assert "patterns.md" in result
    assert "INDEX.md" not in result
    assert "working.md" not in result


def _make_tool_call(call_id, name, args):
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = name
    tc.function.arguments = json.dumps(args)
    return tc


def _mock_completion_with_writes(file_writes):
    calls = []
    for fname, content in file_writes.items():
        calls.append(
            _make_tool_call(
                f"call_{fname}", "write_knowledge_file", {"filename": fname, "content": content}
            )
        )

    msg1 = MagicMock()
    msg1.tool_calls = calls
    msg1.content = None
    choice1 = MagicMock()
    choice1.message = msg1
    choice1.finish_reason = "tool_calls"
    resp1 = MagicMock()
    resp1.choices = [choice1]

    msg2 = MagicMock()
    msg2.tool_calls = None
    msg2.content = "Done."
    choice2 = MagicMock()
    choice2.message = msg2
    choice2.finish_reason = "stop"
    resp2 = MagicMock()
    resp2.choices = [choice2]

    return [resp1, resp2]


async def test_compact_knowledge_writes_files(tmp_path, monkeypatch):
    mdir = tmp_path / ".sigil" / "memory"
    mdir.mkdir(parents=True)

    writes = {"project.md": "# Project\nStuff", "architecture.md": "# Arch\nMore"}

    responses = _mock_completion_with_writes(writes)
    index_msg = MagicMock()
    index_msg.content = "# Knowledge Index\n\n## project.md\nProject info"
    index_resp = MagicMock()
    index_resp.choices = [MagicMock(message=index_msg)]
    responses.append(index_resp)

    call_count = {"n": 0}

    async def fake_acompletion(**kwargs):
        idx = call_count["n"]
        call_count["n"] += 1
        return responses[idx]

    monkeypatch.setattr("sigil.knowledge.litellm.acompletion", fake_acompletion)
    monkeypatch.setattr("sigil.knowledge.get_context_window", lambda m: 32_000)

    async def fake_get_head(r):
        return "abc123"

    monkeypatch.setattr("sigil.knowledge.get_head", fake_get_head)
    monkeypatch.setattr("sigil.knowledge.now_utc", lambda: "2026-01-01T00:00:00Z")
    monkeypatch.setattr("sigil.knowledge.SIGIL_DIR", ".sigil")
    monkeypatch.setattr("sigil.knowledge.MEMORY_DIR", "memory")

    result = await compact_knowledge(tmp_path, "test-model", "raw discovery context")

    assert (mdir / "project.md").exists()
    assert (mdir / "architecture.md").exists()
    assert (mdir / "INDEX.md").exists()
    assert result == str(mdir / "INDEX.md")


async def test_compact_knowledge_rejects_reserved(tmp_path, monkeypatch):
    mdir = tmp_path / ".sigil" / "memory"
    mdir.mkdir(parents=True)

    calls = [
        _make_tool_call(
            "c1", "write_knowledge_file", {"filename": "INDEX.md", "content": "hacked"}
        ),
        _make_tool_call(
            "c2", "write_knowledge_file", {"filename": "working.md", "content": "hacked"}
        ),
        _make_tool_call(
            "c3", "write_knowledge_file", {"filename": "legit.md", "content": "real content"}
        ),
    ]

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

    index_msg = MagicMock()
    index_msg.content = "# Index\n## legit.md\nstuff"
    index_resp = MagicMock()
    index_resp.choices = [MagicMock(message=index_msg)]

    call_count = {"n": 0}
    resps = [resp1, resp2, index_resp]

    async def fake_acompletion(**kwargs):
        idx = call_count["n"]
        call_count["n"] += 1
        return resps[idx]

    monkeypatch.setattr("sigil.knowledge.litellm.acompletion", fake_acompletion)
    monkeypatch.setattr("sigil.knowledge.get_context_window", lambda m: 32_000)

    async def fake_get_head(r):
        return "abc123"

    monkeypatch.setattr("sigil.knowledge.get_head", fake_get_head)
    monkeypatch.setattr("sigil.knowledge.now_utc", lambda: "2026-01-01T00:00:00Z")
    monkeypatch.setattr("sigil.knowledge.SIGIL_DIR", ".sigil")
    monkeypatch.setattr("sigil.knowledge.MEMORY_DIR", "memory")

    await compact_knowledge(tmp_path, "test-model", "context")

    assert (mdir / "legit.md").exists()
    assert (mdir / "INDEX.md").read_text() != "hacked"
    assert not (mdir / "working.md").exists() or (mdir / "working.md").read_text() != "hacked"


async def test_compact_knowledge_empty_response(tmp_path, monkeypatch):
    mdir = tmp_path / ".sigil" / "memory"
    mdir.mkdir(parents=True)

    msg = MagicMock()
    msg.tool_calls = None
    msg.content = "Nothing to write."
    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = "stop"
    resp = MagicMock()
    resp.choices = [choice]

    async def fake_acompletion(**kw):
        return resp

    monkeypatch.setattr("sigil.knowledge.litellm.acompletion", fake_acompletion)
    monkeypatch.setattr("sigil.knowledge.get_context_window", lambda m: 32_000)
    monkeypatch.setattr("sigil.knowledge.SIGIL_DIR", ".sigil")
    monkeypatch.setattr("sigil.knowledge.MEMORY_DIR", "memory")

    result = await compact_knowledge(tmp_path, "test-model", "context")
    assert result == ""


async def test_select_knowledge_calls_llm_and_loads(tmp_path, monkeypatch):
    mdir = tmp_path / ".sigil" / "memory"
    mdir.mkdir(parents=True)
    (mdir / "INDEX.md").write_text("# Index\n## arch.md\nArchitecture info")
    (mdir / "arch.md").write_text("architecture content")

    tc = _make_tool_call("c1", "load_knowledge_files", {"filenames": ["arch.md"]})
    msg = MagicMock()
    msg.tool_calls = [tc]
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]

    async def fake_acompletion(**kw):
        return resp

    monkeypatch.setattr("sigil.knowledge.litellm.acompletion", fake_acompletion)
    monkeypatch.setattr("sigil.knowledge.SIGIL_DIR", ".sigil")
    monkeypatch.setattr("sigil.knowledge.MEMORY_DIR", "memory")

    result = await select_knowledge(tmp_path, "test-model", "find dead code")
    assert "arch.md" in result
    assert result["arch.md"] == "architecture content"


async def test_select_knowledge_no_index(tmp_path, monkeypatch):
    monkeypatch.setattr("sigil.knowledge.SIGIL_DIR", ".sigil")
    monkeypatch.setattr("sigil.knowledge.MEMORY_DIR", "memory")
    result = await select_knowledge(tmp_path, "test-model", "anything")
    assert result == {}


async def test_is_knowledge_stale_no_index(tmp_path, monkeypatch):
    monkeypatch.setattr("sigil.knowledge.SIGIL_DIR", ".sigil")
    monkeypatch.setattr("sigil.knowledge.MEMORY_DIR", "memory")
    assert await is_knowledge_stale(tmp_path) is True


async def test_is_knowledge_stale_head_matches(tmp_path, monkeypatch):
    mdir = tmp_path / ".sigil" / "memory"
    mdir.mkdir(parents=True)
    (mdir / "INDEX.md").write_text("<!-- head: abc123 | updated: 2026-01-01 -->\n# Index")

    monkeypatch.setattr("sigil.knowledge.SIGIL_DIR", ".sigil")
    monkeypatch.setattr("sigil.knowledge.MEMORY_DIR", "memory")

    async def fake_get_head(r):
        return "abc123"

    monkeypatch.setattr("sigil.knowledge.get_head", fake_get_head)
    assert await is_knowledge_stale(tmp_path) is False


async def test_is_knowledge_stale_head_differs(tmp_path, monkeypatch):
    mdir = tmp_path / ".sigil" / "memory"
    mdir.mkdir(parents=True)
    (mdir / "INDEX.md").write_text("<!-- head: abc123 | updated: 2026-01-01 -->\n# Index")

    monkeypatch.setattr("sigil.knowledge.SIGIL_DIR", ".sigil")
    monkeypatch.setattr("sigil.knowledge.MEMORY_DIR", "memory")

    async def fake_get_head(r):
        return "def456"

    monkeypatch.setattr("sigil.knowledge.get_head", fake_get_head)
    assert await is_knowledge_stale(tmp_path) is True
