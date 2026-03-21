"""NemoClaw / Docker sandbox for isolated agent execution.

Wraps Sigil's executor in a security sandbox so LLM-driven code generation,
file I/O, and shell commands (lint/test) run with restricted filesystem,
network, and process capabilities.

Architecture:
  Host (Sigil orchestrator)          Sandbox (NemoClaw or Docker)
  ┌──────────────────────┐           ┌──────────────────────────┐
  │ discover, learn,     │           │ executor_worker.py       │
  │ analyze, validate    │           │ ├─ LLM tool loop         │
  │                      │  create   │ ├─ read/edit/create files │
  │ execute_parallel()───┼──────────▶│ ├─ lint + test            │
  │                      │  result   │ └─ write result.json      │
  │ push, PR, cleanup  ◀─┼──────────│                           │
  └──────────────────────┘  teardown └──────────────────────────┘

Network inside sandbox: LLM API + package manager only. No GitHub API.
Filesystem: worktree directory only. No host access.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sigil.core.config import Config
from sigil.core.utils import arun

SANDBOX_TIMEOUT = 60
BLOCKED_DOMAINS = frozenset({
    "169.254.169.254",
    "metadata.google.internal",
    "localhost",
    "127.0.0.1",
})

MODEL_DOMAIN_MAP: dict[str, list[str]] = {
    "anthropic": ["api.anthropic.com"],
    "openai": ["api.openai.com"],
    "gemini": ["generativelanguage.googleapis.com"],
    "vertex_ai": ["us-central1-aiplatform.googleapis.com"],
    "azure": ["openai.azure.com"],
}

PACKAGE_MANAGER_DOMAINS = [
    "pypi.org",
    "files.pythonhosted.org",
]


@dataclass(frozen=True)
class SandboxContext:
    sandbox_id: str
    sandbox_type: str  # nemoclaw | docker
    worktree_path: Path


def _infer_provider(model: str) -> str:
    if "/" in model:
        return model.split("/")[0]
    return "openai"


def _validate_allowlist(domains: list[str]) -> list[str]:
    validated = []
    for domain in domains:
        domain = domain.strip().lower()
        if not domain:
            continue
        if domain in BLOCKED_DOMAINS:
            continue
        if "*" in domain:
            continue
        if domain.replace(".", "").replace("-", "").replace(":", "").isdigit():
            continue
        validated.append(domain)
    return validated


def build_network_allowlist(config: Config) -> list[str]:
    provider = _infer_provider(config.model)
    domains = list(MODEL_DOMAIN_MAP.get(provider, ["api.openai.com"]))
    domains.extend(PACKAGE_MANAGER_DOMAINS)
    user_domains = _validate_allowlist(list(config.sandbox_allowlist))
    domains.extend(user_domains)
    return sorted(set(domains))


async def create(worktree_path: Path, config: Config) -> SandboxContext:
    if config.sandbox == "nemoclaw":
        return await _setup_nemoclaw(worktree_path, config)
    if config.sandbox == "docker":
        return await _setup_docker(worktree_path, config)
    raise ValueError(f"Unknown sandbox type: {config.sandbox}")


async def _setup_nemoclaw(worktree_path: Path, config: Config) -> SandboxContext:
    sandbox_id = f"sigil-{worktree_path.name}"
    rc, stdout, stderr = await arun(
        ["nemoclaw", "onboard", "--name", sandbox_id],
        cwd=worktree_path,
        timeout=SANDBOX_TIMEOUT,
    )
    if rc != 0:
        rc_check, _, _ = await arun(["which", "docker"], timeout=5)
        if rc_check == 0:
            return await _setup_docker(worktree_path, config)
        raise RuntimeError(
            f"NemoClaw onboard failed (exit {rc}): {stderr.strip()}\n"
            f"Docker fallback not available."
        )
    return SandboxContext(
        sandbox_id=sandbox_id,
        sandbox_type="nemoclaw",
        worktree_path=worktree_path,
    )


async def _setup_docker(worktree_path: Path, config: Config) -> SandboxContext:
    sandbox_id = f"sigil-docker-{worktree_path.name}"
    rc, _, stderr = await arun(["which", "docker"], timeout=5)
    if rc != 0:
        raise RuntimeError("Docker is not available. Cannot create sandbox.")
    return SandboxContext(
        sandbox_id=sandbox_id,
        sandbox_type="docker",
        worktree_path=worktree_path,
    )


async def run_in_sandbox(
    ctx: SandboxContext,
    config: Config,
    worker_args_path: Path,
) -> int:
    if ctx.sandbox_type == "nemoclaw":
        cmd = [
            "nemoclaw", ctx.sandbox_id, "connect", "--",
            "python", "-m", "sigil.pipeline.executor_worker",
            str(worker_args_path),
        ]
        rc, _, _ = await arun(cmd, cwd=ctx.worktree_path, timeout=600)
        return rc

    import os

    cmd = [
        "docker", "run", "--rm",
        "--name", ctx.sandbox_id,
        "--cap-drop=ALL",
        "-v", f"{ctx.worktree_path}:/workspace:rw",
        "-w", "/workspace",
        "-e", f"SIGIL_WORKER_ARGS=/workspace/{worker_args_path.name}",
    ]

    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        if key in os.environ:
            cmd.extend(["-e", key])

    cmd.extend([
        "python:3.11-slim",
        "python", "-m", "sigil.pipeline.executor_worker",
        f"/workspace/{worker_args_path.name}",
    ])

    rc, _, _ = await arun(cmd, cwd=ctx.worktree_path, timeout=600)
    return rc


async def teardown(ctx: SandboxContext) -> None:
    try:
        if ctx.sandbox_type == "nemoclaw":
            await arun(
                ["nemoclaw", ctx.sandbox_id, "remove"],
                timeout=30,
            )
        elif ctx.sandbox_type == "docker":
            await arun(
                ["docker", "rm", "-f", ctx.sandbox_id],
                timeout=10,
            )
    except Exception:
        pass
