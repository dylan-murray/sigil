import asyncio
import difflib
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

_UNSAFE_SHELL_CHARS = re.compile(r"[;|&<>`$\n]")

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
            if _UNSAFE_SHELL_CHARS.search(cmd):
                raise ValueError(
                    f"Command contains unsafe shell characters: {cmd!r}. "
                    "Use a list of strings instead."
                )
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
        return (
            proc.returncode or 0,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )
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


_ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")


def expand_env_vars(value: str, *, strict: bool = False) -> str:
    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        val = os.environ.get(name)
        if val is None:
            if strict:
                raise ValueError(f"Environment variable ${{{name}}} is not set")
            return ""
        return val

    return _ENV_VAR_PATTERN.sub(_sub, value)


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
    text = text.replace("\\'", "'")
    return text


def numbered_window(lines: list[str], center: int, radius: int = 10) -> str:
    start = max(0, center - radius)
    end = min(len(lines), center + radius + 1)
    return "\n".join(f"{i + 1:>4} | {lines[i]}" for i in range(start, end))


def find_all_match_locations(content: str, old_content: str) -> list[int]:
    positions = []
    start = 0
    while True:
        idx = content.find(old_content, start)
        if idx == -1:
            break
        line_num = content[:idx].count("\n") + 1
        positions.append(line_num)
        start = idx + 1
    return positions


def format_ambiguous_matches(content: str, old_content: str, file: str) -> str:
    locations = find_all_match_locations(content, old_content)
    lines = content.splitlines()
    parts = [
        f"old_content matches {len(locations)} locations in {file}. "
        f"Include more surrounding lines to make your edit unique.\n\n"
        f"Match locations:"
    ]
    for loc in locations[:5]:
        center = loc - 1
        window = numbered_window(lines, center, radius=3)
        parts.append(f"\n--- Match at line {loc} ---\n{window}")
    if len(locations) > 5:
        parts.append(f"\n... and {len(locations) - 5} more matches")
    return "\n".join(parts)


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


FUZZY_THRESHOLD = 0.85
FUZZY_AMBIGUITY_MARGIN = 0.05


def fuzzy_find_match(content: str, old_content: str) -> tuple[str, float, int] | None:
    old_lines = old_content.splitlines(keepends=True)
    file_lines = content.splitlines(keepends=True)
    n = len(old_lines)
    if n == 0 or len(file_lines) == 0:
        return None

    anchors = _extract_anchors(old_lines)
    if not anchors:
        return None

    candidates = _find_candidate_regions(file_lines, anchors, n)
    if not candidates:
        return None

    scored: list[tuple[str, float, int]] = []
    for start, end in candidates:
        window = "".join(file_lines[start:end])
        ratio = difflib.SequenceMatcher(None, old_content, window, autojunk=False).ratio()
        scored.append((window, ratio, start + 1))

    scored.sort(key=lambda x: x[1], reverse=True)
    best_text, best_ratio, best_line = scored[0]

    if best_ratio < FUZZY_THRESHOLD:
        return None

    if len(scored) > 1:
        second_ratio = scored[1][1]
        if best_ratio - second_ratio < FUZZY_AMBIGUITY_MARGIN:
            return None

    return best_text, best_ratio, best_line


def _extract_anchors(old_lines: list[str]) -> list[str]:
    anchors = []
    for line in old_lines:
        stripped = line.strip()
        if len(stripped) >= 6 and not stripped.startswith("#"):
            anchors.append(stripped)
            if len(anchors) >= 3:
                break
    for line in reversed(old_lines):
        stripped = line.strip()
        if len(stripped) >= 6 and not stripped.startswith("#"):
            if stripped not in anchors:
                anchors.append(stripped)
                break
    return anchors


def _find_candidate_regions(
    file_lines: list[str], anchors: list[str], target_len: int
) -> list[tuple[int, int]]:
    hits: set[int] = set()
    for anchor in anchors:
        for i, line in enumerate(file_lines):
            if anchor in line.strip():
                hits.add(i)

    if not hits:
        return []

    regions: set[tuple[int, int]] = set()
    flex = max(2, target_len // 3)
    for length in range(target_len - flex, target_len + flex + 1):
        if length < 1:
            continue
        for hit in hits:
            for offset in range(-flex, flex + 1):
                start = hit + offset
                end = start + length
                if start < 0 or end > len(file_lines):
                    continue
                if any(start <= h < end for h in hits):
                    regions.add((start, end))

    if len(hits) >= 2:
        first_hit = min(hits)
        last_hit = max(hits)
        if last_hit > first_hit:
            span_start = first_hit
            span_end = last_hit + 1
            for pad in range(max(0, target_len - (span_end - span_start) - flex), flex + 1):
                end = span_end + pad
                if end <= len(file_lines):
                    regions.add((span_start, end))

    return sorted(regions)[:20]
