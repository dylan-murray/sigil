from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from sigil.memory import _write_frontmatter, update_working


def test_write_frontmatter_roundtrips():
    meta = {"last_updated": "2026-01-01T00:00:00Z", "version": 2}
    body = "# Working Memory\n\nSome content here."

    result = _write_frontmatter(meta, body)

    lines = result.split("\n")
    assert lines[0] == "---"
    close_idx = lines.index("---", 1)
    parsed = yaml.safe_load("\n".join(lines[1:close_idx]))
    assert parsed == meta
    body_after = "\n".join(lines[close_idx + 2 :]).strip()
    assert body_after == body


def test_write_frontmatter_preserves_key_order():
    meta = {"zebra": 1, "alpha": 2, "middle": 3}
    result = _write_frontmatter(meta, "body")
    front_lines = result.split("---")[1].strip().split("\n")
    keys = [line.split(":")[0] for line in front_lines]
    assert keys == ["zebra", "alpha", "middle"]


def _mock_llm_response(content: str) -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    return resp


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "has_existing,expected_prompt_fragment",
    [
        (True, "existing working.md"),
        (False, "first run"),
    ],
    ids=["existing-memory", "first-run"],
)
async def test_update_working_prompt_branches(tmp_path, has_existing, expected_prompt_fragment):
    if has_existing:
        memory_dir = tmp_path / ".sigil" / "memory"
        memory_dir.mkdir(parents=True)
        (memory_dir / "working.md").write_text("prior knowledge")

    with (
        patch(
            "sigil.memory.acompletion",
            new_callable=AsyncMock,
            return_value=_mock_llm_response("new body"),
        ) as mock_llm,
        patch("sigil.memory.now_utc", return_value="2026-01-01T00:00:00Z"),
        patch("sigil.memory.get_max_output_tokens", return_value=4096),
    ):
        await update_working(tmp_path, "gpt-4o", "scan results")

    prompt = mock_llm.call_args[1]["messages"][0]["content"]
    assert expected_prompt_fragment in prompt.lower()


@pytest.mark.asyncio
async def test_update_working_creates_dir_and_writes(tmp_path):
    memory_path = tmp_path / ".sigil" / "memory" / "working.md"
    assert not memory_path.parent.exists()

    with (
        patch(
            "sigil.memory.acompletion",
            new_callable=AsyncMock,
            return_value=_mock_llm_response("generated body"),
        ),
        patch("sigil.memory.now_utc", return_value="2026-03-22T12:00:00Z"),
        patch("sigil.memory.get_max_output_tokens", return_value=4096),
    ):
        result = await update_working(tmp_path, "gpt-4o", "context")

    assert memory_path.exists()
    written = memory_path.read_text()
    assert written == result

    parsed_meta = yaml.safe_load(written.split("---")[1])
    assert parsed_meta["last_updated"] == "2026-03-22T12:00:00Z"
    assert "generated body" in written


@pytest.mark.asyncio
async def test_update_working_lifecycle(tmp_path):
    call_prompts = []

    async def capture_llm(**kwargs):
        call_prompts.append(kwargs["messages"][0]["content"])
        call_num = len(call_prompts)
        return _mock_llm_response(f"memory from run {call_num}")

    with (
        patch("sigil.memory.acompletion", side_effect=capture_llm),
        patch("sigil.memory.now_utc", return_value="2026-01-01T00:00:00Z"),
        patch("sigil.memory.get_max_output_tokens", return_value=4096),
    ):
        await update_working(tmp_path, "gpt-4o", "first scan")
        await update_working(tmp_path, "gpt-4o", "second scan")

    assert "first run" in call_prompts[0].lower()
    assert "memory from run 1" in call_prompts[1]
    assert "existing working.md" in call_prompts[1].lower()

    final = (tmp_path / ".sigil" / "memory" / "working.md").read_text()
    assert "memory from run 2" in final
