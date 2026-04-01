from unittest.mock import MagicMock

import pytest

from sigil.pipeline.style import extract_style


@pytest.mark.asyncio
async def test_extract_style_happy_path(tmp_path, monkeypatch):
    repo = tmp_path
    (repo / "sigil").mkdir()
    (repo / "sigil" / "pipeline.py").write_text(
        "def foo_bar(x):\n    if x:\n        return x\n    return None\n"
    )
    (repo / "sigil" / "helpers.py").write_text(
        "def build_item(value):\n    result = value + 1\n    return result\n"
    )

    async def fake_arun(cmd, *, cwd=None, timeout=30):
        return 0, "sigil/pipeline.py\nsigil/helpers.py\n", ""

    msg = MagicMock()
    msg.content = "# Style Lexicon\n\n- Naming: snake_case\n"
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]

    async def fake_acompletion(**kwargs):
        return resp

    monkeypatch.setattr("sigil.pipeline.style.arun", fake_arun)
    monkeypatch.setattr("sigil.pipeline.style.acompletion", fake_acompletion)

    result = await extract_style(repo, "test-model")

    assert result == str(repo / ".sigil" / "memory" / "style.md")
    assert (
        repo / ".sigil" / "memory" / "style.md"
    ).read_text() == "# Style Lexicon\n\n- Naming: snake_case\n"


@pytest.mark.asyncio
async def test_extract_style_handles_empty_repo_list(tmp_path, monkeypatch):
    async def fake_arun(cmd, *, cwd=None, timeout=30):
        return 0, "\n", ""

    monkeypatch.setattr("sigil.pipeline.style.arun", fake_arun)

    result = await extract_style(tmp_path, "test-model")

    assert result is None
    assert not (tmp_path / ".sigil" / "memory" / "style.md").exists()


@pytest.mark.asyncio
async def test_extract_style_uses_all_candidates_when_small_repo(tmp_path, monkeypatch):
    repo = tmp_path
    (repo / "a.py").write_text("def a():\n    return 1\n")
    (repo / "b.py").write_text("def b():\n    return 2\n")

    seen = []

    async def fake_arun(cmd, *, cwd=None, timeout=30):
        return 0, "a.py\nb.py\n", ""

    msg = MagicMock()
    msg.content = "# Style Lexicon\n"
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]

    async def fake_acompletion(**kwargs):
        seen.append(kwargs["messages"][0]["content"])
        return resp

    monkeypatch.setattr("sigil.pipeline.style.arun", fake_arun)
    monkeypatch.setattr("sigil.pipeline.style.acompletion", fake_acompletion)

    result = await extract_style(repo, "test-model")

    assert result == str(repo / ".sigil" / "memory" / "style.md")
    assert "a.py" in seen[0]
    assert "b.py" in seen[0]
