from unittest.mock import AsyncMock, patch

import pytest

from sigil.core.llm import (
    _split_at_tool_boundary,
    compact_messages,
    estimate_tokens,
)


def _make_tool_call(tc_id: str, name: str, args: str = "{}") -> dict:
    return {"id": tc_id, "function": {"name": name, "arguments": args}}


def test_estimate_tokens_counts_all_content_types():
    messages = [
        {"role": "user", "content": "hello world"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "a" * 400, "cache_control": {"type": "ephemeral"}}
            ],
        },
        {
            "role": "assistant",
            "content": "thinking",
            "tool_calls": [_make_tool_call("tc1", "read_file", "x" * 800)],
        },
        {"role": "tool", "tool_call_id": "tc1", "content": "file contents here"},
    ]
    result = estimate_tokens(messages)
    string_part = len("hello world") // 4
    list_part = 400 // 4
    assistant_part = len("thinking") // 4
    tc_part = 800 // 4
    tool_part = len("file contents here") // 4
    expected = string_part + list_part + assistant_part + tc_part + tool_part
    assert result == expected


def test_split_at_tool_boundary_never_splits_pairs():
    messages = [
        {"role": "user", "content": "initial prompt"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [_make_tool_call("tc1", "read_file")],
        },
        {"role": "tool", "tool_call_id": "tc1", "content": "file data"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [_make_tool_call("tc2", "apply_edit")],
        },
        {"role": "tool", "tool_call_id": "tc2", "content": "ok"},
        {"role": "assistant", "content": "done"},
    ]
    idx = _split_at_tool_boundary(messages, keep_recent=3)
    remaining = messages[idx:]
    for msg in remaining:
        if msg.get("role") == "tool":
            tc_id = msg["tool_call_id"]
            has_parent = any(
                tc_id in [tc["id"] for tc in m.get("tool_calls", [])]
                for m in remaining
                if m.get("role") == "assistant"
            )
            assert has_parent, f"Orphaned tool result {tc_id} after split at {idx}"

    assert messages[idx].get("role") != "tool"


@pytest.mark.asyncio
async def test_compact_messages_skips_below_threshold():
    messages = [
        {"role": "user", "content": "short"},
        {"role": "assistant", "content": "reply"},
    ]
    original = list(messages)
    result = await compact_messages(
        messages, "anthropic/claude-haiku-4-5-20251001", threshold_tokens=1000
    )
    assert result is False
    assert messages == original


@pytest.mark.asyncio
async def test_compact_messages_replaces_old_keeps_recent():
    old_msgs = [
        {"role": "user", "content": "x" * 400_000},
        {
            "role": "assistant",
            "content": "noted",
            "tool_calls": [_make_tool_call("tc1", "read_file")],
        },
        {"role": "tool", "tool_call_id": "tc1", "content": "y" * 100_000},
    ]
    recent_msgs = [
        {"role": "assistant", "content": "recent reply 1"},
        {"role": "user", "content": "recent question"},
        {"role": "assistant", "content": "recent reply 2"},
    ]
    messages = old_msgs + recent_msgs

    mock_response = AsyncMock()
    mock_response.choices = [AsyncMock()]
    mock_response.choices[0].message.content = "Summary of earlier work."

    with patch("sigil.core.llm.acompletion", return_value=mock_response) as mock_ac:
        result = await compact_messages(
            messages, "anthropic/claude-haiku-4-5-20251001", threshold_tokens=1000, keep_recent=3
        )

    assert result is True
    assert mock_ac.called
    assert messages[0]["role"] == "user"
    assert "[COMPACTED CONTEXT" in messages[0]["content"]
    assert "Summary of earlier work." in messages[0]["content"]
    for recent in recent_msgs:
        assert recent in messages


@pytest.mark.asyncio
async def test_compact_messages_survives_llm_failure():
    messages = [
        {"role": "user", "content": "x" * 400_000},
        {"role": "assistant", "content": "reply"},
        {"role": "user", "content": "followup"},
    ]
    original = list(messages)

    with patch("sigil.core.llm.acompletion", side_effect=RuntimeError("LLM down")):
        result = await compact_messages(
            messages, "anthropic/claude-haiku-4-5-20251001", threshold_tokens=1000
        )

    assert result is False
    assert messages == original
