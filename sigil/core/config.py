from dataclasses import dataclass, field, replace
from fnmatch import fnmatch
from pathlib import Path
from typing import Literal, get_args

import yaml


SIGIL_DIR = ".sigil"
CONFIG_FILE = "config.yml"
MEMORY_DIR = "memory"


def memory_dir(repo: Path) -> Path:
    return repo / SIGIL_DIR / MEMORY_DIR


Boldness = Literal["conservative", "balanced", "bold", "experimental"]
SandboxMode = Literal["none", "nemoclaw", "docker"]

DEFAULT_FOCUS = [
    "tests",
    "dead_code",
    "security",
    "docs",
    "types",
    "features",
    "refactoring",
]

DEFAULT_IGNORE = [
    ".sigil/**",
    ".git/**",
]

DEFAULT_MODEL = "anthropic/claude-sonnet-4-6"

AGENT_NAMES = frozenset(
    {
        "architect",
        "auditor",
        "ideator",
        "triager",
        "challenger",
        "arbiter",
        "selector",
        "engineer",
        "tool",
        "reviewer",
        "discovery",
        "compactor",
        "memory",
    }
)

AGENT_CONFIG_KEYS = {"model", "max_tokens"}


@dataclass(frozen=True, slots=True)
class Config:
    model: str = DEFAULT_MODEL
    boldness: Boldness = "bold"
    focus: list[str] = field(default_factory=lambda: list(DEFAULT_FOCUS))
    ignore: list[str] = field(default_factory=list)
    max_prs_per_run: int = 3
    max_github_issues: int = 5
    max_ideas_per_run: int = 15
    idea_ttl_days: int = 180
    pre_hooks: list[str] = field(default_factory=list)
    post_hooks: list[str] = field(default_factory=list)
    max_retries: int = 2
    max_parallel_tasks: int = 3
    max_tool_calls: int = 50
    agents: dict[str, dict] = field(default_factory=dict)
    directive_phrase: str = "@sigil work on this"
    arbiter: bool = False
    max_spend_usd: float = 20.0
    mcp_servers: list[dict] = field(default_factory=list)
    sandbox: SandboxMode = "none"
    sandbox_allowlist: tuple[str, ...] = ()

    @property
    def effective_ignore(self) -> list[str]:
        combined = list(DEFAULT_IGNORE)
        for p in self.ignore:
            if p not in combined:
                combined.append(p)
        return combined

    def is_ignored(self, path: str) -> bool:
        return any(fnmatch(path, p) for p in self.effective_ignore)

    @property
    def effective_max_retries(self) -> int:
        return max(self.max_retries, len(self.post_hooks))

    def model_for(self, agent: str) -> str:
        if agent not in AGENT_NAMES:
            raise ValueError(
                f"Unknown agent {agent!r}. Valid agents: {', '.join(sorted(AGENT_NAMES))}"
            )
        agent_cfg = self.agents.get(agent, {})
        default = self.model
        return agent_cfg.get("model", default)

    def max_tokens_for(self, agent: str) -> int | None:
        if agent not in AGENT_NAMES:
            raise ValueError(
                f"Unknown agent {agent!r}. Valid agents: {', '.join(sorted(AGENT_NAMES))}"
            )
        agent_cfg = self.agents.get(agent, {})
        val = agent_cfg.get("max_tokens")
        return int(val) if val is not None else None

    def with_model(self, model: str) -> "Config":
        return replace(self, model=model)

    @classmethod
    def load(cls, repo_path: Path) -> "Config":
        config_path = repo_path / SIGIL_DIR / CONFIG_FILE
        if not config_path.exists():
            return cls()
        try:
            raw = yaml.safe_load(config_path.read_text())
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in {CONFIG_FILE}: {e}") from e
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ValueError(f"{CONFIG_FILE} must be a YAML mapping, got {type(raw).__name__}")
        raw.pop("version", None)
        if "sandbox_allowlist" in raw and isinstance(raw["sandbox_allowlist"], list):
            raw["sandbox_allowlist"] = tuple(raw["sandbox_allowlist"])
        unknown = set(raw) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError(f"Unknown field(s) in {CONFIG_FILE}: {', '.join(sorted(unknown))}")
        agents_raw = raw.get("agents", {})
        if agents_raw:
            unknown_agents = set(agents_raw) - AGENT_NAMES
            if unknown_agents:
                raise ValueError(
                    f"Unknown agent(s) in {CONFIG_FILE}: {', '.join(sorted(unknown_agents))}. "
                    f"Valid agents: {', '.join(sorted(AGENT_NAMES))}"
                )
            for name, agent_cfg in agents_raw.items():
                if not isinstance(agent_cfg, dict):
                    raise ValueError(
                        f"agents.{name} must be a mapping, got {type(agent_cfg).__name__}"
                    )
                bad_keys = set(agent_cfg) - AGENT_CONFIG_KEYS
                if bad_keys:
                    raise ValueError(
                        f"Unknown key(s) in agents.{name}: {', '.join(sorted(bad_keys))}"
                    )
        config = cls(**raw)
        allowed = get_args(Boldness)
        if config.boldness not in allowed:
            raise ValueError(
                f"Invalid boldness {config.boldness!r} — must be one of: {', '.join(allowed)}"
            )
        sandbox_modes = get_args(SandboxMode)
        if config.sandbox not in sandbox_modes:
            raise ValueError(
                f"Invalid sandbox {config.sandbox!r} — must be one of: {', '.join(sandbox_modes)}"
            )
        if config.max_spend_usd <= 0:
            raise ValueError(f"max_spend_usd must be positive, got {config.max_spend_usd}")
        return config

    def to_yaml(self) -> str:
        agents = {k: dict(v) for k, v in self.agents.items()} if self.agents else None
        data = {
            "version": 1,
            "model": self.model,
            **({"agents": agents} if agents else {}),
            "boldness": self.boldness,
            "focus": list(self.focus),
            "ignore": list(self.ignore),
            "max_prs_per_run": self.max_prs_per_run,
            "max_github_issues": self.max_github_issues,
            "max_ideas_per_run": self.max_ideas_per_run,
            "idea_ttl_days": self.idea_ttl_days,
            "pre_hooks": list(self.pre_hooks),
            "post_hooks": list(self.post_hooks),
            "max_retries": self.max_retries,
            "max_parallel_tasks": self.max_parallel_tasks,
            "max_tool_calls": self.max_tool_calls,
            "directive_phrase": self.directive_phrase,
            "arbiter": self.arbiter,
            "max_spend_usd": self.max_spend_usd,
            "mcp_servers": list(self.mcp_servers),
            "sandbox": self.sandbox,
            "sandbox_allowlist": list(self.sandbox_allowlist),
        }
        return yaml.dump(data, default_flow_style=False, sort_keys=False)
