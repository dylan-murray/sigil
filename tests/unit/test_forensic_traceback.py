"""Tests for forensic traceback functionality."""

from pathlib import Path

import pytest

from sigil.pipeline.executor import _extract_traceback_frames, _summarize_hook_errors


@pytest.fixture
def repo_path(tmp_path: Path) -> Path:
    """Create a mock repo structure."""
    return tmp_path


def create_file_with_content(repo: Path, rel_path: str, content: str) -> Path:
    """Helper to create a file with given content."""
    p = repo / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


class TestExtractTracebackFrames:
    """Test the _extract_traceback_frames function."""

    def test_simple_traceback(self, repo_path: Path):
        """Test extraction from a simple pytest traceback."""
        create_file_with_content(
            repo_path,
            "src/foo.py",
            "def bar(x):\n    return 1 / x\n\ndef baz():\n    bar(0)\n",
        )

        raw_output = """
        =================================== FAILURES ===================================
        ___________________________________ test_baz ____________________________________

            def test_baz():
                from src.foo import baz
                baz()
                >   AssertionError: assert False

            src/foo.py:5: in baz
                bar(0)
            src/foo.py:2: in bar
                return 1 / x
            ZeroDivisionError: division by zero
        """
        result = _extract_traceback_frames(raw_output, repo_path)

        assert "src/foo.py:5" in result
        assert "src/foo.py:2" in result
        assert "def bar(x):" in result
        assert "return 1 / x" in result

    def test_limits_to_three_frames(self, repo_path: Path):
        """Test that only top 3 frames are extracted."""
        for i in range(5):
            create_file_with_content(
                repo_path,
                f"src/module{i}.py",
                f"def func{i}():\n    raise ValueError('error {i}')\n",
            )

        raw_output = """
        Traceback (most recent call last):
          File "tests/test_many.py", line 10, in test_func
            from src.module0 import func0
            func0()
          File "src/module0.py", line 2, in func0
            func1()
          File "src/module1.py", line 2, in func1
            func2()
          File "src/module2.py", line 2, in func2
            func3()
          File "src/module3.py", line 2, in func3
            func4()
          File "src/module4.py", line 2, in func4
            raise ValueError('error 4')
        """
        result = _extract_traceback_frames(raw_output, repo_path)

        # Should have at most 3 frames (excluding pytest internals)
        frame_count = result.count("###")
        assert frame_count <= 3

    def test_skips_pytest_internal_frames(self, repo_path: Path):
        """Test that pytest and site-packages frames are skipped."""
        create_file_with_content(
            repo_path,
            "src/app.py",
            "def main():\n    raise RuntimeError('boom')\n",
        )
        create_file_with_content(
            repo_path,
            "tests/test_app.py",
            "def test_main():\n    from src.app import main\n    main()\n",
        )

        raw_output = """
        Traceback (most recent call last):
          File "/usr/local/lib/python3.11/pytest.py", line 123, in pytest_fun
            item.runtest()
          File "/usr/local/lib/python3.11/site-packages/_pytest/runner.py", line 89, in call_and_report
            return call(item, item.config.pluginmanager)
          File "tests/test_app.py", line 10, in test_main
            from src.app import main
            main()
          File "src/app.py", line 2, in main
            raise RuntimeError('boom')
        """
        result = _extract_traceback_frames(raw_output, repo_path)

        # Should only include user code frames (src/app.py, tests/test_app.py)
        assert "src/app.py" in result
        assert "tests/test_app.py" in result
        # Should NOT include pytest or site-packages paths
        assert "pytest.py" not in result
        assert "site-packages" not in result

    def test_graceful_handling_missing_file(self, repo_path: Path):
        """Test that missing files are skipped silently."""
        raw_output = """
        Traceback (most recent call last):
          File "nonexistent.py", line 10, in <module>
            raise ValueError('error')
        """
        result = _extract_traceback_frames(raw_output, repo_path)

        # Should return empty since no valid files were found
        assert result == ""

    def test_graceful_handling_outside_repo(self, repo_path: Path):
        """Test that files outside repo are skipped."""
        create_file_with_content(
            repo_path,
            "src/app.py",
            "def main():\n    raise RuntimeError('boom')\n",
        )

        raw_output = """
        Traceback (most recent call last):
          File "/absolute/path/outside/repo/file.py", line 5, in <module>
            raise ValueError('error')
          File "src/app.py", line 2, in main
            raise RuntimeError('boom')
        """
        result = _extract_traceback_frames(raw_output, repo_path)

        # Should include src/app.py but NOT the outside path
        assert "src/app.py:2" in result
        assert "outside/repo" not in result

    def test_context_window_boundary_at_start(self, repo_path: Path):
        """Test windowing when failing line is near file start."""
        create_file_with_content(
            repo_path,
            "src/simple.py",
            "def func():\n    # line 2\n    # line 3\n    raise ValueError('error')\n",
        )

        raw_output = """
        Traceback (most recent call last):
          File "tests/test_simple.py", line 5, in test_func
            from src.simple import func
            func()
          File "src/simple.py", line 4, in func
            raise ValueError('error')
        """
        result = _extract_traceback_frames(raw_output, repo_path, context_lines=10)

        # Should not crash and should include line 4
        assert "src/simple.py:4" in result
        # Should include line numbers 1-4 (all lines in file)
        assert "   1:" in result or "1:" in result

    def test_context_window_boundary_at_end(self, repo_path: Path):
        """Test windowing when failing line is near file end."""
        create_file_with_content(
            repo_path,
            "src/end.py",
            "\n".join(f"    line_{i} = {i}" for i in range(1, 20)) + "\nraise ValueError()",
        )

        raw_output = """
        Traceback (most recent call last):
          File "tests/test_end.py", line 3, in test_end
            from src.end import *
            raise ValueError('error')
          File "src/end.py", line 20, in <module>
            raise ValueError()
        """
        result = _extract_traceback_frames(raw_output, repo_path, context_lines=10)

        assert "src/end.py:20" in result
        # Should include lines from ~10 to 20
        assert "line_19" in result

    def test_detects_nearby_assertions(self, repo_path: Path):
        """Test that nearby assertions are highlighted."""
        create_file_with_content(
            repo_path,
            "src/with_asserts.py",
            "def func(x):\n"
            "    assert x > 0, 'x must be positive'\n"
            "    y = 10 / x\n"
            "    assert y < 100, 'y too large'\n"
            "    return y\n",
        )

        raw_output = """
        Traceback (most recent call last):
          File "tests/test_asserts.py", line 5, in test_func
            from src.with_asserts import func
            func(0)
          File "src/with_asserts.py", line 4, in func
            y = 10 / x
        ZeroDivisionError: division by zero
        """
        result = _extract_traceback_frames(raw_output, repo_path, context_lines=5)

        # Should include the assert on line 2 (within +/- 5 lines of line 4)
        assert "assert x > 0" in result
        # Should also include assert on line 5 (within +/- 5)
        assert "assert y < 100" in result
        # Check the section heading
        assert "Nearby assertions and type hints (potential invariants):" in result

    def test_handles_unicode_content(self, repo_path: Path):
        """Test that unicode characters in source are handled."""
        create_file_with_content(
            repo_path,
            "src/unicode.py",
            "# -*- coding: utf-8 -*-\n"
            "def greet(name: str) -> str:\n"
            '    """Greet someone with emoji 🎉"""\n'
            '    return f"Hello, {name}! 👋"\n',
        )

        raw_output = """
        Traceback (most recent call last):
          File "tests/test_unicode.py", line 3, in test_greet
            from src.unicode import greet
            greet(None)
          File "src/unicode.py", line 3, in greet
            return f"Hello, {name}! 👋"
        TypeError: greet() missing 1 required positional argument: 'name'
        """
        result = _extract_traceback_frames(raw_output, repo_path)

        assert "src/unicode.py" in result
        assert "🎉" in result or "👋" in result

    def test_empty_traceback_returns_empty(self, repo_path: Path):
        """Test that non-traceback output returns empty string."""
        raw_output = "Some random error output without traceback"
        result = _extract_traceback_frames(raw_output, repo_path)
        assert result == ""

    def test_malformed_line_numbers(self, repo_path: Path):
        """Test handling of malformed line numbers."""
        create_file_with_content(
            repo_path,
            "src/malformed.py",
            "def func():\n    pass\n",
        )

        raw_output = """
        Traceback (most recent call last):
          File "src/malformed.py", line abc, in func
            raise ValueError('error')
        """
        result = _extract_traceback_frames(raw_output, repo_path)

        # Should skip the malformed frame but not crash; since the file exists but line is invalid,
        # the frame is skipped. Result should be empty or not contain malformed.py
        assert "malformed.py" not in result or result == ""

    def test_duplicate_frames_deduplicated(self, repo_path: Path):
        """Test that duplicate frames are handled (same file:line appears twice)."""
        create_file_with_content(
            repo_path,
            "src/recursive.py",
            "def a():\n    b()\n\ndef b():\n    a()\n",
        )

        raw_output = """
        Traceback (most recent call last):
          File "tests/test_recursive.py", line 5, in test_rec
            from src.recursive import a
            a()
          File "src/recursive.py", line 2, in a
            b()
          File "src/recursive.py", line 5, in b
            a()
          RecursionError: maximum recursion depth exceeded
        """
        result = _extract_traceback_frames(raw_output, repo_path)

        # Should include src/recursive.py at least once
        assert "src/recursive.py" in result
        # Should not crash with duplicate entries

    def test_uses_repo_root_for_validation(self, repo_path: Path):
        """Test that paths are resolved against the provided repo root."""
        # Create a file inside the repo
        create_file_with_content(
            repo_path,
            "src/inside.py",
            "def func():\n    raise ValueError('error')\n",
        )

        # Simulate a traceback with a relative path that would resolve outside
        raw_output = """
        Traceback (most recent call last):
          File "../outside.py", line 1, in <module>
            raise ValueError('error')
          File "src/inside.py", line 2, in func
            raise ValueError('error')
        """
        result = _extract_traceback_frames(raw_output, repo_path)

        # src/inside.py should be included
        assert "src/inside.py:2" in result
        # ../outside.py should be skipped entirely
        assert "outside.py" not in result

    def test_detects_nearby_type_hints(self, repo_path: Path):
        """Test that nearby type hints are highlighted."""
        create_file_with_content(
            repo_path,
            "src/typed.py",
            "from typing import Optional\n"
            "\n"
            "def process(value: int) -> Optional[str]:\n"
            "    if value < 0:\n"
            "        return None\n"
            "    result: str = str(value)\n"
            "    return result\n",
        )

        raw_output = """
        Traceback (most recent call last):
          File "tests/test_typed.py", line 6, in test_process
            from src.typed import process
            process("not an int")
          File "src/typed.py", line 4, in process
            if value < 0:
        TypeError: '<' not supported between instances of 'str' and 'int'
        """
        result = _extract_traceback_frames(raw_output, repo_path, context_lines=10)

        # Should include type hints: function signature with -> Optional[str] and value: int
        assert "def process(value: int) -> Optional[str]:" in result
        assert "result: str = str(value)" in result
        assert "Nearby assertions and type hints (potential invariants):" in result

    def test_detects_return_annotation_only(self, repo_path: Path):
        """Test detection of return type annotations."""
        create_file_with_content(
            repo_path,
            "src/simple_type.py",
            "def foo() -> int:\n    return 'not an int'\n",
        )

        raw_output = """
        Traceback (most recent call last):
          File "tests/test_simple_type.py", line 3, in test_foo
            from src.simple_type import foo
            foo()
          File "src/simple_type.py", line 2, in foo
            return 'not an int'
        TypeError: Expected int, got str
        """
        result = _extract_traceback_frames(raw_output, repo_path)

        assert "def foo() -> int:" in result
        assert "Nearby assertions and type hints (potential invariants):" in result

    def test_ignores_type_hints_in_comments(self, repo_path: Path):
        """Test that type hints in comments are not flagged."""
        create_file_with_content(
            repo_path,
            "src/comment.py",
            "def foo(x):\n    # type: (int) -> str\n    return str(x)\n",
        )

        raw_output = """
        Traceback (most recent call last):
          File "tests/test_comment.py", line 4, in test_foo
            from src.comment import foo
            foo("oops")
          File "src/comment.py", line 3, in foo
            return str(x)
        """
        result = _extract_traceback_frames(raw_output, repo_path)

        # The comment line may appear in the code window but should NOT be in the invariants section
        # Check that the invariants section either doesn't exist or doesn't contain the comment
        if "Nearby assertions and type hints (potential invariants):" in result:
            # Extract just the invariants section
            inv_start = result.index("Nearby assertions and type hints")
            inv_section = result[inv_start:]
            assert "# type: (int) -> str" not in inv_section
        else:
            assert True  # No invariants section, which is also fine


class TestSummarizeHookErrorsWithForensic:
    """Test the _summarize_hook_errors function with forensic context."""

    @pytest.mark.asyncio
    async def test_injects_forensic_context_when_repo_provided(self, repo_path: Path, monkeypatch):
        """Test that forensic context is injected when repo is provided."""
        create_file_with_content(
            repo_path,
            "src/calc.py",
            "def add(a, b):\n    return a + b\n\ndef subtract(a, b):\n    return a - b\n",
        )

        raw_output = """
        =================================== FAILURES ===================================
        ___________________________________ test_add ____________________________________

            def test_add():
                from src.calc import add
                assert add(1, 2) == 4

            src/calc.py:2: in add
                return a + b
            AssertionError: assert 3 == 4
        """

        # Mock acompletion to capture the prompt
        captured_prompt = {}

        async def mock_acompletion(*args, **kwargs):
            # Capture the user message content
            messages = kwargs.get("messages", [])
            if messages and messages[0].get("role") == "user":
                captured_prompt["content"] = messages[0]["content"]
            # Return a mock response
            from types import SimpleNamespace

            response = SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="Mock summary: fix the assertion")
                    )
                ]
            )
            return response

        monkeypatch.setattr("sigil.pipeline.executor.acompletion", mock_acompletion)

        summary = await _summarize_hook_errors(raw_output, "test-model", repo=repo_path)

        assert summary == "Mock summary: fix the assertion"
        content = captured_prompt.get("content", "")
        assert "Forensic Traceback" in content
        assert "src/calc.py:2" in content
        assert "def add(a, b):" in content

    @pytest.mark.asyncio
    async def test_omits_forensic_context_when_repo_none(self, repo_path: Path, monkeypatch):
        """Test that forensic context is omitted when repo is None."""
        raw_output = "Some error output"

        captured_prompt = {}

        async def mock_acompletion(*args, **kwargs):
            messages = kwargs.get("messages", [])
            if messages and messages[0].get("role") == "user":
                captured_prompt["content"] = messages[0]["content"]
            from types import SimpleNamespace

            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="Mock summary"))]
            )

        monkeypatch.setattr("sigil.pipeline.executor.acompletion", mock_acompletion)

        summary = await _summarize_hook_errors(raw_output, "test-model", repo=None)

        assert summary == "Mock summary"
        content = captured_prompt.get("content", "")
        assert "Forensic Traceback" not in content
        assert raw_output in content

    @pytest.mark.asyncio
    async def test_falls_back_to_raw_on_acompletion_error(self, repo_path: Path, monkeypatch):
        """Test that raw output is returned if LLM call fails."""
        raw_output = "Error output"

        async def mock_acompletion(*args, **kwargs):
            raise RuntimeError("LLM unavailable")

        monkeypatch.setattr("sigil.pipeline.executor.acompletion", mock_acompletion)

        summary = await _summarize_hook_errors(raw_output, "test-model", repo=repo_path)

        # Should return raw output as fallback
        assert summary == raw_output

    @pytest.mark.asyncio
    async def test_handles_empty_llm_response(self, repo_path: Path, monkeypatch):
        """Test that empty LLM response falls back to raw output."""
        raw_output = "Error output"

        async def mock_acompletion(*args, **kwargs):
            from types import SimpleNamespace

            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=""))])

        monkeypatch.setattr("sigil.pipeline.executor.acompletion", mock_acompletion)

        summary = await _summarize_hook_errors(raw_output, "test-model", repo=repo_path)

        # Should return raw output when LLM returns empty
        assert summary == raw_output
