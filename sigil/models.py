from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Component:
    name: str
    path: str
    description: str


@dataclass(frozen=True, slots=True)
class RepoModel:
    name: str
    language: str
    stack: list[str] = field(default_factory=list)
    purpose: str = ""
    key_components: list[Component] = field(default_factory=list)
    conventions: list[str] = field(default_factory=list)
    test_command: str | None = None
    lint_command: str | None = None
    build_command: str | None = None
    ci_provider: str | None = None
    open_issues_summary: str = ""
    file_count: int = 0
    top_level_dirs: list[str] = field(default_factory=list)
    readme_snippet: str = ""
    claude_md_snippet: str = ""
    recent_commits: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"Project: {self.name}",
            f"Language: {self.language}",
            f"Stack: {', '.join(self.stack) if self.stack else 'unknown'}",
            f"Purpose: {self.purpose or 'unknown'}",
            f"Files: {self.file_count}",
        ]
        if self.test_command:
            lines.append(f"Test: {self.test_command}")
        if self.lint_command:
            lines.append(f"Lint: {self.lint_command}")
        if self.build_command:
            lines.append(f"Build: {self.build_command}")
        if self.ci_provider:
            lines.append(f"CI: {self.ci_provider}")
        if self.key_components:
            lines.append(f"Components: {len(self.key_components)}")
            for c in self.key_components:
                lines.append(f"  - {c.name}: {c.description}")
        return "\n".join(lines)
