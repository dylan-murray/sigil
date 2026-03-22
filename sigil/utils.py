import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

StatusCallback = Callable[[str], None]


async def arun(
    cmd: str | list[str],
    *,
    cwd: Path | None = None,
    timeout: float = 30,
) -> tuple[int, str, str]:
    proc = None
    try:
        if isinstance(cmd, str):
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
        else:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
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
