from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

import yaml


SIGIL_DIR = ".sigil"
CONFIG_FILE = "config.yml"
MEMORY_DIR = "memory"

Boldness = Literal["conservative", "balanced", "bold", "experimental"]

DEFAULT_FOCUS = [
    "tests",
    "dead_code",
    "security",
    "docs",
    "types",
    "features",
]

DEFAULT_MODEL = "anthropic/claude-sonnet-4-20250514"


@dataclass(frozen=True, slots=True)
class Config:
    model: str = DEFAULT_MODEL
    boldness: Boldness = "bold"
    focus: list[str] = field(default_factory=lambda: list(DEFAULT_FOCUS))
    ignore: list[str] = field(default_factory=list)
    max_prs_per_run: int = 3
    max_issues_per_run: int = 5
    max_ideas_per_run: int = 15
    idea_ttl_days: int = 180
    schedule: str = "0 2 * * *"
    lint_cmd: str | None = None
    test_cmd: str | None = None
    max_retries: int = 3
    max_parallel_agents: int = 3

    def with_model(self, model: str) -> Config:
        return replace(self, model=model)

    @classmethod
    def load(cls, repo_path: Path) -> Config:
        config_path = repo_path / SIGIL_DIR / CONFIG_FILE
        if not config_path.exists():
            return cls()
        raw = yaml.safe_load(config_path.read_text()) or {}
        raw.pop("version", None)
        return cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})

    def to_yaml(self) -> str:
        data = {
            "version": 1,
            "model": self.model,
            "boldness": self.boldness,
            "focus": list(self.focus),
            "ignore": list(self.ignore),
            "max_prs_per_run": self.max_prs_per_run,
            "max_issues_per_run": self.max_issues_per_run,
            "max_ideas_per_run": self.max_ideas_per_run,
            "idea_ttl_days": self.idea_ttl_days,
            "schedule": self.schedule,
            "lint_cmd": self.lint_cmd,
            "test_cmd": self.test_cmd,
            "max_retries": self.max_retries,
            "max_parallel_agents": self.max_parallel_agents,
        }
        return yaml.dump(data, default_flow_style=False, sort_keys=False)
