---
title: 'Sigil Situation Room: Real-time Terminal Observability Dashboard'
summary: Add a `sigil dashboard` command that launches a local, lightweight 'Situation
  Room' (using Textual or a simple Rich Live
status: open
complexity: small
disposition: pr
priority: 6
created: '2026-03-29T15:44:20Z'
---

# Sigil Situation Room: Real-time Terminal Observability Dashboard

## Description

Add a `sigil dashboard` command that launches a local, lightweight 'Situation Room' (using Textual or a simple Rich Live display) to monitor the agent in real-time.

Implementation:
1. `sigil/ui/dashboard.py`: Uses `rich.live.Live` to create a multi-pane terminal interface.
2. Panes: 
    - **The 'Thought Stream'**: Real-time streaming of the current agent's `reasoning` (hidden from standard logs but visible here).
    - **Resource usage**: Current run cost vs `max_cost_usd` with a progress bar.
    - **Worktree Map**: Showing active branches and their current pipeline stage (Executing, Testing, Rebasing).
3. The dashboard reads from a local socket or a json-l file that `cli.py` updates during the run.

This provides observability into the 'Black Box' of autonomous execution, making it much easier for developers to trust (and debug) the agent during local runs.

## Rationale

Autonomous agents are opaque. When Sigil is running `execute_parallel`, the user just sees a spinner. A 'Situation Room' provides the transparency needed to debug complex agent behaviors like the 'self-reinforcing loops' mentioned in memory.

