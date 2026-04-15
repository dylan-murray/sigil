"""Unit tests for behavioral contract checking."""

from pathlib import Path
from unittest.mock import patch

from sigil.pipeline.behavioral_contract import check_behavioral_contract
from sigil.pipeline.models import FileTracker


def test_behavioral_contract_no_changes(tmp_path: Path):
    """Test that contract check passes when no function bodies change."""
    # Set up a temporary git repo
    repo = tmp_path
    (repo / "test.py").write_text(
        "def foo():\n    return 1\n\nclass Bar:\n    def method(self):\n        pass\n"
    )
    # Initialize git repo
    (repo / ".git").mkdir()
    (repo / ".git" / "config").write_text("[core]\n")
    # Commit the initial file
    def subprocess_run(*args, **kwargs):
        return None
    with patch("sigil.pipeline.behavioral_contract.subprocess.run", side_effect=subprocess_run):
        # Track the file as modified (but content unchanged)
        tracker = FileTracker(
            modified_files=[Path("test.py")],
            added_files=[],
            deleted_files=[],
        )
        success, msg = check_behavioral_contract(repo, tracker)
        assert success is True
        assert msg == ""


def test_behavioral_contract_function_changed(tmp_path: Path):
    """Test that contract check fails when function body changes."""
    repo = tmp_path
    # Original content
    (repo / "test.py").write_text("def foo():\n    return 1\n")
    (repo / ".git").mkdir()
    (repo / ".git" / "config").write_text("[core]\n")
    # Commit the original
    with patch("sigil.pipeline.behavioral_contract.subprocess.run") as mock_run:
        # Mock git show to return original content
        mock_run.return_value.stdout = "def foo():\n    return 1\n"
        # Now change the file in working tree
        (repo / "test.py").write_text("def foo():\n    return 2\n")
        tracker = FileTracker(
            modified_files=[Path("test.py")],
            added_files=[],
            deleted_files=[],
        )
        success, msg = check_behavioral_contract(repo, tracker)
        assert success is False
        assert "Behavioral contract changed for 'foo'" in msg


def test_behavioral_contract_function_removed(tmp_path: Path):
    """Test that contract check fails when function is removed."""
    repo = tmp_path
    (repo / "test.py").write_text("def foo():\n    pass\n")
    (repo / ".git").mkdir()
    (repo / ".git" / "config").write_text("[core]\n")
    with patch("sigil.pipeline.behavioral_contract.subprocess.run") as mock_run:
        mock_run.return_value.stdout = "def foo():\n    pass\n"
        # Remove the function
        (repo / "test.py").write_text("# empty\n")
        tracker = FileTracker(
            modified_files=[Path("test.py")],
            added_files=[],
            deleted_files=[],
        )
        success, msg = check_behavioral_contract(repo, tracker)
        assert success is False
        assert "Function/class 'foo' removed" in msg


def test_behavioral_contract_new_file(tmp_path: Path):
    """Test that new files (no HEAD version) are skipped."""
    repo = tmp_path
    (repo / "new.py").write_text("def bar():\n    pass\n")
    (repo / ".git").mkdir()
    (repo / ".git" / "config").write_text("[core]\n")
    # Mock git show to fail (file not in HEAD)
    with patch("sigil.pipeline.behavioral_contract.subprocess.run") as mock_run:
        mock_run.side_effect = Exception("not found")
        tracker = FileTracker()
        tracker.modified = {str(Path("new.py"))}
        success, msg = check_behavioral_contract(repo, tracker)
        assert success is True  # No contract to violate
        assert msg == ""


def test_behavioral_contract_syntax_error_skipped(tmp_path: Path):
    """Test that files with syntax errors are skipped."""
    repo = tmp_path
    (repo / "bad.py").write_text("def foo(:")  # invalid syntax
    (repo / ".git").mkdir()
    (repo / ".git" / "config").write_text("[core]\n")
    with patch("sigil.pipeline.behavioral_contract.subprocess.run") as mock_run:
        mock_run.return_value.stdout = "def foo():\n    pass\n"  # original valid
        tracker = FileTracker()
        tracker.modified = {str(Path("bad.py"))}
        success, msg = check_behavioral_contract(repo, tracker)
        # Should skip due to syntax error in new version -> no violation
        assert success is True
        assert msg == ""
