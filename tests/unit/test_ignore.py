from sigil.utils.ignore import SigilIgnore


def test_sigil_ignore_basic(tmp_path):
    # Setup .sigilignore
    ignore_file = tmp_path / ".sigilignore"
    ignore_file.write_text("*.log\ntmp/\nbuild/**\n")

    si = SigilIgnore(tmp_path)

    # Happy path
    assert si.is_ignored("error.log") is True
    assert si.is_ignored("tmp/debug.txt") is True
    assert si.is_ignored("build/output/bin") is True

    # Not ignored
    assert si.is_ignored("main.py") is False
    assert si.is_ignored("src/main.py") is False


def test_sigil_ignore_missing_file(tmp_path):
    # No .sigilignore file
    si = SigilIgnore(tmp_path)
    assert si.is_ignored("any_file.txt") is False


def test_sigil_ignore_empty_file(tmp_path):
    # Empty .sigilignore file
    ignore_file = tmp_path / ".sigilignore"
    ignore_file.write_text("")

    si = SigilIgnore(tmp_path)
    assert si.is_ignored("any_file.txt") is False


def test_sigil_ignore_path_normalization(tmp_path):
    ignore_file = tmp_path / ".sigilignore"
    ignore_file.write_text("docs/*.md")

    si = SigilIgnore(tmp_path)
    assert si.is_ignored("docs/readme.md") is True
    assert si.is_ignored("docs/images/logo.png") is False
    assert si.is_ignored("readme.md") is False
