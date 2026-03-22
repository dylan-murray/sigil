from dataclasses import dataclass, field
from pathlib import Path


AGENT_CONFIG_PRIORITY: list[tuple[str, str]] = [
    ("AGENTS.md", "AGENTS.md (universal)"),
    ("CLAUDE.md", "Claude Code"),
    (".cursorrules", "Cursor (legacy)"),
    (".github/copilot-instructions.md", "GitHub Copilot"),
    ("codex.md", "Codex (OpenAI)"),
    (".aider.conf.yml", "Aider"),
]

AGENT_CONFIG_DIRS: list[tuple[str, str]] = [
    (".cursor/rules", "Cursor"),
]

CURSOR_RULES_EXTENSIONS = {".md", ".mdc", ".txt", ""}

MAX_CONFIG_CHARS = 4000


@dataclass(frozen=True)
class AgentConfigResult:
    detected_files: list[str] = field(default_factory=list)
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


def _read_truncated(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return ""
    if len(text) > MAX_CONFIG_CHARS:
        return text[:MAX_CONFIG_CHARS] + "\n... (truncated)"
    return text


def detect_agent_config(repo: Path) -> AgentConfigResult:
    for filename, source in AGENT_CONFIG_PRIORITY:
        content = _read_truncated(repo / filename)
        if content:
            return AgentConfigResult(detected_files=[filename], source=source, content=content)

    for dirname, source in AGENT_CONFIG_DIRS:
        dirpath = repo / dirname
        if not dirpath.is_dir():
            continue
        parts: list[str] = []
        detected: list[str] = []
        for child in sorted(dirpath.iterdir()):
            if child.is_file() and child.suffix in CURSOR_RULES_EXTENSIONS:
                content = _read_truncated(child)
                if content:
                    rel = str(child.relative_to(repo))
                    parts.append(content)
                    detected.append(rel)
        if parts:
            return AgentConfigResult(
                detected_files=detected,
                source=source,
                content="\n\n".join(parts),
            )

    return AgentConfigResult()
