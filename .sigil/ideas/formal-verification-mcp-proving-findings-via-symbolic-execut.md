---
title: 'Formal Verification MCP: Proving Findings via Symbolic Execution'
summary: Integrate a 'Symbolic Execution' MCP tool that agents can use to trace variable
  flow without running the full test suite
status: open
complexity: medium
disposition: issue
priority: 19
created: '2026-03-29T15:44:20Z'
---

# Formal Verification MCP: Proving Findings via Symbolic Execution

## Description

Integrate a 'Symbolic Execution' MCP tool that agents can use to trace variable flow without running the full test suite. This tool would use a library like `crosshair` or `pytype` to provide 'Counter-Examples' to an agent's assumptions (e.g., 'If x is None, this line will raise AttributeError'). When the Auditor finds a bug, it can 'Prove' the bug exists by asking the Symbolic Tool to find an input that triggers it. This moves Sigil from 'Pattern Matching' bugs to 'Verifying' bugs, reducing false positives in the `pipeline/maintenance.py` stage.

## Rationale

Sigil currently relies on LLM intuition for bugs. Adding a symbolic verification step in the toolset (`core/mcp.py`) bridges the gap between LLM 'guessing' and formal verification.

