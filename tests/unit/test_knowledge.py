import json
from unittest.mock import MagicMock

from sigil.pipeline.knowledge import (
    _decode_json_string,
    _knowledge_budget,
    _load_existing_knowledge,
    _max_input_chars,
    _parse_response,
    _repair_truncated_json,
    _truncate_to_budget,
    compact_knowledge,
    is_knowledge_stale,
    select_memory,
)


def test_knowledge_budget_scales_with_context(monkeypatch):
    monkeypatch.setattr("sigil.pipeline.knowledge.get_context_window", lambda m: 128_000)
    assert _knowledge_budget("test-model") == 128_000

    monkeypatch.setattr("sigil.pipeline.knowledge.get_context_window", lambda m: 8_000)
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


def test_parse_response_plain_json():
    raw = json.dumps({"files": {"a.md": "content"}, "index": "# Index"})
    result = _parse_response(raw)
    assert result["files"]["a.md"] == "content"


def test_parse_response_with_fences():
    raw = "```json\n" + json.dumps({"files": {}, "index": ""}) + "\n```"
    result = _parse_response(raw)
    assert result["files"] == {}


def test_repair_truncated_json_salvages_files():
    raw = '{"files": {"project.md": "# Project\\nContent", "arch.md": "# Arch\\nStuff"}, "index": "# Inde'
    result = _repair_truncated_json(raw)
    assert result is not None
    assert "project.md" in result["files"]
    assert "arch.md" in result["files"]


def test_repair_truncated_json_no_files():
    result = _repair_truncated_json("totally broken garbage")
    assert result is None


def test_parse_response_truncated_falls_back_to_repair():
    raw = '{"files": {"project.md": "# Project\\nContent"}, "index": "# Index trun'
    result = _parse_response(raw)
    assert "project.md" in result["files"]


def test_decode_json_string_handles_escapes():
    assert _decode_json_string("hello\\nworld") == "hello\nworld"
    assert _decode_json_string('say \\"hi\\"') == 'say "hi"'
    assert _decode_json_string("back\\\\slash") == "back\\slash"
    assert _decode_json_string("tab\\there") == "tab\there"


def test_max_input_chars(monkeypatch):
    monkeypatch.setattr("sigil.pipeline.knowledge.get_context_window", lambda m: 200_000)
    monkeypatch.setattr("sigil.pipeline.knowledge.get_max_output_tokens", lambda m: 8_192)
    result = _max_input_chars("test-model")
    assert result == (200_000 - 8_192 - 2000) * 3


def test_truncate_to_budget():
    short = "hello"
    assert _truncate_to_budget(short, 100) == short

    long_text = "x" * 1000
    result = _truncate_to_budget(long_text, 100)
    assert len(result) < 200
    assert "truncated" in result


def _make_json_response(files, index="# Knowledge Index\n\n## project.md\nProject info"):
    payload = json.dumps({"files": files, "index": index})
    msg = MagicMock()
    msg.content = payload
    msg.tool_calls = None
    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = "stop"
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _make_tool_call(call_id, name, args):
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = name
    tc.function.arguments = json.dumps(args)
    return tc


def _make_read_then_json_responses(read_files, final_files, final_index):
    tool_calls = []
    for fname in read_files:
        tool_calls.append(
            _make_tool_call(f"call_{fname}", "read_knowledge_file", {"filename": fname})
        )

    msg1 = MagicMock()
    msg1.tool_calls = tool_calls
    msg1.content = None
    choice1 = MagicMock()
    choice1.message = msg1
    choice1.finish_reason = "tool_calls"
    resp1 = MagicMock()
    resp1.choices = [choice1]

    resp2 = _make_json_response(final_files, final_index)

    return [resp1, resp2]


def _patch_common(
    monkeypatch,
    tmp_path,
    head="abc123",
    manifest_hash="aabbccdd00112233445566778899aabbccddeeff00112233445566778899aabb",
):
    async def fake_get_head(r):
        return head

    async def fake_compute_manifest_hash(r):
        return manifest_hash

    monkeypatch.setattr("sigil.pipeline.knowledge.get_context_window", lambda m: 32_000)
    monkeypatch.setattr("sigil.pipeline.knowledge.get_max_output_tokens", lambda m: 8192)
    monkeypatch.setattr("sigil.pipeline.knowledge.get_head", fake_get_head)
    monkeypatch.setattr(
        "sigil.pipeline.knowledge.compute_manifest_hash", fake_compute_manifest_hash
    )
    monkeypatch.setattr("sigil.pipeline.knowledge.now_utc", lambda: "2026-01-01T00:00:00Z")
    monkeypatch.setattr(
        "sigil.pipeline.knowledge.memory_dir",
        lambda repo: repo / ".sigil" / "memory",
    )


async def test_compact_knowledge_full_init(tmp_path, monkeypatch):
    mdir = tmp_path / ".sigil" / "memory"
    mdir.mkdir(parents=True)

    files = {"project.md": "# Project\nStuff", "architecture.md": "# Arch\nMore"}
    resp = _make_json_response(files)

    async def fake_acompletion(**kwargs):
        return resp

    _patch_common(monkeypatch, tmp_path)
    monkeypatch.setattr("sigil.pipeline.knowledge.acompletion", fake_acompletion)
    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)

    result = await compact_knowledge(tmp_path, "test-model", "raw discovery context")

    assert (mdir / "project.md").exists()
    assert (mdir / "architecture.md").exists()
    assert (mdir / "INDEX.md").exists()
    assert result == str(mdir / "INDEX.md")
    assert "abc123" in (mdir / "INDEX.md").read_text()


async def test_compact_knowledge_rejects_reserved(tmp_path, monkeypatch):
    mdir = tmp_path / ".sigil" / "memory"
    mdir.mkdir(parents=True)

    files = {
        "INDEX.md": "hacked",
        "working.md": "hacked",
        "legit.md": "real content",
    }
    resp = _make_json_response(files)

    async def fake_acompletion(**kwargs):
        return resp

    _patch_common(monkeypatch, tmp_path)
    monkeypatch.setattr("sigil.pipeline.knowledge.acompletion", fake_acompletion)
    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)

    await compact_knowledge(tmp_path, "test-model", "context")

    assert (mdir / "legit.md").exists()
    assert "hacked" not in (mdir / "INDEX.md").read_text()
    assert not (mdir / "working.md").exists() or (mdir / "working.md").read_text() != "hacked"


async def test_compact_knowledge_empty_response(tmp_path, monkeypatch):
    mdir = tmp_path / ".sigil" / "memory"
    mdir.mkdir(parents=True)

    resp = _make_json_response({}, "")

    async def fake_acompletion(**kw):
        return resp

    _patch_common(monkeypatch, tmp_path)
    monkeypatch.setattr("sigil.pipeline.knowledge.acompletion", fake_acompletion)
    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)

    result = await compact_knowledge(tmp_path, "test-model", "context")
    assert result == ""


async def test_compact_knowledge_skips_when_manifest_matches(tmp_path, monkeypatch):
    mdir = tmp_path / ".sigil" / "memory"
    mdir.mkdir(parents=True)
    (mdir / "INDEX.md").write_text(
        "<!-- head: abc123 | manifest: aabbccdd00112233445566778899aabbccddeeff00112233445566778899aabb | updated: 2026-01-01 -->\n# Index"
    )
    (mdir / "project.md").write_text("# Project\nContent")

    _patch_common(
        monkeypatch,
        tmp_path,
        head="abc123",
        manifest_hash="aabbccdd00112233445566778899aabbccddeeff00112233445566778899aabb",
    )

    result = await compact_knowledge(tmp_path, "test-model", "discovery context")
    assert result == ""


async def test_compact_knowledge_incremental_with_tool_reads(tmp_path, monkeypatch):
    mdir = tmp_path / ".sigil" / "memory"
    mdir.mkdir(parents=True)
    (mdir / "project.md").write_text("# Project\nOld content")
    (mdir / "architecture.md").write_text("# Architecture\nOld arch")
    (mdir / "INDEX.md").write_text(
        "<!-- head: aaa111 | updated: 2026-01-01 -->\n"
        "# Knowledge Index\n\n## project.md\nProject info\n\n## architecture.md\nArch info"
    )

    updated_files = {"architecture.md": "# Architecture\nUpdated arch"}
    index = (
        "# Knowledge Index\n\n## project.md\nProject info\n\n## architecture.md\nUpdated arch info"
    )
    responses = _make_read_then_json_responses(
        read_files=["architecture.md"],
        final_files=updated_files,
        final_index=index,
    )

    call_count = {"n": 0}

    async def fake_acompletion(**kwargs):
        idx = call_count["n"]
        call_count["n"] += 1
        return responses[idx]

    _patch_common(monkeypatch, tmp_path, head="bbb222")
    monkeypatch.setattr("sigil.pipeline.knowledge.acompletion", fake_acompletion)
    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)

    async def fake_arun(cmd, *, cwd=None, timeout=30):
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd
        if "--name-only" in cmd_str:
            return 0, "sigil/llm.py\nsigil/config.py\n", ""
        if "log" in cmd_str:
            return 0, "bbb222 some commit\n", ""
        if "diff" in cmd_str and "--" in cmd_str:
            return 0, "diff --git a/file ...\n+new line", ""
        return 1, "", "unknown"

    monkeypatch.setattr("sigil.pipeline.knowledge.arun", fake_arun)

    result = await compact_knowledge(tmp_path, "test-model", "discovery context")

    assert result == str(mdir / "INDEX.md")
    assert "Updated arch" in (mdir / "architecture.md").read_text()
    assert "Old content" in (mdir / "project.md").read_text()
    assert "bbb222" in (mdir / "INDEX.md").read_text()
    assert call_count["n"] == 2


async def test_compact_knowledge_incremental_deletes_file(tmp_path, monkeypatch):
    mdir = tmp_path / ".sigil" / "memory"
    mdir.mkdir(parents=True)
    (mdir / "project.md").write_text("# Project\nContent")
    (mdir / "obsolete.md").write_text("# Obsolete\nOld stuff")
    (mdir / "INDEX.md").write_text(
        "<!-- head: aaa111 | updated: 2026-01-01 -->\n"
        "# Knowledge Index\n\n## project.md\nProject info\n\n## obsolete.md\nObsolete info"
    )

    updated_files = {"obsolete.md": ""}
    index = "# Knowledge Index\n\n## project.md\nProject info"
    responses = _make_read_then_json_responses(
        read_files=["obsolete.md"],
        final_files=updated_files,
        final_index=index,
    )

    call_count = {"n": 0}

    async def fake_acompletion(**kwargs):
        idx = call_count["n"]
        call_count["n"] += 1
        return responses[idx]

    _patch_common(monkeypatch, tmp_path, head="ccc333")
    monkeypatch.setattr("sigil.pipeline.knowledge.acompletion", fake_acompletion)
    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)

    async def fake_arun(cmd, *, cwd=None, timeout=30):
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd
        if "--name-only" in cmd_str:
            return 0, "sigil/obsolete.py\n", ""
        if "log" in cmd_str:
            return 0, "ccc333 removed obsolete module\n", ""
        if "diff" in cmd_str and "--" in cmd_str:
            return 0, "diff --git a/sigil/obsolete.py ...\n-deleted", ""
        return 1, "", "unknown"

    monkeypatch.setattr("sigil.pipeline.knowledge.arun", fake_arun)

    result = await compact_knowledge(tmp_path, "test-model", "discovery context")

    assert result == str(mdir / "INDEX.md")
    assert not (mdir / "obsolete.md").exists()
    assert (mdir / "project.md").exists()


async def test_compact_knowledge_incremental_no_tool_reads(tmp_path, monkeypatch):
    mdir = tmp_path / ".sigil" / "memory"
    mdir.mkdir(parents=True)
    (mdir / "project.md").write_text("# Project\nContent")
    (mdir / "INDEX.md").write_text(
        "<!-- head: aaa111 | updated: 2026-01-01 -->\n# Knowledge Index\n\n## project.md\nProject info"
    )

    updated_files = {"project.md": "# Project\nUpdated"}
    index = "# Knowledge Index\n\n## project.md\nUpdated info"
    resp = _make_json_response(updated_files, index)

    async def fake_acompletion(**kwargs):
        return resp

    _patch_common(monkeypatch, tmp_path, head="ddd444")
    monkeypatch.setattr("sigil.pipeline.knowledge.acompletion", fake_acompletion)
    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)

    async def fake_arun(cmd, *, cwd=None, timeout=30):
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd
        if "--name-only" in cmd_str:
            return 0, "README.md\n", ""
        if "log" in cmd_str:
            return 0, "ddd444 update readme\n", ""
        if "diff" in cmd_str and "--" in cmd_str:
            return 0, "diff --git a/README.md ...\n+new line", ""
        return 1, "", "unknown"

    monkeypatch.setattr("sigil.pipeline.knowledge.arun", fake_arun)

    result = await compact_knowledge(tmp_path, "test-model", "discovery context")
    assert result == str(mdir / "INDEX.md")
    assert "Updated" in (mdir / "project.md").read_text()


async def test_compact_knowledge_falls_back_to_full_on_git_failure(tmp_path, monkeypatch):
    mdir = tmp_path / ".sigil" / "memory"
    mdir.mkdir(parents=True)
    (mdir / "project.md").write_text("# Project\nOld")
    (mdir / "INDEX.md").write_text("<!-- head: aaa111 | updated: 2026-01-01 -->\n# Index")

    full_files = {"project.md": "# Project\nFull rebuild"}
    resp = _make_json_response(full_files)

    async def fake_acompletion(**kwargs):
        return resp

    _patch_common(monkeypatch, tmp_path, head="ddd444")
    monkeypatch.setattr("sigil.pipeline.knowledge.acompletion", fake_acompletion)
    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)

    async def fake_arun(cmd, *, cwd=None, timeout=30):
        return 1, "", "git error"

    monkeypatch.setattr("sigil.pipeline.knowledge.arun", fake_arun)

    result = await compact_knowledge(tmp_path, "test-model", "full discovery context")

    assert result == str(mdir / "INDEX.md")
    assert "Full rebuild" in (mdir / "project.md").read_text()


async def test_compact_knowledge_malformed_json_returns_empty(tmp_path, monkeypatch):
    mdir = tmp_path / ".sigil" / "memory"
    mdir.mkdir(parents=True)

    msg = MagicMock()
    msg.content = "not valid json at all"
    msg.tool_calls = None
    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = "stop"
    resp = MagicMock()
    resp.choices = [choice]

    async def fake_acompletion(**kw):
        return resp

    _patch_common(monkeypatch, tmp_path)
    monkeypatch.setattr("sigil.pipeline.knowledge.acompletion", fake_acompletion)
    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)

    result = await compact_knowledge(tmp_path, "test-model", "context")
    assert result == ""


async def test_incremental_parse_failure_rebuilds_index(tmp_path, monkeypatch):
    mdir = tmp_path / ".sigil" / "memory"
    mdir.mkdir(parents=True)
    (mdir / "project.md").write_text("# Project Overview\nContent here")
    (mdir / "patterns.md").write_text("# Coding Patterns\nPattern stuff")
    (mdir / "INDEX.md").write_text(
        "<!-- head: aaa111 | updated: 2026-01-01 -->\n"
        "# Knowledge Index\n\n## project.md\nStale description"
    )

    msg = MagicMock()
    msg.content = "not valid json at all"
    msg.tool_calls = None
    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = "stop"
    resp = MagicMock()
    resp.choices = [choice]

    async def fake_acompletion(**kw):
        return resp

    _patch_common(monkeypatch, tmp_path, head="bbb222")
    monkeypatch.setattr("sigil.pipeline.knowledge.acompletion", fake_acompletion)
    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)

    async def fake_arun(cmd, *, cwd=None, timeout=30):
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd
        if "--name-only" in cmd_str:
            return 0, "sigil/foo.py\n", ""
        if "log" in cmd_str:
            return 0, "bbb222 some commit\n", ""
        if "diff" in cmd_str and "--" in cmd_str:
            return 0, "diff --git a/file ...\n+new line", ""
        return 1, "", "unknown"

    monkeypatch.setattr("sigil.pipeline.knowledge.arun", fake_arun)

    result = await compact_knowledge(tmp_path, "test-model", "discovery context")

    assert result == str(mdir / "INDEX.md")
    index_content = (mdir / "INDEX.md").read_text()
    assert "project.md" in index_content
    assert "patterns.md" in index_content
    assert "bbb222" in index_content


async def test_full_compact_parse_failure_rebuilds_index(tmp_path, monkeypatch):
    mdir = tmp_path / ".sigil" / "memory"
    mdir.mkdir(parents=True)
    (mdir / "project.md").write_text("# Project Overview\nExisting content")

    msg = MagicMock()
    msg.content = "garbage response"
    msg.tool_calls = None
    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = "stop"
    resp = MagicMock()
    resp.choices = [choice]

    async def fake_acompletion(**kw):
        return resp

    _patch_common(monkeypatch, tmp_path)
    monkeypatch.setattr("sigil.pipeline.knowledge.acompletion", fake_acompletion)
    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)

    result = await compact_knowledge(tmp_path, "test-model", "context")

    assert result == str(mdir / "INDEX.md")
    index_content = (mdir / "INDEX.md").read_text()
    assert "project.md" in index_content
    assert "abc123" in index_content


async def test_compact_knowledge_truncates_large_discovery(tmp_path, monkeypatch):
    mdir = tmp_path / ".sigil" / "memory"
    mdir.mkdir(parents=True)

    files = {"project.md": "# Project\nSmall"}
    resp = _make_json_response(files)

    prompts_seen = []

    async def fake_acompletion(**kwargs):
        prompts_seen.append(kwargs["messages"][0]["content"])
        return resp

    _patch_common(monkeypatch, tmp_path)
    monkeypatch.setattr("sigil.pipeline.knowledge.acompletion", fake_acompletion)
    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)
    monkeypatch.setattr("sigil.pipeline.knowledge.get_context_window", lambda m: 10_000)
    monkeypatch.setattr("sigil.pipeline.knowledge.get_max_output_tokens", lambda m: 2_000)

    huge_context = "x" * 500_000
    result = await compact_knowledge(tmp_path, "test-model", huge_context)

    assert result == str(mdir / "INDEX.md")
    assert "truncated" in prompts_seen[0]
    assert len(prompts_seen[0]) < 500_000


async def test_compact_knowledge_incremental_dedup_reads(tmp_path, monkeypatch):
    mdir = tmp_path / ".sigil" / "memory"
    mdir.mkdir(parents=True)
    (mdir / "project.md").write_text("# Project\nContent")
    (mdir / "INDEX.md").write_text(
        "<!-- head: aaa111 | updated: 2026-01-01 -->\n# Knowledge Index\n\n## project.md\nProject info"
    )

    tc1 = _make_tool_call("c1", "read_knowledge_file", {"filename": "project.md"})
    tc2 = _make_tool_call("c2", "read_knowledge_file", {"filename": "project.md"})

    msg1 = MagicMock()
    msg1.tool_calls = [tc1, tc2]
    msg1.content = None
    choice1 = MagicMock()
    choice1.message = msg1
    choice1.finish_reason = "tool_calls"
    resp1 = MagicMock()
    resp1.choices = [choice1]

    updated_files = {"project.md": "# Project\nUpdated"}
    resp2 = _make_json_response(updated_files, "# Knowledge Index\n\n## project.md\nUpdated")

    call_count = {"n": 0}
    tool_responses = []

    async def fake_acompletion(**kwargs):
        idx = call_count["n"]
        call_count["n"] += 1
        if idx > 0:
            for msg in kwargs["messages"]:
                if isinstance(msg, dict) and msg.get("role") == "tool":
                    tool_responses.append(msg["content"])
        return [resp1, resp2][idx]

    _patch_common(monkeypatch, tmp_path, head="eee555")
    monkeypatch.setattr("sigil.pipeline.knowledge.acompletion", fake_acompletion)
    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)

    async def fake_arun(cmd, *, cwd=None, timeout=30):
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd
        if "--name-only" in cmd_str:
            return 0, "sigil/main.py\n", ""
        if "log" in cmd_str:
            return 0, "eee555 update main\n", ""
        if "diff" in cmd_str and "--" in cmd_str:
            return 0, "diff --git a/sigil/main.py ...\n+changed", ""
        return 1, "", "unknown"

    monkeypatch.setattr("sigil.pipeline.knowledge.arun", fake_arun)

    result = await compact_knowledge(tmp_path, "test-model", "discovery context")

    assert result == str(mdir / "INDEX.md")
    assert any("Already loaded" in r for r in tool_responses)


async def test_compact_knowledge_incremental_read_budget(tmp_path, monkeypatch):
    mdir = tmp_path / ".sigil" / "memory"
    mdir.mkdir(parents=True)
    (mdir / "big.md").write_text("x" * 200_000)
    (mdir / "small.md").write_text("small content")
    (mdir / "INDEX.md").write_text(
        "<!-- head: aaa111 | updated: 2026-01-01 -->\n"
        "# Knowledge Index\n\n## big.md\nBig file\n\n## small.md\nSmall file"
    )

    tc1 = _make_tool_call("c1", "read_knowledge_file", {"filename": "big.md"})
    tc2 = _make_tool_call("c2", "read_knowledge_file", {"filename": "small.md"})

    msg1 = MagicMock()
    msg1.tool_calls = [tc1, tc2]
    msg1.content = None
    choice1 = MagicMock()
    choice1.message = msg1
    choice1.finish_reason = "tool_calls"
    resp1 = MagicMock()
    resp1.choices = [choice1]

    resp2 = _make_json_response(
        {"big.md": "# Big\nUpdated"},
        "# Knowledge Index\n\n## big.md\nUpdated\n\n## small.md\nSmall file",
    )

    call_count = {"n": 0}
    tool_responses_by_id = {}

    async def fake_acompletion(**kwargs):
        idx = call_count["n"]
        call_count["n"] += 1
        if idx > 0:
            for msg in kwargs["messages"]:
                if isinstance(msg, dict) and msg.get("role") == "tool":
                    tool_responses_by_id[msg["tool_call_id"]] = msg["content"]
        return [resp1, resp2][idx]

    _patch_common(monkeypatch, tmp_path, head="fff666")
    monkeypatch.setattr("sigil.pipeline.knowledge.acompletion", fake_acompletion)
    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)
    monkeypatch.setattr("sigil.pipeline.knowledge.MAX_TOOL_READ_CHARS", 50_000)

    async def fake_arun(cmd, *, cwd=None, timeout=30):
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd
        if "--name-only" in cmd_str:
            return 0, "sigil/big.py\n", ""
        if "log" in cmd_str:
            return 0, "fff666 update big\n", ""
        if "diff" in cmd_str and "--" in cmd_str:
            return 0, "diff --git a/sigil/big.py ...\n+changed", ""
        return 1, "", "unknown"

    monkeypatch.setattr("sigil.pipeline.knowledge.arun", fake_arun)

    result = await compact_knowledge(tmp_path, "test-model", "discovery context")

    assert result == str(mdir / "INDEX.md")
    assert "budget exceeded" in tool_responses_by_id.get("c2", "").lower()


async def test_select_memory_calls_llm_and_loads(tmp_path, monkeypatch):
    mdir = tmp_path / ".sigil" / "memory"
    mdir.mkdir(parents=True)
    (mdir / "INDEX.md").write_text("# Index\n## arch.md\nArchitecture info")
    (mdir / "arch.md").write_text("architecture content")

    tc = _make_tool_call("c1", "load_memory_files", {"filenames": ["arch.md"]})
    msg = MagicMock()
    msg.tool_calls = [tc]
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]

    async def fake_acompletion(**kw):
        return resp

    monkeypatch.setattr("sigil.pipeline.knowledge.acompletion", fake_acompletion)
    monkeypatch.setattr("sigil.core.agent.acompletion", fake_acompletion)
    monkeypatch.setattr(
        "sigil.pipeline.knowledge.memory_dir",
        lambda repo: repo / ".sigil" / "memory",
    )

    result = await select_memory(tmp_path, "test-model", "find dead code")
    assert ".sigil/memory/arch.md" in result
    assert result[".sigil/memory/arch.md"] == "architecture content"


async def test_select_memory_no_index(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "sigil.pipeline.knowledge.memory_dir",
        lambda repo: repo / ".sigil" / "memory",
    )
    result = await select_memory(tmp_path, "test-model", "anything")
    assert result == {}


async def test_is_knowledge_stale_no_index(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "sigil.pipeline.knowledge.memory_dir",
        lambda repo: repo / ".sigil" / "memory",
    )
    assert await is_knowledge_stale(tmp_path) is True


async def test_is_knowledge_stale_manifest_matches(tmp_path, monkeypatch):
    mdir = tmp_path / ".sigil" / "memory"
    mdir.mkdir(parents=True)
    (mdir / "INDEX.md").write_text(
        "<!-- head: abc123 | manifest: aabbccdd00112233445566778899aabbccddeeff00112233445566778899aabb | updated: 2026-01-01 -->\n# Index"
    )

    monkeypatch.setattr(
        "sigil.pipeline.knowledge.memory_dir",
        lambda repo: repo / ".sigil" / "memory",
    )

    async def fake_compute(r):
        return "aabbccdd00112233445566778899aabbccddeeff00112233445566778899aabb"

    monkeypatch.setattr("sigil.pipeline.knowledge.compute_manifest_hash", fake_compute)
    assert await is_knowledge_stale(tmp_path) is False


async def test_is_knowledge_stale_manifest_differs(tmp_path, monkeypatch):
    mdir = tmp_path / ".sigil" / "memory"
    mdir.mkdir(parents=True)
    (mdir / "INDEX.md").write_text(
        "<!-- head: abc123 | manifest: aabbccdd00112233445566778899aabbccddeeff00112233445566778899aabb | updated: 2026-01-01 -->\n# Index"
    )

    monkeypatch.setattr(
        "sigil.pipeline.knowledge.memory_dir",
        lambda repo: repo / ".sigil" / "memory",
    )

    async def fake_compute(r):
        return "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"

    monkeypatch.setattr("sigil.pipeline.knowledge.compute_manifest_hash", fake_compute)
    assert await is_knowledge_stale(tmp_path) is True
