import pytest

from sigil.state.memory import load_working, update_working

from .conftest import model_for, skip_if_no_key


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider", ["openai", "anthropic", "gemini", "bedrock", "azure", "mistral"]
)
async def test_memory_lifecycle_real_llm(tmp_path, provider):
    skip_if_no_key(provider)
    model = model_for(provider)

    path1 = await update_working(
        tmp_path, model, "Added type hints to utils.py and fixed a broken import in cli.py."
    )

    memory_file = tmp_path / ".sigil" / "memory" / "working.md"
    assert memory_file.exists()
    assert path1 == str(memory_file)

    content1 = load_working(tmp_path)
    assert len(content1.strip()) > 0

    await update_working(
        tmp_path, model, "Opened PR #12 to remove dead code in executor.py. No issues filed."
    )

    content2 = load_working(tmp_path)
    assert content2 != content1
