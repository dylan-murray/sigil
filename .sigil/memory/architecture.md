# Sigil's 8-Stage Async Agentic Workflow — Pipeline Overview

Sigil operates through a linear pipeline where each stage can be configured with different LLM models. The core logic is organized into `core/` (foundational), `pipeline/` (stages), `integrations/` (GitHub/MCP), and `state/` (persistence).

## Pipeline Stages
1. **Discover:** Scans repo structure, git history, and source files using `discovery.py`.
2. **Learn:** Builds or refreshes `.sigil/memory/` knowledge files via `knowledge.py`.
3. **Connect MCP:** Loads Model Context Protocol servers to expose external tools.
4. **Analyze + Ideate:** Parallel agents (`maintenance.py` and `ideation.py`) find bugs and propose features.
5. **Validate:** Triage agent (`validation.py`) filters candidates and writes implementation specs.
6. **Execute:** Engineer agent (`executor.py`) applies changes in isolated git worktrees.
7. **Publish:** Opens GitHub PRs for successful fixes and issues for risky findings.
8. **Remember:** Updates `working.md` with run history and insights.

## Execution Isolation
Sigil uses `git worktree` to run multiple agents in parallel. Each worktree is isolated at `.sigil/worktrees/<slug>`, preventing concurrent agents from interfering with each other or the main branch.
