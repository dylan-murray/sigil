from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sigil.core.config import Config
from sigil.pipeline.sandbox import (
    SandboxContext,
    _validate_allowlist,
    build_network_allowlist,
    create,
    teardown,
)


@pytest.fixture
def sandbox_config() -> Config:
    return Config(sandbox="nemoclaw", model="anthropic/claude-sonnet-4-6")


@pytest.fixture
def docker_config() -> Config:
    return Config(sandbox="docker", model="openai/gpt-4o")


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    wt = tmp_path / "worktree"
    wt.mkdir()
    return wt


class TestBuildNetworkAllowlist:
    def test_anthropic_model(self):
        config = Config(model="anthropic/claude-sonnet-4-6")
        domains = build_network_allowlist(config)
        assert "api.anthropic.com" in domains
        assert "pypi.org" in domains
        assert "files.pythonhosted.org" in domains

    def test_openai_model(self):
        config = Config(model="openai/gpt-4o")
        domains = build_network_allowlist(config)
        assert "api.openai.com" in domains

    def test_gemini_model(self):
        config = Config(model="gemini/gemini-2.5-pro")
        domains = build_network_allowlist(config)
        assert "generativelanguage.googleapis.com" in domains

    def test_unknown_provider_defaults_to_openai(self):
        config = Config(model="some-random-provider/model")
        domains = build_network_allowlist(config)
        assert "api.openai.com" in domains

    def test_bare_model_name_defaults_to_openai(self):
        config = Config(model="gpt-4o")
        domains = build_network_allowlist(config)
        assert "api.openai.com" in domains

    def test_user_allowlist_included(self):
        config = Config(
            model="anthropic/claude-sonnet-4-6",
            sandbox_allowlist=("custom-api.company.com",),
        )
        domains = build_network_allowlist(config)
        assert "custom-api.company.com" in domains

    def test_user_allowlist_blocked_domains_stripped(self):
        config = Config(
            model="anthropic/claude-sonnet-4-6",
            sandbox_allowlist=("169.254.169.254", "metadata.google.internal", "safe.com"),
        )
        domains = build_network_allowlist(config)
        assert "169.254.169.254" not in domains
        assert "metadata.google.internal" not in domains
        assert "safe.com" in domains

    def test_wildcard_domains_stripped(self):
        config = Config(
            model="anthropic/claude-sonnet-4-6",
            sandbox_allowlist=("*.evil.com", "safe.com"),
        )
        domains = build_network_allowlist(config)
        assert "*.evil.com" not in domains
        assert "safe.com" in domains

    def test_no_duplicates(self):
        config = Config(
            model="openai/gpt-4o",
            sandbox_allowlist=("api.openai.com",),
        )
        domains = build_network_allowlist(config)
        assert domains.count("api.openai.com") == 1


class TestValidateAllowlist:
    def test_blocks_metadata_ips(self):
        assert _validate_allowlist(["169.254.169.254"]) == []

    def test_blocks_metadata_hostnames(self):
        assert _validate_allowlist(["metadata.google.internal"]) == []

    def test_blocks_localhost(self):
        assert _validate_allowlist(["localhost"]) == []

    def test_blocks_wildcards(self):
        assert _validate_allowlist(["*.evil.com"]) == []

    def test_allows_normal_domains(self):
        assert _validate_allowlist(["api.company.com"]) == ["api.company.com"]

    def test_strips_empty(self):
        assert _validate_allowlist(["", "  ", "valid.com"]) == ["valid.com"]


class TestCreateSandbox:
    @pytest.mark.asyncio
    async def test_nemoclaw_success(self, worktree: Path, sandbox_config: Config):
        with patch("sigil.pipeline.sandbox.arun", new_callable=AsyncMock) as mock_arun:
            mock_arun.return_value = (0, "sandbox created", "")
            ctx = await create(worktree, sandbox_config)
            assert ctx.sandbox_type == "nemoclaw"
            assert ctx.worktree_path == worktree

    @pytest.mark.asyncio
    async def test_nemoclaw_fails_falls_back_to_docker(
        self, worktree: Path, sandbox_config: Config
    ):
        with patch("sigil.pipeline.sandbox.arun", new_callable=AsyncMock) as mock_arun:
            # 1: nemoclaw onboard fails, 2: which docker (in fallback check), 3: which docker (in _setup_docker)
            mock_arun.side_effect = [
                (1, "", "onboard failed"),
                (0, "/usr/bin/docker", ""),
                (0, "/usr/bin/docker", ""),
            ]
            ctx = await create(worktree, sandbox_config)
            assert ctx.sandbox_type == "docker"

    @pytest.mark.asyncio
    async def test_nemoclaw_fails_no_docker_raises(self, worktree: Path, sandbox_config: Config):
        with patch("sigil.pipeline.sandbox.arun", new_callable=AsyncMock) as mock_arun:
            mock_arun.side_effect = [
                (1, "", "onboard failed"),
                (1, "", "docker not found"),
            ]
            with pytest.raises(RuntimeError, match="NemoClaw onboard failed"):
                await create(worktree, sandbox_config)

    @pytest.mark.asyncio
    async def test_docker_direct(self, worktree: Path, docker_config: Config):
        with patch("sigil.pipeline.sandbox.arun", new_callable=AsyncMock) as mock_arun:
            mock_arun.return_value = (0, "/usr/bin/docker", "")
            ctx = await create(worktree, docker_config)
            assert ctx.sandbox_type == "docker"

    @pytest.mark.asyncio
    async def test_docker_unavailable_raises(self, worktree: Path, docker_config: Config):
        with patch("sigil.pipeline.sandbox.arun", new_callable=AsyncMock) as mock_arun:
            mock_arun.return_value = (1, "", "not found")
            with pytest.raises(RuntimeError, match="Docker is not available"):
                await create(worktree, docker_config)

    @pytest.mark.asyncio
    async def test_unknown_sandbox_type_raises(self, worktree: Path):
        config = Config(sandbox="none")
        # sandbox="none" shouldn't call create, but if it does:
        with pytest.raises(ValueError, match="Unknown sandbox type"):
            await create(worktree, config)


class TestTeardown:
    @pytest.mark.asyncio
    async def test_nemoclaw_teardown(self, worktree: Path):
        ctx = SandboxContext(sandbox_id="test-1", sandbox_type="nemoclaw", worktree_path=worktree)
        with patch("sigil.pipeline.sandbox.arun", new_callable=AsyncMock) as mock_arun:
            mock_arun.return_value = (0, "", "")
            await teardown(ctx)
            mock_arun.assert_called_once()
            assert "remove" in mock_arun.call_args[0][0]

    @pytest.mark.asyncio
    async def test_docker_teardown(self, worktree: Path):
        ctx = SandboxContext(sandbox_id="test-1", sandbox_type="docker", worktree_path=worktree)
        with patch("sigil.pipeline.sandbox.arun", new_callable=AsyncMock) as mock_arun:
            mock_arun.return_value = (0, "", "")
            await teardown(ctx)
            mock_arun.assert_called_once()
            assert "docker" in mock_arun.call_args[0][0]

    @pytest.mark.asyncio
    async def test_teardown_failure_does_not_raise(self, worktree: Path):
        ctx = SandboxContext(sandbox_id="test-1", sandbox_type="nemoclaw", worktree_path=worktree)
        with patch("sigil.pipeline.sandbox.arun", new_callable=AsyncMock) as mock_arun:
            mock_arun.side_effect = Exception("cleanup failed")
            await teardown(ctx)  # Should not raise
