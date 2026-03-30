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

AGENT_CONFIG_KEYS = {"model", "max_tokens", "max_iterations"}

DEFAULT_MAX_ITERATIONS: dict[str, int] = {
    "architect": 10,
    "engineer": 50,
    "auditor": 15,
    "ideator": 15,
    "triager": 15,
    "challenger": 15,
    "arbiter": 10,
    "reviewer": 15,
    "compactor": 5,
    "memory": 5,
    "selector": 3,
    "tool": 10,
    "discovery": 5,
}


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

    def max_iterations_for(self, agent: str) -> int:
        if agent not in AGENT_NAMES:
            raise ValueError(
                f"Unknown agent {agent!r}. Valid agents: {', '.join(sorted(AGENT_NAMES))}"
            )
        agent_cfg = self.agents.get(agent, {})
        val = agent_cfg.get("max_iterations")
        if val is not None:
            return int(val)
        return DEFAULT_MAX_ITERATIONS.get(agent, 15)

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
# Validation — controls how findings and ideas are reviewed.
#   arbiter: false  Single triager pass (default, fast, cheap)
#   arbiter: true   Triager + challenger + arbiter (higher quality, ~3x cost)
# ---------------------------------------------------------------------------
# arbiter: false

# ---------------------------------------------------------------------------
# Directive phrase — Sigil scans GitHub issue comments for this phrase.
# When found, the issue is treated as a work directive for the next run.
# ---------------------------------------------------------------------------
# directive_phrase: "@sigil work on this"

# ---------------------------------------------------------------------------
# Sandbox — isolate code execution in a container.
#   none      No sandboxing (default)
#   docker    Run hooks inside a Docker container
#   nemoclaw  Run hooks inside a Nemoclaw sandbox
# ---------------------------------------------------------------------------
# sandbox: none
# sandbox_allowlist: []   # commands allowed inside the sandbox

# ---------------------------------------------------------------------------
# Per-agent model and iteration overrides.
# Use strong models for planning (architect, triager) and cheap/fast models
# for high-volume work (compactor, selector, memory).
#
# Valid agents: architect, engineer, auditor, ideator, triager, challenger,
#   arbiter, reviewer, compactor, memory, selector, tool, discovery
#
# Each agent accepts:
#   model:          override the default model
#   max_iterations: max tool calls per turn (prevents runaway agents)
# ---------------------------------------------------------------------------
# agents:
#   architect:
#     model: google/gemini-2.5-pro
#     max_iterations: 10
#   engineer:
#     model: anthropic/claude-opus-4-6
#     max_iterations: 50
#   auditor:
#     model: google/gemini-2.5-flash
#     max_iterations: 15
#   ideator:
#     model: google/gemini-2.5-flash
#     max_iterations: 15
#   triager:
#     model: anthropic/claude-sonnet-4-6
#     max_iterations: 15
#   compactor:
#     model: anthropic/claude-haiku-4-5-20251001
#     max_iterations: 5
#   memory:
#     model: google/gemini-2.5-flash
#     max_iterations: 5
#   selector:
#     model: google/gemini-2.5-flash
#     max_iterations: 3

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
