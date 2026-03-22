from dataclasses import dataclass, field
from pathlib import Path


AGENT_CONFIG_SOURCES: list[tuple[str, str, bool]] = [
    ("AGENTS.md", "AGENTS.md (universal)", False),
    ("CLAUDE.md", "Claude Code", False),
    (".cursor/rules", "Cursor", True),
    (".cursorrules", "Cursor (legacy)", False),
    (".github/copilot-instructions.md", "GitHub Copilot", False),
    ("codex.md", "Codex (OpenAI)", False),
]

CURSOR_RULES_EXTENSIONS = {".md", ".mdc", ".txt"}

PER_FILE_MAX_CHARS = 4000
MAX_TOTAL_CHARS = 8000


@dataclass(frozen=True)
class AgentConfigResult:
    detected_files: tuple[str, ...] = field(default_factory=tuple)
    source: str = ""
    content: str = ""

    @property
    def has_config(self) -> bool:
        return bool(self.content)

    def format_for_prompt(self) -> str:
        if not self.content:
            return ""
        header = ", ".join(f"`{f}`" for f in self.detected_files)
        return f"Source: {header}\n\n{self.content}"

    def format_for_pr_body(self) -> str:
        if not self.detected_files:
            return ""
        files = ", ".join(f"`{f}`" for f in self.detected_files)
        return f"## Repo Conventions\nHonored agent config: {files}"


def _read_truncated(path: Path, max_chars: int = MAX_TOTAL_CHARS) -> str:
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


def _detect_single_file(repo: Path, filename: str, source: str) -> AgentConfigResult | None:
    content = _read_truncated(repo / filename)
    if content:
        return AgentConfigResult(detected_files=(filename,), source=source, content=content)
    return None


def _detect_dir(repo: Path, dirname: str, source: str) -> AgentConfigResult | None:
    dirpath = repo / dirname
    if not dirpath.is_dir():
        return None
    parts: list[str] = []
    detected: list[str] = []
    total_chars = 0
    for child in sorted(dirpath.iterdir()):
        if total_chars >= MAX_TOTAL_CHARS:
            break
        if child.is_file() and child.suffix in CURSOR_RULES_EXTENSIONS:
            budget_left = min(PER_FILE_MAX_CHARS, MAX_TOTAL_CHARS - total_chars)
            content = _read_truncated(child, max_chars=budget_left)
            if content:
                rel = str(child.relative_to(repo))
                parts.append(content)
                detected.append(rel)
                total_chars += len(content)
    if parts:
        return AgentConfigResult(
            detected_files=tuple(detected),
            source=source,
            content="\n\n".join(parts),
        )
    return None


def detect_agent_config(repo: Path) -> AgentConfigResult:
    for path, source, is_dir in AGENT_CONFIG_SOURCES:
        if is_dir:
            result = _detect_dir(repo, path, source)
        else:
            result = _detect_single_file(repo, path, source)
        if result:
            return result
    return AgentConfigResult()
