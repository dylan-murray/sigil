import textwrap

from sigil.pipeline.ast_scan import ast_type_safety_scan


def test_missing_return_type_on_public_function(tmp_path):
    code = textwrap.dedent("""\
        def greet(name: str):
            return f"Hello {name}"
    """)
    (tmp_path / "mod.py").write_text(code)

    findings = ast_type_safety_scan(tmp_path, [])
    assert len(findings) == 1
    f = findings[0]
    assert f.category == "types"
    assert f.file == "mod.py"
    assert f.line == 1
    assert f.risk == "low"
    assert f.disposition == "pr"
    assert "return type" in f.description.lower()


def test_private_function_missing_return_type_skipped(tmp_path):
    code = textwrap.dedent("""\
        def _helper(x: int) -> int:
            return x
    """)
    (tmp_path / "mod.py").write_text(code)

    findings = ast_type_safety_scan(tmp_path, [])
    assert len(findings) == 0


def test_fully_annotated_function_no_findings(tmp_path):
    code = textwrap.dedent("""\
        def greet(name: str) -> str:
            return f"Hello {name}"
    """)
    (tmp_path / "mod.py").write_text(code)

    findings = ast_type_safety_scan(tmp_path, [])
    assert len(findings) == 0


def test_untyped_argument(tmp_path):
    code = textwrap.dedent("""\
        def greet(name) -> str:
            return f"Hello {name}"
    """)
    (tmp_path / "mod.py").write_text(code)

    findings = ast_type_safety_scan(tmp_path, [])
    untyped = [f for f in findings if "argument" in f.description.lower()]
    assert len(untyped) == 1
    assert untyped[0].category == "types"
    assert untyped[0].line == 1
    assert untyped[0].risk == "low"


def test_any_in_signature(tmp_path):
    code = textwrap.dedent("""\
        from typing import Any

        def process(data: Any) -> str:
            return str(data)
    """)
    (tmp_path / "mod.py").write_text(code)

    findings = ast_type_safety_scan(tmp_path, [])
    any_findings = [f for f in findings if "any" in f.description.lower()]
    assert len(any_findings) >= 1
    assert any(f.risk == "medium" for f in any_findings)


def test_any_nested_in_generic(tmp_path):
    code = textwrap.dedent("""\
        from typing import Any

        def process(items: list[Any]) -> dict[str, Any]:
            return {}
    """)
    (tmp_path / "mod.py").write_text(code)

    findings = ast_type_safety_scan(tmp_path, [])
    any_findings = [f for f in findings if "any" in f.description.lower()]
    assert len(any_findings) >= 1


def test_bare_except(tmp_path):
    code = textwrap.dedent("""\
        try:
            x = 1
        except:
            pass
    """)
    (tmp_path / "mod.py").write_text(code)

    findings = ast_type_safety_scan(tmp_path, [])
    assert len(findings) == 1
    f = findings[0]
    assert f.category == "security"
    assert f.line == 3
    assert f.risk == "high"
    assert "bare except" in f.description.lower()


def test_specific_except_no_finding(tmp_path):
    code = textwrap.dedent("""\
        try:
            x = 1
        except ValueError:
            pass
    """)
    (tmp_path / "mod.py").write_text(code)

    findings = ast_type_safety_scan(tmp_path, [])
    bare = [
        f for f in findings if f.category == "security" and "bare except" in f.description.lower()
    ]
    assert len(bare) == 0


def test_syntax_error_file_skipped(tmp_path):
    code = "def broken(:\n    pass\n"
    (tmp_path / "bad.py").write_text(code)

    findings = ast_type_safety_scan(tmp_path, [])
    assert len(findings) == 0


def test_ignore_patterns_respected(tmp_path):
    code = textwrap.dedent("""\
        def greet(name):
            return f"Hello {name}"
    """)
    (tmp_path / "mod.py").write_text(code)

    findings = ast_type_safety_scan(tmp_path, ["mod.py"])
    assert len(findings) == 0


def test_multiple_issues_in_one_file(tmp_path):
    code = textwrap.dedent("""\
        from typing import Any

        def process(data: Any):
            try:
                result = data
            except:
                pass
            return result
    """)
    (tmp_path / "mod.py").write_text(code)

    findings = ast_type_safety_scan(tmp_path, [])
    categories = {f.category for f in findings}
    assert "types" in categories
    assert "security" in categories
    assert len(findings) >= 3


def test_async_function_missing_return_type(tmp_path):
    code = textwrap.dedent("""\
        async def fetch(url: str):
            return None
    """)
    (tmp_path / "mod.py").write_text(code)

    findings = ast_type_safety_scan(tmp_path, [])
    assert len(findings) == 1
    assert findings[0].category == "types"
    assert "return type" in findings[0].description.lower()


def test_kwonly_untyped_argument(tmp_path):
    code = textwrap.dedent("""\
        def greet(*, name) -> str:
            return f"Hello {name}"
    """)
    (tmp_path / "mod.py").write_text(code)

    findings = ast_type_safety_scan(tmp_path, [])
    untyped = [f for f in findings if "argument" in f.description.lower()]
    assert len(untyped) == 1


def test_attribute_any_in_annotation(tmp_path):
    code = textwrap.dedent("""\
        import typing

        def process(data: typing.Any) -> str:
            return str(data)
    """)
    (tmp_path / "mod.py").write_text(code)

    findings = ast_type_safety_scan(tmp_path, [])
    any_findings = [f for f in findings if "any" in f.description.lower()]
    assert len(any_findings) >= 1


def test_init_method_not_flagged(tmp_path):
    code = textwrap.dedent("""\
        class Foo:
            def __init__(self, x):
                self.x = x
    """)
    (tmp_path / "mod.py").write_text(code)

    findings = ast_type_safety_scan(tmp_path, [])
    return_findings = [f for f in findings if "return type" in f.description.lower()]
    assert len(return_findings) == 0
    self_findings = [f for f in findings if "self" in f.description.lower()]
    assert len(self_findings) == 0


def test_subdirectory_files_scanned(tmp_path):
    sub = tmp_path / "pkg"
    sub.mkdir()
    code = textwrap.dedent("""\
        def greet(name: str):
            return f"Hello {name}"
    """)
    (sub / "mod.py").write_text(code)

    findings = ast_type_safety_scan(tmp_path, [])
    assert len(findings) == 1
    assert findings[0].file == "pkg/mod.py"
    assert "return type" in findings[0].description.lower()


def test_encoding_error_file_skipped(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_bytes(b"\x80\x81\x82")

    findings = ast_type_safety_scan(tmp_path, [])
    assert len(findings) == 0
