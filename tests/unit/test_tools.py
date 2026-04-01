from unittest.mock import AsyncMock, patch

from sigil.core.tools import make_run_tests_tool
from sigil.pipeline.models import FileTracker


async def test_make_run_tests_tool_uses_relevant_tests(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    tracker = FileTracker()
    tracker.modified.add("sigil/core/utils.py")

    with (
        patch(
            "sigil.core.tools.get_relevant_tests",
            new=AsyncMock(return_value=["tests/unit/test_utils.py"]),
        ),
        patch("sigil.core.tools.arun", new=AsyncMock(return_value=(0, "ok\n", ""))) as mocked_arun,
    ):
        tool = make_run_tests_tool(repo, None, tracker)
        result = await tool.handler(
            {"repro_test": "tests/unit/test_utils.py::test_arun_exec_success"}
        )

    assert "PASS" in result.content
    mocked_arun.assert_awaited_once()
    assert mocked_arun.await_args.args[0] == [
        "pytest",
        "tests/unit/test_utils.py",
        "tests/unit/test_utils.py::test_arun_exec_success",
    ]


async def test_make_run_tests_tool_falls_back_to_all_tests(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    tracker = FileTracker()

    with (
        patch("sigil.core.tools.get_relevant_tests", new=AsyncMock(return_value=[])),
        patch(
            "sigil.core.tools.arun", new=AsyncMock(return_value=(1, "", "failed"))
        ) as mocked_arun,
    ):
        tool = make_run_tests_tool(repo, None, tracker)
        result = await tool.handler({})

    assert "FAIL" in result.content
    assert mocked_arun.await_args.args[0] == ["pytest", "tests"]
