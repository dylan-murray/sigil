import asyncio
import os
import re
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

StatusCallback = Callable[[str], None]

_SENSITIVE_ENV_PATTERN = re.compile(
    r"(KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL|AUTH|PRIVATE|SIGNING)"
    r"|^(AWS_|GH_|GITHUB_|OPENAI_|ANTHROPIC_|AZURE_|GCP_|GOOGLE_)"
    r"|^(DATABASE_URL|REDIS_URL|MONGO_URI|DSN|CONNECTION_STRING)$"
    r"|^(NPM_TOKEN|PYPI_TOKEN|NUGET_API_KEY|DOCKER_PASSWORD)$"
    r"|^(SLACK_|SENDGRID_|TWILIO_|STRIPE_|SENTRY_DSN)",
    re.IGNORECASE,
)

_ENV_ALLOWLIST: set[str] = {
    "PATH",
    "HOME",
    "USER",
    "SHELL",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TERM",
    "EDITOR",
    "VISUAL",
    "TMPDIR",
    "TZ",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_CACHE_HOME",
    "XDG_RUNTIME_DIR",
    "VIRTUAL_ENV",
    "CONDA_DEFAULT_ENV",
    "PYTHONPATH",
    "PYTHONDONTWRITEBYTECODE",
    "NODE_ENV",
    "GOPATH",
    "GOROOT",
    "CARGO_HOME",
    "RUSTUP_HOME",
    "JAVA_HOME",
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL",
    "GIT_EXEC_PATH",
    "GIT_TEMPLATE_DIR",
    "COLUMNS",
    "LINES",
    "PWD",
    "OLDPWD",
    "SHLVL",
    "LOGNAME",
    "HOSTNAME",
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "SSH_AUTH_SOCK",
    "GPG_AGENT_INFO",
    "COLORTERM",
    "TERM_PROGRAM",
    "CLICOLOR",
    "FORCE_COLOR",
    "NO_COLOR",
}


def _sanitized_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for k, v in os.environ.items():
        if k in _ENV_ALLOWLIST:
            env[k] = v
        elif not _SENSITIVE_ENV_PATTERN.search(k):
            env[k] = v
    return env


async def arun(
    cmd: str | list[str],
    *,
    cwd: Path | None = None,
    timeout: float = 30,
) -> tuple[int, str, str]:
    safe_env = _sanitized_env()
    proc = None
    try:
        if isinstance(cmd, str):
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=safe_env,
            )
        else:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=safe_env,
            )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode or 0, stdout.decode(), stderr.decode()
    except asyncio.TimeoutError:
        if proc:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.communicate()
        return 1, "", f"Command timed out after {timeout} seconds."
    except FileNotFoundError:
        cmd_name = cmd if isinstance(cmd, str) else cmd[0]
        return 1, "", f"Command not found: {cmd_name}"


async def get_head(repo: Path) -> str:
    rc, stdout, _ = await arun(["git", "rev-parse", "HEAD"], cwd=repo, timeout=5)
    if rc == 0:
        return stdout.strip()
    return ""


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_file(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text()
    except OSError:
        return ""


def read_truncated(path: Path, max_chars: int = 8000) -> str:
    if not path.is_file():
        return ""
    try:
        with path.open(errors="replace") as f:
            text = f.read(max_chars + 1)
    except OSError:
        return ""
    if len(text) > max_chars:
        return text[:max_chars] + "\n... (truncated)"
    return text


def fix_double_escaped(text: str) -> str:
    if "\\n" in text and "\n" not in text:
        text = text.replace("\\n", "\n").replace("\\t", "\t")
    return text


def numbered_window(lines: list[str], center: int, radius: int = 10) -> str:
    start = max(0, center - radius)
    end = min(len(lines), center + radius + 1)
    return "\n".join(f"{i + 1:>4} | {lines[i]}" for i in range(start, end))


def find_best_match_region(content: str, old_content: str) -> str:
    lines = content.splitlines()
    old_lines = [ln.strip() for ln in old_content.strip().splitlines() if ln.strip()]
    if not old_lines:
        return numbered_window(lines, len(lines) // 2, 20)
    for candidate in old_lines[:10]:
        if len(candidate) < 8:
            continue
        for i, line in enumerate(lines):
            if candidate in line:
                return (
                    f"Found similar content near line {i + 1} "
                    f"(matching: {candidate[:60]!r}):\n\n" + numbered_window(lines, i, 15)
                )
    return (
        f"No matching content found. File has {len(lines)} lines. "
        f"Use read_file with offset and limit to find the section you need."
    )
