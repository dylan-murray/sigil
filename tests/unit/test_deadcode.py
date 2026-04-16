from sigil.pipeline.deadcode import find_dead_code


def test_find_dead_code_happy_path(tmp_path):
    # File 1: defines used and unused functions
    f1 = tmp_path / "module1.py"
    f1.write_text("def used_func(): pass\ndef unused_func(): pass")

    # File 2: uses used_func
    f2 = tmp_path / "module2.py"
    f2.write_text("from module1 import used_func\nused_func()")

    candidates = find_dead_code(tmp_path)

    # Should find unused_func
    unused = [c for c in candidates if c.name == "unused_func"]
    assert len(unused) == 1
    assert unused[0].type == "function"

    # Should NOT find used_func
    used = [c for c in candidates if c.name == "used_func"]
    assert len(used) == 0


def test_find_dead_code_unused_import(tmp_path):
    f1 = tmp_path / "module1.py"
    f1.write_text("import os\nimport sys\nprint(os.name)")

    candidates = find_dead_code(tmp_path)

    # Should find sys as unused import
    unused_sys = [c for c in candidates if c.name == "sys" and c.type == "import"]
    assert len(unused_sys) == 1

    # Should NOT find os
    unused_os = [c for c in candidates if c.name == "os" and c.type == "import"]
    assert len(unused_os) == 0


def test_find_dead_code_entry_points(tmp_path):
    # Mock sigil/cli.py
    cli_dir = tmp_path / "sigil"
    cli_dir.mkdir()
    cli_file = cli_dir / "cli.py"
    cli_file.write_text("def main(): pass\ndef _run(): pass\ndef unused_cli(): pass")

    # Mock tests/
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    test_file = test_dir / "test_main.py"
    test_file.write_text("def test_something(): pass\ndef unused_test_helper(): pass")

    # Mock Typer command
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    app_file = app_dir / "commands.py"
    app_file.write_text(
        "import typer\napp = typer.Typer()\n\n@app.command()\ndef my_cmd(): pass\ndef unused_cmd(): pass"
    )

    candidates = find_dead_code(tmp_path)

    # Should NOT flag main, _run, test_something, my_cmd
    protected = {"main", "_run", "test_something", "my_cmd"}
    for name in protected:
        assert not any(c.name == name for c in candidates)

    # Should flag unused_cli, unused_test_helper, unused_cmd
    flagged = {c.name for c in candidates}
    assert "unused_cli" in flagged
    assert "unused_test_helper" in flagged
    assert "unused_cmd" in flagged


def test_find_dead_code_attribute_access(tmp_path):
    f1 = tmp_path / "module1.py"
    f1.write_text("def target_func(): pass")

    f2 = tmp_path / "module2.py"
    f2.write_text("import module1\nmodule1.target_func()")

    candidates = find_dead_code(tmp_path)

    # target_func should be marked as used via attribute access
    assert not any(c.name == "target_func" for c in candidates)
