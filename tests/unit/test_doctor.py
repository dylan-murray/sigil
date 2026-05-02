import os
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sigil.core.config import SIGIL_DIR, CONFIG_FILE, Config
from sigil.core.doctor import (
    CheckResult,
    check_api_key,
    check_config,
    check_disk_space,
    check_git,
    check_git_remote,
    check_github_token,
    check_mcp_servers,
    check_python_version,
    run_all_checks,
)


class TestCheckResult:
    def test_frozen(self) -> None:
        r = CheckResult(name="test", status="pass", message="ok")
        with pytest.raises(AttributeError):
            r.name = "changed"

    def test_defaults(self) -> None:
        r = CheckResult(name="test", status="pass", message="ok")
        assert r.details is None


class TestCheckConfig:
    def test_missing_file(self, tmp_path: Path) -> None:
        result = check_config(tmp_path)
        assert result.status == "pass"
        assert "defaults" in result.message.lower()

    def test_valid_file(self, tmp_path: Path) -> None:
        sigil_dir = tmp_path / SIGIL_DIR
        sigil_dir.mkdir(parents=True)
        (sigil_dir / CONFIG_FILE).write_text(Config().to_yaml())
        result = check_config(tmp_path)
        assert result.status == "pass"
        assert "defaults" not in result.message.lower()

    def test_invalid_yaml(self, tmp_path: Path) -> None:
        sigil_dir = tmp_path / SIGIL_DIR
        sigil_dir.mkdir(parents=True)
        (sigil_dir / CONFIG_FILE).write_text(":\n  - :\n    bad: [unmatched")
        result = check_config(tmp_path)
        assert result.status == "fail"
        assert "Invalid YAML" in result.details

    def test_invalid_boldness(self, tmp_path: Path) -> None:
        sigil_dir = tmp_path / SIGIL_DIR
        sigil_dir.mkdir(parents=True)
        (sigil_dir / CONFIG_FILE).write_text("boldness: yolo\n")
        result = check_config(tmp_path)
        assert result.status == "fail"
        assert "boldness" in result.details.lower()


class TestCheckApiKey:
    def test_with_anthropic_key(self) -> None:
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}, clear=False):
            result = check_api_key()
        assert result.status == "pass"

    def test_with_openai_key(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False):
            result = check_api_key()
        assert result.status == "pass"

    def test_no_keys(self) -> None:
        env_vars_to_clear = {
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "AZURE_API_KEY",
            "DEEPSEEK_API_KEY",
        }
        with patch.dict(os.environ, {}, clear=False):
            for key in env_vars_to_clear:
                os.environ.pop(key, None)
            result = check_api_key()
        assert result.status == "fail"


class TestCheckGit:
    @pytest.mark.asyncio
    async def test_git_available(self) -> None:
        with patch(
            "sigil.core.doctor.arun",
            new_callable=AsyncMock,
            return_value=(0, "git version 2.40", ""),
        ):
            result = await check_git()
        assert result.status == "pass"

    @pytest.mark.asyncio
    async def test_git_missing(self) -> None:
        with patch(
            "sigil.core.doctor.arun", new_callable=AsyncMock, return_value=(1, "", "not found")
        ):
            result = await check_git()
        assert result.status == "fail"


class TestCheckGitRemote:
    @pytest.mark.asyncio
    async def test_remote_present(self, tmp_path: Path) -> None:
        with patch(
            "sigil.core.doctor.arun",
            new_callable=AsyncMock,
            return_value=(0, "https://github.com/user/repo.git\n", ""),
        ):
            result = await check_git_remote(tmp_path)
        assert result.status == "pass"

    @pytest.mark.asyncio
    async def test_no_remote(self, tmp_path: Path) -> None:
        with patch(
            "sigil.core.doctor.arun",
            new_callable=AsyncMock,
            return_value=(128, "", "fatal: no such remote"),
        ):
            result = await check_git_remote(tmp_path)
        assert result.status == "warn"


class TestCheckGithubToken:
    def test_token_set(self) -> None:
        with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"}, clear=False):
            result = check_github_token()
        assert result.status == "pass"

    def test_token_missing(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GITHUB_TOKEN", None)
            result = check_github_token()
        assert result.status == "warn"


class TestCheckDiskSpace:
    def test_sufficient_space(self, tmp_path: Path) -> None:
        mock_usage = MagicMock(free=5 * 1024**3, total=100 * 1024**3, used=95 * 1024**3)
        with patch("sigil.core.doctor.shutil.disk_usage", return_value=mock_usage):
            result = check_disk_space(tmp_path)
        assert result.status == "pass"

    def test_low_space(self, tmp_path: Path) -> None:
        mock_usage = MagicMock(free=500 * 1024**2, total=100 * 1024**3, used=99 * 1024**3)
        with patch("sigil.core.doctor.shutil.disk_usage", return_value=mock_usage):
            result = check_disk_space(tmp_path)
        assert result.status == "warn"


class TestCheckPythonVersion:
    def test_python_311(self) -> None:
        with patch("sigil.core.doctor.sys") as mock_sys:
            mock_sys.version_info = SimpleNamespace(major=3, minor=11, micro=0)
            result = check_python_version()
        assert result.status == "pass"

    def test_python_310(self) -> None:
        with patch("sigil.core.doctor.sys") as mock_sys:
            mock_sys.version_info = SimpleNamespace(major=3, minor=10, micro=0)
            result = check_python_version()
        assert result.status == "fail"

    def test_python_312(self) -> None:
        with patch("sigil.core.doctor.sys") as mock_sys:
            mock_sys.version_info = SimpleNamespace(major=3, minor=12, micro=1)
            result = check_python_version()
        assert result.status == "pass"


class TestCheckMcpServers:
    @pytest.mark.asyncio
    async def test_no_servers(self) -> None:
        config = Config()
        result = await check_mcp_servers(config)
        assert result.status == "pass"

    @pytest.mark.asyncio
    async def test_servers_connect(self) -> None:
        config = Config(mcp_servers=[{"name": "test", "command": "echo"}])
        mock_mgr = MagicMock()
        mock_mgr.server_count = 1
        mock_mgr.tool_count = 2

        @asynccontextmanager
        async def _mock_connect(cfg):
            yield mock_mgr

        with patch("sigil.core.mcp.connect_mcp_servers", _mock_connect):
            result = await check_mcp_servers(config)
        assert result.status == "pass"

    @pytest.mark.asyncio
    async def test_servers_fail(self) -> None:
        config = Config(mcp_servers=[{"name": "test", "command": "echo"}])

        @asynccontextmanager
        async def _mock_connect_fail(cfg):
            raise OSError("connection failed")
            yield  # pragma: no cover

        with patch("sigil.core.mcp.connect_mcp_servers", _mock_connect_fail):
            result = await check_mcp_servers(config)
        assert result.status == "warn"


class TestRunAllChecks:
    @pytest.mark.asyncio
    async def test_all_pass(self, tmp_path: Path) -> None:
        config = Config()
        with (
            patch(
                "sigil.core.doctor.check_config",
                return_value=CheckResult(name="Config", status="pass", message="ok"),
            ),
            patch(
                "sigil.core.doctor.check_api_key",
                return_value=CheckResult(name="API Key", status="pass", message="ok"),
            ),
            patch(
                "sigil.core.doctor.check_git",
                new_callable=AsyncMock,
                return_value=CheckResult(name="Git", status="pass", message="ok"),
            ),
            patch(
                "sigil.core.doctor.check_git_remote",
                new_callable=AsyncMock,
                return_value=CheckResult(name="Git Remote", status="pass", message="ok"),
            ),
            patch(
                "sigil.core.doctor.check_github_token",
                return_value=CheckResult(name="GitHub Token", status="pass", message="ok"),
            ),
            patch(
                "sigil.core.doctor.check_mcp_servers",
                new_callable=AsyncMock,
                return_value=CheckResult(name="MCP Servers", status="pass", message="ok"),
            ),
            patch(
                "sigil.core.doctor.check_disk_space",
                return_value=CheckResult(name="Disk Space", status="pass", message="ok"),
            ),
            patch(
                "sigil.core.doctor.check_python_version",
                return_value=CheckResult(name="Python", status="pass", message="ok"),
            ),
        ):
            results = await run_all_checks(tmp_path, config)
        assert all(r.status == "pass" for r in results)
        assert len(results) == 8

    @pytest.mark.asyncio
    async def test_config_none_skips_mcp(self, tmp_path: Path) -> None:
        with (
            patch(
                "sigil.core.doctor.check_config",
                return_value=CheckResult(name="Config", status="fail", message="bad"),
            ),
            patch(
                "sigil.core.doctor.check_api_key",
                return_value=CheckResult(name="API Key", status="pass", message="ok"),
            ),
            patch(
                "sigil.core.doctor.check_git",
                new_callable=AsyncMock,
                return_value=CheckResult(name="Git", status="pass", message="ok"),
            ),
            patch(
                "sigil.core.doctor.check_git_remote",
                new_callable=AsyncMock,
                return_value=CheckResult(name="Git Remote", status="pass", message="ok"),
            ),
            patch(
                "sigil.core.doctor.check_github_token",
                return_value=CheckResult(name="GitHub Token", status="pass", message="ok"),
            ),
            patch(
                "sigil.core.doctor.check_disk_space",
                return_value=CheckResult(name="Disk Space", status="pass", message="ok"),
            ),
            patch(
                "sigil.core.doctor.check_python_version",
                return_value=CheckResult(name="Python", status="pass", message="ok"),
            ),
        ):
            results = await run_all_checks(tmp_path, None)
        assert len(results) == 8
        assert results[0].status == "fail"
        mcp_result = [r for r in results if r.name == "MCP Servers"][0]
        assert mcp_result.status == "warn"
        assert "Skipped" in mcp_result.message
