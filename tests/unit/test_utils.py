import pytest
from sigil.core.utils import arun, find_all_match_locations, format_ambiguous_matches


async def test_arun_exec_success():
    rc, stdout, stderr = await arun(["echo", "hello"])
    assert rc == 0
    assert stdout.strip() == "hello"


async def test_arun_exec_failure():
    rc, stdout, stderr = await arun(["false"])
    assert rc != 0


async def test_arun_shell_success():
    rc, stdout, stderr = await arun("echo hello world")
    assert rc == 0
    assert stdout.strip() == "hello world"


async def test_arun_shell_pipe():
    with pytest.raises(ValueError, match="contains unsafe shell characters"):
        await arun("echo abc | tr a-z A-Z")


async def test_arun_shell_injection_blocked():
    with pytest.raises(ValueError, match="contains unsafe shell characters"):
        await arun("echo hello; rm -rf /")


async def test_arun_shell_injection_ampersand():
    with pytest.raises(ValueError, match="contains unsafe shell characters"):
        await arun("echo hello && echo world")


async def test_arun_shell_injection_blocked():
    with pytest.raises(ValueError, match="contains unsafe shell characters"):
        await arun("echo hello; rm -rf /")


async def test_arun_shell_injection_ampersand():
    with pytest.raises(ValueError, match="contains unsafe shell characters"):
        await arun("echo hello && echo world")
    rc, stdout, stderr = await arun(["sleep", "10"], timeout=0.1)
    assert rc == 1
    assert "timed out" in stderr


async def test_arun_command_not_found():
    rc, stdout, stderr = await arun(["nonexistent_command_xyz"])
    assert rc == 1
    assert "not found" in stderr.lower() or "Command not found" in stderr


async def test_arun_cwd(tmp_path):
    rc, stdout, _ = await arun(["pwd"], cwd=tmp_path)
    assert rc == 0
    assert tmp_path.name in stdout


def test_find_all_match_locations():
    content = "a\nb\nc\nb\nd\nb\n"
    locs = find_all_match_locations(content, "b")
    assert locs == [2, 4, 6]


def test_find_all_match_locations_multiline():
    content = "def foo():\n    return 1\n\ndef bar():\n    return 1\n"
    locs = find_all_match_locations(content, "return 1")
    assert locs == [2, 5]


def test_format_ambiguous_matches_shows_context():
    content = "a = 1\nb = 2\nx = 10\nc = 3\nd = 4\nx = 10\ne = 5\n"
    result = format_ambiguous_matches(content, "x = 10", "test.py")
    assert "matches 2 locations" in result
    assert "Match at line 3" in result
    assert "Match at line 6" in result
    assert "a = 1" in result
    assert "d = 4" in result
