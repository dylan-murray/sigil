from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal, get_args

import yaml


SIGIL_DIR = ".sigil"
CONFIG_FILE = "config.yml"
MEMORY_DIR = "memory"

Boldness = Literal["conservative", "balanced", "bold", "experimental"]
ValidationMode = Literal["single", "parallel"]

DEFAULT_FOCUS = [
    "tests",
    "dead_code",
    "security",
    "docs",
    "types",
    "features",
    "refactoring",
]

DEFAULT_MODEL = "anthropic/claude-sonnet-4-6"

AGENT_NAMES = frozenset(
    {
        "analyzer",
        "ideator",
        "validator",
        "codegen",
        "discovery",
        "compactor",
        "memory",
        "reviewer",
        "arbiter",
        "selector",
    }
)


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
    pre_hooks: list[str] = field(default_factory=list)
    post_hooks: list[str] = field(default_factory=list)
    max_retries: int = 1
    max_parallel_agents: int = 3
    agents: dict[str, dict] = field(default_factory=dict)
    fetch_github_issues: bool = True
    max_github_issues: int = 25
    directive_phrase: str = "@sigil work on this"
    validation_mode: ValidationMode = "single"
    max_cost_usd: float = 20.0
    mcp_servers: list[dict] = field(default_factory=list)

    def model_for(self, agent: str) -> str:
        if agent not in AGENT_NAMES:
            raise ValueError(
                f"Unknown agent {agent!r}. Valid agents: {', '.join(sorted(AGENT_NAMES))}"
            )
        agent_cfg = self.agents.get(agent, {})
        default = self.model
        return agent_cfg.get("model", default)

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
                bad_keys = set(agent_cfg) - {"model"}
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
        allowed_vm = get_args(ValidationMode)
        if config.validation_mode not in allowed_vm:
            raise ValueError(
                f"Invalid validation_mode {config.validation_mode!r} — must be one of: {', '.join(allowed_vm)}"
            )
        if config.max_cost_usd <= 0:
            raise ValueError(f"max_cost_usd must be positive, got {config.max_cost_usd}")
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
            "max_issues_per_run": self.max_issues_per_run,
            "max_ideas_per_run": self.max_ideas_per_run,
            "idea_ttl_days": self.idea_ttl_days,
            "pre_hooks": list(self.pre_hooks),
            "post_hooks": list(self.post_hooks),
            "max_retries": self.max_retries,
            "max_parallel_agents": self.max_parallel_agents,
            "fetch_github_issues": self.fetch_github_issues,
            "max_github_issues": self.max_github_issues,
            "directive_phrase": self.directive_phrase,
            "validation_mode": self.validation_mode,
            "max_cost_usd": self.max_cost_usd,
            "mcp_servers": list(self.mcp_servers),
        }
        return yaml.dump(data, default_flow_style=False, sort_keys=False)
