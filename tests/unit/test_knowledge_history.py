import json
from types import SimpleNamespace

import pytest

from sigil.core.agent import Tool
from sigil.pipeline.knowledge import (
    MAX_HISTORY_CHARS,
    MAX_HISTORY_DIFF_LINES,
    clear_memory_cache,
    git_show_history,
    select_memory,
)


@pytest.mark.asyncio
async def test_git_show_history_includes_recent_commit_messages_and_diffs(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    async def fake_arun(cmd, *, cwd=None, timeout=30):
        calls.append(cmd)
        if cmd[:2] == ["git", "log"]:
            return (
                0,
                "".join(
                    [
                        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\x1faaaaaaa\x1f2026-03-01\x1fFix parser regression\x1e",
                        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\x1fbbbbbbb\x1f2026-03-02\x1fRefine parser recovery\x1e",
                    ]
                ),
                "",
            )
        if cmd[:2] == ["git", "show"]:
            sha = cmd[6]
            if sha.startswith("a"):
                patch = (
                    "diff --git a/src/parser.py b/src/parser.py\n"
                    "@@ -1,2 +1,2 @@\n"
                    "-old parser\n"
                    "+new parser\n"
                )
            else:
                patch = (
                    "diff --git a/src/parser.py b/src/parser.py\n"
                    "@@ -8,2 +8,2 @@\n"
                    "-fallback\n"
                    "+resilient fallback\n"
                )
            return 0, patch, ""
        return 1, "", "unexpected command"

    monkeypatch.setattr("sigil.pipeline.knowledge.arun", fake_arun)

    history = await git_show_history(tmp_path, "src/parser.py")

    assert "Fix parser regression" in history
    assert "Refine parser recovery" in history
    assert "new parser" in history
    assert len(history) <= MAX_HISTORY_CHARS
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_git_show_history_returns_empty_for_invalid_path(tmp_path):
    result = await git_show_history(tmp_path, "../secret.py")
    assert result == ""


@pytest.mark.asyncio
async def test_git_show_history_truncates_large_diff_output(tmp_path, monkeypatch):
    async def fake_arun(cmd, *, cwd=None, timeout=30):
        if cmd[:2] == ["git", "log"]:
            return (
                0,
                "".join(
                    [
                        "cccccccccccccccccccccccccccccccccccccccc\x1fccccccc\x1f2026-03-03\x1fStabilize formatting\x1e",
                    ]
                ),
                "",
            )
        if cmd[:2] == ["git", "show"]:
            lines = ["diff --git a/src/format.py b/src/format.py", "@@ -1,1 +1,1 @@"]
            lines.extend(f"+ line {idx}" for idx in range(20))
            return 0, "\n".join(lines), ""
        return 1, "", "unexpected command"

    monkeypatch.setattr("sigil.pipeline.knowledge.arun", fake_arun)

    history = await git_show_history(tmp_path, "src/format.py")

    assert "Stabilize formatting" in history
    assert "line 0" in history
    assert f"line {MAX_HISTORY_DIFF_LINES}" not in history


@pytest.mark.asyncio
async def test_select_memory_appends_history_summary(tmp_path, monkeypatch):
    clear_memory_cache()

    async def fake_acompletion(**kwargs):
        tool_call = SimpleNamespace(
            function=SimpleNamespace(arguments=json.dumps({"filenames": ["architecture.md"]}))
        )
        message = SimpleNamespace(tool_calls=[tool_call])
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice])

    async def fake_history(repo, filename):
        return "- 2026-03-01 abc123 Refactor parser\n  diff --git a/src/parser.py b/src/parser.py"

    monkeypatch.setattr("sigil.pipeline.knowledge.acompletion", fake_acompletion)
    monkeypatch.setattr("sigil.pipeline.knowledge.safe_max_tokens", lambda *a, **k: 1024)
    monkeypatch.setattr(
        "sigil.pipeline.knowledge.load_index",
        lambda repo: "# Knowledge Index\n\n## architecture.md\nArchitecture",
    )
    monkeypatch.setattr(
        "sigil.pipeline.knowledge.load_memory_files",
        lambda repo, filenames: {".sigil/memory/architecture.md": "Architecture content"},
    )
    monkeypatch.setattr("sigil.pipeline.knowledge.git_show_history", fake_history)

    result = await select_memory(tmp_path, "test-model", "inspect parser behavior")

    content = result[".sigil/memory/architecture.md"]
    assert "Architecture content" in content
    assert "Recent git history" in content
    assert "Refactor parser" in content


@pytest.mark.asyncio
async def test_tool_execute_accepts_sync_and_async_handlers() -> None:
    sync_tool = Tool(
        name="sync",
        description="sync tool",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: "sync result",
    )

    async def _async_handler(args):
        return "async result"

    async_tool = Tool(
        name="async",
        description="async tool",
        parameters={"type": "object", "properties": {}},
        handler=_async_handler,
    )

    sync_result = await sync_tool.execute({})
    async_result = await async_tool.execute({})

    assert sync_result.content == "sync result"
    assert async_result.content == "async result"
