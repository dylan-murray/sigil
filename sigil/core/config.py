from dataclasses import dataclass, field, replace
from fnmatch import fnmatch
from pathlib import Path
from typing import Literal, get_args

import yaml


SIGIL_DIR = ".sigil"
CONFIG_FILE = "config.yml"
MEMORY_DIR = "memory"

_MODEL_OVERRIDE_FIELDS = frozenset({"max_input_tokens", "max_output_tokens"})


def _validate_model_overrides(raw: object) -> dict[str, dict[str, int]]:
    if not isinstance(raw, dict):
        raise ValueError(f"model_overrides must be a mapping, got {type(raw).__name__}")
    resolved: dict[str, dict[str, int]] = {}
    for model, cfg in raw.items():
        if not isinstance(cfg, dict):
            raise ValueError(f"model_overrides.{model} must be a mapping, got {type(cfg).__name__}")
        bad = set(cfg) - _MODEL_OVERRIDE_FIELDS
        if bad:
            raise ValueError(
                f"Unknown key(s) in model_overrides.{model}: {', '.join(sorted(bad))}. "
                f"Valid keys: {', '.join(sorted(_MODEL_OVERRIDE_FIELDS))}"
            )
        entry: dict[str, int] = {}
        for key, val in cfg.items():
            if not isinstance(val, int) or val <= 0:
                raise ValueError(
                    f"model_overrides.{model}.{key} must be a positive integer, got {val!r}"
                )
            entry[key] = val
        resolved[model] = entry
    return resolved


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
    ".venv/**",
    "venv/**",
    "env/**",
    "__pycache__/**",
    "*.pyc",
    "*.pyo",
    "*.egg-info/**",
    ".mypy_cache/**",
    ".pytest_cache/**",
    ".ruff_cache/**",
    ".tox/**",
    "node_modules/**",
    "dist/**",
    "build/**",
    ".next/**",
    ".cache/**",
    "target/**",
    "*.so",
    "*.dylib",
    "*.dll",
    "*.o",
    "*.a",
    "*.class",
    "*.jar",
]

DEFAULT_MODEL = "anthropic/claude-sonnet-4-6"

AGENT_NAMES = frozenset(
    {
        "architect",
        "auditor",
        "ideator",
        "triager",
        "selector",
        "engineer",
        "discovery",
        "compactor",
        "memory",
    }
)

AGENT_CONFIG_KEYS = {"model", "max_tokens", "max_iterations", "reasoning_effort"}

VALID_REASONING_EFFORTS = frozenset({"low", "medium", "high"})

DEFAULT_MAX_ITERATIONS: dict[str, int] = {
    "architect": 15,
    "engineer": 50,
    "auditor": 15,
    "ideator": 15,
    "triager": 15,
    "compactor": 5,
    "memory": 5,
    "selector": 3,
    "discovery": 5,
}


@dataclass(frozen=True, slots=True)
class AgentSpec:
    model: str
    max_tokens: int | None
    max_iterations: int
    reasoning_effort: str | None


def _validate_agent_entry(entry: object, label: str) -> None:
    if not isinstance(entry, dict):
        raise ValueError(f"{label} must be a mapping, got {type(entry).__name__}")
    bad_keys = set(entry) - AGENT_CONFIG_KEYS
    if bad_keys:
        raise ValueError(
            f"Unknown key(s) in {label}: {', '.join(sorted(bad_keys))}. "
            f"Valid keys: {', '.join(sorted(AGENT_CONFIG_KEYS))}"
        )
    re_val = entry.get("reasoning_effort")
    if re_val is not None and re_val not in VALID_REASONING_EFFORTS:
        raise ValueError(
            f"Invalid reasoning_effort {re_val!r} for {label} "
            f"— must be one of: {', '.join(sorted(VALID_REASONING_EFFORTS))}"
        )


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
    llm_timeout: int = 300
    max_parallel_tasks: int = 3
    agents: dict[str, list[dict]] = field(default_factory=dict)
    directive_phrase: str = "@sigil work on this"
    max_spend_usd: float = 20.0
    mcp_servers: list[dict] = field(default_factory=list)
    model_overrides: dict[str, dict[str, int]] = field(default_factory=dict)
    sandbox: SandboxMode = "none"
    sandbox_allowlist: tuple[str, ...] = ()
    adaptive_stages: bool = False

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

    def instances_for(self, agent: str) -> list[AgentSpec]:
        if agent not in AGENT_NAMES:
            raise ValueError(
                f"Unknown agent {agent!r}. Valid agents: {', '.join(sorted(AGENT_NAMES))}"
            )
        raw = self.agents.get(agent) or [{}]
        default_iters = DEFAULT_MAX_ITERATIONS.get(agent, 15)
        result: list[AgentSpec] = []
        for entry in raw:
            max_tok_raw = entry.get("max_tokens")
            result.append(
                AgentSpec(
                    model=entry.get("model", self.model),
                    max_tokens=int(max_tok_raw) if max_tok_raw is not None else None,
                    max_iterations=int(entry.get("max_iterations", default_iters)),
                    reasoning_effort=entry.get("reasoning_effort"),
                )
            )
        return result

    def model_for(self, agent: str) -> str:
        return self.instances_for(agent)[0].model

    def max_iterations_for(self, agent: str) -> int:
        return self.instances_for(agent)[0].max_iterations

    def max_tokens_for(self, agent: str) -> int | None:
        return self.instances_for(agent)[0].max_tokens

    def reasoning_effort_for(self, agent: str) -> str | None:
        return self.instances_for(agent)[0].reasoning_effort

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
        if "model_overrides" in raw:
            raw["model_overrides"] = _validate_model_overrides(raw["model_overrides"])
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
            for name, instances in agents_raw.items():
                if not isinstance(instances, list):
                    raise ValueError(
                        f"agents.{name} must be a list, got {type(instances).__name__}"
                    )
                if not instances:
                    raise ValueError(
                        f"agents.{name} must have at least one entry (use a list of dicts)"
                    )
                for i, entry in enumerate(instances):
                    _validate_agent_entry(entry, f"agents.{name}[{i}]")
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
        focus_lines = "\n".join(f"  - {f}" for f in self.focus)
        return f"""\
# Sigil configuration — https://github.com/dylan-murray/sigil
version: 1

# ---------------------------------------------------------------------------
# LLM model (any litellm-supported model)
# See https://docs.litellm.ai/docs/providers for the full provider list.
# ---------------------------------------------------------------------------
model: {self.model}

# ---------------------------------------------------------------------------
# Boldness — controls how aggressive Sigil's suggestions are.
#   conservative  Only obvious, low-risk fixes
#   balanced      Safe refactors and common maintenance
#   bold          Broader cleanup, docs, and testing improvements
#   experimental  Speculative ideas and larger suggestions
# ---------------------------------------------------------------------------
boldness: {self.boldness}

# ---------------------------------------------------------------------------
# Focus areas — what types of improvements Sigil looks for.
# ---------------------------------------------------------------------------
focus:
{focus_lines}

# ---------------------------------------------------------------------------
# Ignore patterns — glob patterns for files Sigil should skip entirely
# during discovery, analysis, and execution. .sigil/** and .git/** are
# always ignored.
# ---------------------------------------------------------------------------
# ignore:
#   - "vendor/**"
#   - "*.generated.*"
#   - "node_modules/**"

# ---------------------------------------------------------------------------
# Per-run limits
# ---------------------------------------------------------------------------
max_prs_per_run: {self.max_prs_per_run}        # max pull requests opened per run
max_github_issues: {self.max_github_issues}      # max issues opened per run
max_ideas_per_run: {self.max_ideas_per_run}     # max ideas generated per run
idea_ttl_days: {self.idea_ttl_days}          # days before stale ideas are auto-pruned

# ---------------------------------------------------------------------------
# Execution settings
# ---------------------------------------------------------------------------
max_retries: {self.max_retries}              # retries after a post-hook failure
max_parallel_tasks: {self.max_parallel_tasks}      # max parallel git worktrees during execution
max_spend_usd: {self.max_spend_usd}          # hard cost cap per run (USD) — raises BudgetExceededError

# ---------------------------------------------------------------------------
# Adaptive stage skipping — skip pipeline stages when nothing changed.
# When enabled, Sigil compares the current HEAD to the last run's commit.
# If no files changed, discovery and analysis are skipped (findings re-used).
# Override with --force-all to run all stages regardless.
# ---------------------------------------------------------------------------
# adaptive_stages: true

# ---------------------------------------------------------------------------
# Pre/post hooks — shell commands that gate code generation.
#   pre_hooks:  run BEFORE code generation. If any fails, the item is aborted.
#   post_hooks: run AFTER code generation. If any fails, the agent retries
#               (up to max_retries). Failed items are downgraded to issues.
# ---------------------------------------------------------------------------
# pre_hooks:
#   - uv run ruff check .
# post_hooks:
#   - uv run ruff format .
#   - uv run pytest tests/ -x -q

# ---------------------------------------------------------------------------
# Per-agent configuration.
# Each agent value is a LIST of one or more instance configs. Multiple entries
# = multiple parallel instances (currently used by `ideator` to get diverse
# perspectives across models). Singletons are still lists of one for schema
# uniformity.
#
# Valid agents: architect, engineer, auditor, ideator, triager,
#   compactor, memory, selector, discovery
#
# Each entry accepts:
#   model:            override the global model for this instance
#   max_tokens:       max output tokens per call
#   max_iterations:   max tool calls per turn (prevents runaway agents)
#   reasoning_effort: low / medium / high (for models that support reasoning)
# ---------------------------------------------------------------------------
# agents:
#   ideator:
#     - model: anthropic/claude-opus-4-7
#     - model: openai/gpt-5
#       reasoning_effort: medium
#     - model: google/gemini-2.5-pro
#   architect:
#     - model: google/gemini-2.5-pro
#       max_iterations: 10
#   engineer:
#     - model: anthropic/claude-opus-4-6
#       max_iterations: 50
#   auditor:
#     - model: google/gemini-2.5-flash
#   triager:
#     - model: anthropic/claude-sonnet-4-6
#   compactor:
#     - model: anthropic/claude-haiku-4-5-20251001
#       max_iterations: 5
#   memory:
#     - model: google/gemini-2.5-flash
#       max_iterations: 5
#   selector:
#     - model: google/gemini-2.5-flash
#       max_iterations: 3

# ---------------------------------------------------------------------------
# MCP servers — connect external tools via the Model Context Protocol.
# Sigil exposes MCP tools to all agents, namespaced as mcp__<server>__<tool>.
# Environment variable placeholders (${{VAR}}) are resolved at runtime.
# ---------------------------------------------------------------------------
# mcp_servers:
#   - name: notion
#     command: npx
#     args: ["-y", "@notionhq/mcp-server"]
#     env:
#       NOTION_API_KEY: "${{NOTION_API_KEY}}"
#     purpose: "product requirements and design docs"
#   - name: snowflake
#     url: "http://localhost:3001/sse"
#     headers:
#       Authorization: "Bearer ${{SNOWFLAKE_TOKEN}}"
#     purpose: "data warehouse schemas and query results"
"""
