import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from sigil.state.memory import (
    _write_frontmatter,
    compute_manifest_hash,
    load_manifest_hash,
    update_working,
)


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
            "sigil.state.memory.acompletion",
            new_callable=AsyncMock,
            return_value=_mock_llm_response("new body"),
        ) as mock_llm,
        patch("sigil.state.memory.now_utc", return_value="2026-01-01T00:00:00Z"),
        patch("sigil.state.memory.safe_max_tokens", return_value=4096),
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
            "sigil.state.memory.acompletion",
            new_callable=AsyncMock,
            return_value=_mock_llm_response("generated body"),
        ),
        patch("sigil.state.memory.now_utc", return_value="2026-03-22T12:00:00Z"),
        patch("sigil.state.memory.safe_max_tokens", return_value=4096),
    ):
        result = await update_working(tmp_path, "gpt-4o", "context")

    assert memory_path.exists()
    assert result == str(memory_path)
    written = memory_path.read_text()

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
        patch("sigil.state.memory.acompletion", side_effect=capture_llm),
        patch("sigil.state.memory.now_utc", return_value="2026-01-01T00:00:00Z"),
        patch("sigil.state.memory.safe_max_tokens", return_value=4096),
    ):
        await update_working(tmp_path, "gpt-4o", "first scan")
        await update_working(tmp_path, "gpt-4o", "second scan")

    assert "first run" in call_prompts[0].lower()
    assert "memory from run 1" in call_prompts[1]
    assert "existing working.md" in call_prompts[1].lower()

    final = (tmp_path / ".sigil" / "memory" / "working.md").read_text()
    assert "memory from run 2" in final


def _git(repo, *args):
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _init_repo(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@test.com")
    _git(tmp_path, "config", "user.name", "Test")


@pytest.mark.asyncio
async def test_manifest_hash_deterministic(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "foo.py").write_text("print('hello')")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "init")

    h1 = await compute_manifest_hash(tmp_path)
    h2 = await compute_manifest_hash(tmp_path)

    assert h1 == h2
    assert len(h1) == 64


@pytest.mark.asyncio
async def test_manifest_hash_changes_on_code_change(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "foo.py").write_text("print('hello')")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "init")

    h1 = await compute_manifest_hash(tmp_path)

    (tmp_path / "foo.py").write_text("print('world')")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "change")

    h2 = await compute_manifest_hash(tmp_path)

    assert h1 != h2


@pytest.mark.asyncio
async def test_manifest_hash_ignores_memory_files(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "foo.py").write_text("print('hello')")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "init")

    h1 = await compute_manifest_hash(tmp_path)

    memory_dir = tmp_path / ".sigil" / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "working.md").write_text("some memory")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "add memory")

    h2 = await compute_manifest_hash(tmp_path)

    assert h1 == h2


@pytest.mark.asyncio
async def test_manifest_hash_stable_across_amend(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "foo.py").write_text("print('hello')")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "init")

    h1 = await compute_manifest_hash(tmp_path)

    memory_dir = tmp_path / ".sigil" / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "working.md").write_text(f"manifest_hash: {h1}")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "--amend", "--no-edit")

    h2 = await compute_manifest_hash(tmp_path)

    assert h1 == h2


def test_load_manifest_hash_from_working(tmp_path):
    memory_dir = tmp_path / ".sigil" / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "working.md").write_text(
        "---\nlast_updated: '2026-01-01'\nmanifest_hash: abc123\n---\n\nbody\n"
    )

    assert load_manifest_hash(tmp_path) == "abc123"


def test_load_manifest_hash_missing_file(tmp_path):
    assert load_manifest_hash(tmp_path) == ""


def test_load_manifest_hash_no_hash_in_frontmatter(tmp_path):
    memory_dir = tmp_path / ".sigil" / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "working.md").write_text("---\nlast_updated: '2026-01-01'\n---\n\nbody\n")

    assert load_manifest_hash(tmp_path) == ""


@pytest.mark.asyncio
async def test_update_working_stores_manifest_hash(tmp_path):
    with (
        patch(
            "sigil.state.memory.acompletion",
            new_callable=AsyncMock,
            return_value=_mock_llm_response("new body"),
        ),
        patch("sigil.state.memory.now_utc", return_value="2026-01-01T00:00:00Z"),
        patch("sigil.state.memory.safe_max_tokens", return_value=4096),
    ):
        await update_working(tmp_path, "gpt-4o", "context", manifest_hash="deadbeef")

    written = (tmp_path / ".sigil" / "memory" / "working.md").read_text()
    parsed = yaml.safe_load(written.split("---")[1])
    assert parsed["manifest_hash"] == "deadbeef"
