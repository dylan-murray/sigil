import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from sigil.core.config import SIGIL_DIR, CONFIG_FILE, Config
from sigil.core.utils import arun


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    message: str
    details: str | None = None


def check_config(repo: Path) -> CheckResult:
    config_path = repo / SIGIL_DIR / CONFIG_FILE
    try:
        Config.load(repo)
    except ValueError as e:
        return CheckResult(
            name="Config",
            status="fail",
            message="Config validation failed",
            details=str(e),
        )
    if not config_path.exists():
        return CheckResult(
            name="Config",
            status="pass",
            message="Config valid (using defaults — no config file found)",
        )
    return CheckResult(
        name="Config",
        status="pass",
        message="Config valid",
    )


def check_api_key() -> CheckResult:
    key_vars = [
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "AZURE_API_KEY",
        "DEEPSEEK_API_KEY",
    ]
    found = [k for k in key_vars if _env_is_set(k)]
    if found:
        return CheckResult(
            name="LLM API Key",
            status="pass",
            message=f"Found {', '.join(found)}",
        )
    return CheckResult(
        name="LLM API Key",
        status="fail",
        message="No LLM API key found",
        details="Set one of: " + ", ".join(key_vars),
    )


def _env_is_set(key: str) -> bool:
    import os

    val = os.environ.get(key)
    return val is not None and val != ""


async def check_git() -> CheckResult:
    rc, stdout, _ = await arun(["git", "--version"], timeout=10)
    if rc == 0:
        version = stdout.strip()
        return CheckResult(
            name="Git",
            status="pass",
            message=version,
        )
    return CheckResult(
        name="Git",
        status="fail",
        message="git binary not found",
    )


async def check_git_remote(repo: Path) -> CheckResult:
    rc, stdout, _ = await arun(["git", "remote", "get-url", "origin"], cwd=repo, timeout=10)
    if rc == 0 and stdout.strip():
        url = stdout.strip()
        return CheckResult(
            name="Git Remote",
            status="pass",
            message=f"origin → {url}",
        )
    return CheckResult(
        name="Git Remote",
        status="warn",
        message="No 'origin' remote configured (local-only repo)",
    )


def check_github_token() -> CheckResult:
    if _env_is_set("GITHUB_TOKEN"):
        return CheckResult(
            name="GitHub Token",
            status="pass",
            message="GITHUB_TOKEN is set",
        )
    return CheckResult(
        name="GitHub Token",
        status="warn",
        message="GITHUB_TOKEN not set (required for PRs/issues; dry-run works without it)",
    )


async def check_mcp_servers(config: Config) -> CheckResult:
    if not config.mcp_servers:
        return CheckResult(
            name="MCP Servers",
            status="pass",
            message="No MCP servers configured",
        )
    from sigil.core.mcp import connect_mcp_servers

    try:
        async with connect_mcp_servers(config) as mgr:
            connected = mgr.server_count
            total = len(config.mcp_servers)
            if connected == total:
                return CheckResult(
                    name="MCP Servers",
                    status="pass",
                    message=f"All {total} server(s) connected ({mgr.tool_count} tool(s))",
                )
            return CheckResult(
                name="MCP Servers",
                status="warn",
                message=f"{connected}/{total} server(s) connected",
            )
    except Exception as e:
        return CheckResult(
            name="MCP Servers",
            status="warn",
            message="MCP connection failed",
            details=str(e),
        )


def check_disk_space(repo: Path) -> CheckResult:
    try:
        usage = shutil.disk_usage(repo)
    except OSError as e:
        return CheckResult(
            name="Disk Space",
            status="warn",
            message="Could not check disk space",
            details=str(e),
        )
    free_gb = usage.free / (1024**3)
    if usage.free < 1 * 1024**3:
        return CheckResult(
            name="Disk Space",
            status="warn",
            message=f"Low disk space: {free_gb:.1f} GB free",
        )
    return CheckResult(
        name="Disk Space",
        status="pass",
        message=f"{free_gb:.1f} GB free",
    )


def check_python_version() -> CheckResult:
    vi = sys.version_info
    version_str = f"{vi.major}.{vi.minor}.{vi.micro}"
    if (vi.major, vi.minor) >= (3, 11):
        return CheckResult(
            name="Python Version",
            status="pass",
            message=version_str,
        )
    return CheckResult(
        name="Python Version",
        status="fail",
        message=f"Python {version_str} is below minimum 3.11",
    )


async def run_all_checks(repo: Path, config: Config | None = None) -> list[CheckResult]:
    results: list[CheckResult] = []

    results.append(check_config(repo))
    results.append(check_api_key())
    results.append(await check_git())
    results.append(await check_git_remote(repo))
    results.append(check_github_token())

    if config is not None:
        results.append(await check_mcp_servers(config))
    else:
        results.append(
            CheckResult(
                name="MCP Servers",
                status="warn",
                message="Skipped (config not available)",
            )
        )

    results.append(check_disk_space(repo))
    results.append(check_python_version())

    return results
