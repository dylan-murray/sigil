from unittest.mock import AsyncMock, patch

from sigil.core.tester import get_relevant_tests


async def test_get_relevant_tests_finds_downstream_tests(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "tests").mkdir()

    async def fake_arun(cmd, cwd=None, timeout=30):
        assert cmd[:3] == ["grep", "-rlE", "sigil.core.utils"]
        return 0, "tests/unit/test_utils.py\n", ""

    with patch("sigil.core.tester.arun", side_effect=fake_arun):
        tests = await get_relevant_tests(repo, {"sigil/core/utils.py"})

    assert tests == ["tests/unit/test_utils.py"]


async def test_get_relevant_tests_includes_test_files_directly(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "tests").mkdir()

    with patch("sigil.core.tester.arun", new=AsyncMock()) as mocked_arun:
        tests = await get_relevant_tests(repo, {"tests/unit/test_utils.py"})

    assert tests == ["tests/unit/test_utils.py"]
    mocked_arun.assert_not_awaited()


async def test_get_relevant_tests_returns_empty_without_tests_dir(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    with patch("sigil.core.tester.arun", new=AsyncMock()) as mocked_arun:
        tests = await get_relevant_tests(repo, {"sigil/core/utils.py"})

    assert tests == []
    mocked_arun.assert_not_awaited()
