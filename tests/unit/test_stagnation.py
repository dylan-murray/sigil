import logging
from datetime import datetime

import pytest
from unittest.mock import MagicMock, patch

from sigil.core.config import Config
from sigil.pipeline.models import Finding
from sigil.pipeline.stagnation import detect_stagnation, write_stagnation_report

logger = logging.getLogger(__name__)


@pytest.fixture
def mock_config():
    return Config()


@pytest.fixture
def repo_path(tmp_path):
    return tmp_path


@pytest.mark.asyncio
async def test_detect_stagnation_happy_path(repo_path, mock_config):
    # Mock git log to return an old file
    # Format: %ai (date) then name-only
    # We simulate a file modified 2 years ago
    two_years_ago = "2022-01-01 00:00:00 +0000"
    mock_stdout = f"{two_years_ago}\nold_file.py\n"

    with patch("sigil.pipeline.stagnation.arun") as mock_arun:
        mock_arun.return_value = (0, mock_stdout, "")

        # Mock radon to return high complexity
        with patch("radon.complexity.cc_visit") as mock_cc:
            # cc_visit returns a list of objects with .complexity attribute
            mock_block = MagicMock()
            mock_block.complexity = 50
            mock_cc.return_value = [mock_block]

            # Create the file so radon can read it
            (repo_path / "old_file.py").write_text("def foo(): pass")

            findings = await detect_stagnation(repo_path, mock_config)

            assert len(findings) == 1
            assert findings[0].category == "stagnation"
            assert "old_file.py" in findings[0].file
            assert "50.0" in findings[0].description
            assert findings[0].disposition == "issue"


@pytest.mark.asyncio
async def test_detect_stagnation_recent_file(repo_path, mock_config):
    # Mock git log to return a recent file
    today = datetime.now().strftime("%Y-%m-%d %H:%M:%S %z")
    mock_stdout = f"{today}\nrecent_file.py\n"

    with patch("sigil.pipeline.stagnation.arun") as mock_arun:
        mock_arun.return_value = (0, mock_stdout, "")

        (repo_path / "recent_file.py").write_text("def foo(): pass")

        findings = await detect_stagnation(repo_path, mock_config)
        assert len(findings) == 0


@pytest.mark.asyncio
async def test_detect_stagnation_low_complexity(repo_path, mock_config):
    two_years_ago = "2022-01-01 00:00:00 +0000"
    mock_stdout = f"{two_years_ago}\nold_simple_file.py\n"

    with patch("sigil.pipeline.stagnation.arun") as mock_arun:
        mock_arun.return_value = (0, mock_stdout, "")

        with patch("radon.complexity.cc_visit") as mock_cc:
            mock_block = MagicMock()
            mock_block.complexity = 2
            mock_cc.return_value = [mock_block]

            (repo_path / "old_simple_file.py").write_text("def foo(): pass")

            findings = await detect_stagnation(repo_path, mock_config)
            assert len(findings) == 0


@pytest.mark.asyncio
async def test_detect_stagnation_git_failure(repo_path, mock_config):
    with patch("sigil.pipeline.stagnation.arun") as mock_arun:
        mock_arun.return_value = (1, "", "git error")

        findings = await detect_stagnation(repo_path, mock_config)
        assert len(findings) == 0


@pytest.mark.asyncio
async def test_detect_stagnation_radon_error(repo_path, mock_config):
    two_years_ago = "2022-01-01 00:00:00 +0000"
    mock_stdout = f"{two_years_ago}\nbad_file.py\n"

    with patch("sigil.pipeline.stagnation.arun") as mock_arun:
        mock_arun.return_value = (0, mock_stdout, "")

        # Simulate syntax error in radon
        with patch(
            "radon.complexity.cc_visit",
            side_effect=Exception("Parse error"),
        ):
            (repo_path / "bad_file.py").write_text("invalid python code")

            findings = await detect_stagnation(repo_path, mock_config)
            assert len(findings) == 0


def test_write_stagnation_report(repo_path):
    findings = [
        Finding(
            category="stagnation",
            file="old_file.py",
            line=None,
            description="Stale and complex",
            risk="medium",
            suggested_fix="Refactor",
            disposition="issue",
            priority=1,
            rationale="Too old",
        )
    ]

    # Create .sigil/memory directory
    memory_dir = repo_path / ".sigil" / "memory"
    memory_dir.mkdir(parents=True)

    write_stagnation_report(repo_path, findings)

    report_file = memory_dir / "stagnation_report.md"
    assert report_file.exists()
    content = report_file.read_text()
    assert "Stagnation Report" in content
    assert "old_file.py" in content
