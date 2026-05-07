import pytest

from sigil.core.utils import (
    arun,
    find_all_match_locations,
    format_ambiguous_matches,
    normalize_for_fuzzy_match,
    truncate_tool_result,
)


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
    rc, stdout, _ = await arun("echo abc | tr a-z A-Z")
    assert rc == 0
    assert stdout.strip() == "ABC"


async def test_arun_timeout():
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


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("‘hello’", "'hello'"),
        ("“hello”", '"hello"'),
        ("a—b", "a-b"),
        ("a–b", "a-b"),
        ("a‐b", "a-b"),
        ("a−b", "a-b"),
        ("a b", "a b"),
        ("a b", "a b"),
        ("a　b", "a b"),
    ],
)
def test_normalize_character_classes(raw, expected):
    assert normalize_for_fuzzy_match(raw) == expected


def test_normalize_strips_trailing_whitespace_per_line():
    raw = "line one   \nline two\t\nline three"
    assert normalize_for_fuzzy_match(raw) == "line one\nline two\nline three"


def test_normalize_idempotent_for_ascii_input():
    raw = "def foo():\n    return 1\n"
    assert normalize_for_fuzzy_match(raw) == raw


def test_truncate_tool_result_under_limit():
    content = "short content"
    assert truncate_tool_result(content, 50_000) == content


def test_truncate_tool_result_at_limit():
    content = "x" * 1000
    assert truncate_tool_result(content, 1000) == content


def test_truncate_tool_result_over_limit():
    content = "A" * 800 + "B" * 300
    result = truncate_tool_result(content, 1000)
    assert "truncated" in result
    assert "chars omitted" in result
    assert result.startswith("A" * 800)
    assert result.endswith("B" * 200)
    omitted = 1100 - 1000
    assert f"{omitted} chars omitted" in result


def test_truncate_tool_result_empty_string():
    assert truncate_tool_result("", 50_000) == ""


def test_truncate_tool_result_marker_has_guidance():
    content = "x" * 200
    result = truncate_tool_result(content, 100)
    assert "offset" in result.lower() or "limit" in result.lower()


def test_truncate_tool_result_head_tail_split():
    content = "H" * 160 + "M" * 40 + "T" * 100
    result = truncate_tool_result(content, 200)
    head_size = int(200 * 0.8)
    tail_size = 200 - head_size
    assert result.startswith("H" * head_size)
    assert result.endswith("T" * tail_size)
    assert "truncated" in result
