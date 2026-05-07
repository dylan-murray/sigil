from pathlib import Path

from sigil.core.config import Config
from sigil.pipeline.async_checker import scan_async_patterns


def _write_py(repo: Path, rel: str, source: str) -> Path:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(source)
    return p


def test_time_sleep_in_async(tmp_path: Path) -> None:
    _write_py(
        tmp_path,
        "mod.py",
        "import time\n\nasync def foo():\n    time.sleep(5)\n",
    )
    findings = scan_async_patterns(tmp_path, Config().effective_ignore)
    assert len(findings) >= 1
    f = findings[0]
    assert f.category == "async_anti_pattern"
    assert f.disposition == "pr"
    assert "time.sleep" in f.description.lower() or "time.sleep" in f.suggested_fix
    assert f.line is not None and f.line > 0


def test_time_sleep_in_sync_not_flagged(tmp_path: Path) -> None:
    _write_py(
        tmp_path,
        "mod.py",
        "import time\n\ndef foo():\n    time.sleep(5)\n",
    )
    findings = scan_async_patterns(tmp_path, Config().effective_ignore)
    assert len(findings) == 0


def test_sync_file_io_open_in_async(tmp_path: Path) -> None:
    _write_py(
        tmp_path,
        "mod.py",
        "async def foo():\n    f = open('data.txt')\n    content = f.read()\n",
    )
    findings = scan_async_patterns(tmp_path, Config().effective_ignore)
    assert any(f.disposition == "issue" and "open" in f.description for f in findings)


def test_sync_file_io_in_sync_not_flagged(tmp_path: Path) -> None:
    _write_py(
        tmp_path,
        "mod.py",
        "def foo():\n    f = open('data.txt')\n    content = f.read()\n",
    )
    findings = scan_async_patterns(tmp_path, Config().effective_ignore)
    assert len(findings) == 0


def test_missing_await_on_coroutine(tmp_path: Path) -> None:
    source = "async def helper():\n    return 42\n\nasync def main():\n    helper()\n"
    _write_py(tmp_path, "mod.py", source)
    findings = scan_async_patterns(tmp_path, Config().effective_ignore)
    assert any(f.disposition == "pr" and "await" in f.suggested_fix.lower() for f in findings)


def test_awaited_coroutine_not_flagged(tmp_path: Path) -> None:
    source = "async def helper():\n    return 42\n\nasync def main():\n    await helper()\n"
    _write_py(tmp_path, "mod.py", source)
    findings = scan_async_patterns(tmp_path, Config().effective_ignore)
    missing_await = [f for f in findings if "await" in f.suggested_fix.lower()]
    assert len(missing_await) == 0


def test_requests_in_async(tmp_path: Path) -> None:
    _write_py(
        tmp_path,
        "mod.py",
        "import requests\n\nasync def fetch():\n    requests.get('https://example.com')\n",
    )
    findings = scan_async_patterns(tmp_path, Config().effective_ignore)
    assert any(f.disposition == "issue" and "requests" in f.description for f in findings)


def test_requests_in_sync_not_flagged(tmp_path: Path) -> None:
    _write_py(
        tmp_path,
        "mod.py",
        "import requests\n\ndef fetch():\n    requests.get('https://example.com')\n",
    )
    findings = scan_async_patterns(tmp_path, Config().effective_ignore)
    assert len(findings) == 0


def test_sequential_await_in_loop(tmp_path: Path) -> None:
    source = "async def process():\n    for item in items:\n        await handle(item)\n"
    _write_py(tmp_path, "mod.py", source)
    findings = scan_async_patterns(tmp_path, Config().effective_ignore)
    assert any(f.disposition == "issue" and "gather" in f.suggested_fix.lower() for f in findings)


def test_sequential_await_in_while_loop(tmp_path: Path) -> None:
    source = "async def process():\n    while running:\n        await poll()\n"
    _write_py(tmp_path, "mod.py", source)
    findings = scan_async_patterns(tmp_path, Config().effective_ignore)
    assert any(f.disposition == "issue" and "gather" in f.suggested_fix.lower() for f in findings)


def test_clean_async_code_no_findings(tmp_path: Path) -> None:
    source = (
        "import asyncio\n\n"
        "async def fetch():\n"
        "    await asyncio.sleep(1)\n"
        "    data = await read_async()\n"
        "    return data\n"
    )
    _write_py(tmp_path, "mod.py", source)
    findings = scan_async_patterns(tmp_path, Config().effective_ignore)
    assert len(findings) == 0


def test_non_python_files_skipped(tmp_path: Path) -> None:
    p = tmp_path / "data.json"
    p.write_text('{"key": "value"}')
    findings = scan_async_patterns(tmp_path, Config().effective_ignore)
    assert len(findings) == 0


def test_ignored_paths_skipped(tmp_path: Path) -> None:
    _write_py(
        tmp_path,
        ".venv/lib/mod.py",
        "import time\n\nasync def foo():\n    time.sleep(5)\n",
    )
    findings = scan_async_patterns(tmp_path, Config().effective_ignore)
    assert len(findings) == 0


def test_syntax_error_file_skipped(tmp_path: Path) -> None:
    _write_py(tmp_path, "broken.py", "def foo(:\n    pass\n")
    findings = scan_async_patterns(tmp_path, Config().effective_ignore)
    assert len(findings) == 0


def test_multiple_patterns_in_one_file(tmp_path: Path) -> None:
    source = (
        "import time\n"
        "import requests\n\n"
        "async def foo():\n"
        "    time.sleep(1)\n"
        "    requests.get('https://example.com')\n"
    )
    _write_py(tmp_path, "mod.py", source)
    findings = scan_async_patterns(tmp_path, Config().effective_ignore)
    assert len(findings) >= 2


def test_on_status_callback(tmp_path: Path) -> None:
    _write_py(
        tmp_path,
        "mod.py",
        "import time\n\nasync def foo():\n    time.sleep(5)\n",
    )
    messages: list[str] = []
    scan_async_patterns(tmp_path, Config().effective_ignore, on_status=messages.append)
    assert any("Scanning" in m for m in messages)


def test_sigil_dir_ignored(tmp_path: Path) -> None:
    _write_py(
        tmp_path,
        ".sigil/memory/mod.py",
        "import time\n\nasync def foo():\n    time.sleep(5)\n",
    )
    findings = scan_async_patterns(tmp_path, Config().effective_ignore)
    assert len(findings) == 0


def test_nested_async_function(tmp_path: Path) -> None:
    source = "import time\n\nasync def outer():\n    async def inner():\n        time.sleep(1)\n"
    _write_py(tmp_path, "mod.py", source)
    findings = scan_async_patterns(tmp_path, Config().effective_ignore)
    assert len(findings) >= 1


def test_requests_various_methods(tmp_path: Path) -> None:
    for method in ["get", "post", "put", "delete", "patch"]:
        source = (
            f"import requests\n\nasync def foo():\n    requests.{method}('https://example.com')\n"
        )
        _write_py(tmp_path, f"mod_{method}.py", source)
    findings = scan_async_patterns(tmp_path, Config().effective_ignore)
    assert len(findings) >= 5


def test_file_read_write_in_async(tmp_path: Path) -> None:
    source = (
        "async def foo():\n"
        "    f = open('data.txt')\n"
        "    data = f.read()\n"
        "    f.close()\n"
        "    f2 = open('out.txt', 'w')\n"
        "    f2.write(data)\n"
    )
    _write_py(tmp_path, "mod.py", source)
    findings = scan_async_patterns(tmp_path, Config().effective_ignore)
    io_findings = [
        f
        for f in findings
        if "open" in f.description or "read" in f.description or "write" in f.description
    ]
    assert len(io_findings) >= 1
