---
title: Recursive Tool Call Detection & Soft Recovery Warning
summary: Add a `detect_tool_recursion` helper to `sigil.core.llm` that identifies
  when an agent is calling the same tool with ide
status: open
complexity: small
disposition: pr
priority: 7
boldness: experimental
created: '2026-03-31T00:41:14Z'
---

# Recursive Tool Call Detection & Soft Recovery Warning

## Description

Add a `detect_tool_recursion` helper to `sigil.core.llm` that identifies when an agent is calling the same tool with identical arguments multiple times in a row (a 'soft' doom loop). Unlike the existing doom loop detection which looks for 3 identical *consecutive* calls, this should track a window of the last 5 calls and issue a 'Warning' message to the LLM if it sees a repeat, encouraging it to try a different approach before the hard limit is hit. Implementation: 1. Add `detect_tool_recursion` function. 2. Integrate into `Agent._run_loop`. 3. If recursion is detected, inject a system message: "Warning: You are repeating tool calls. If you are stuck, try a different strategy or use a different tool."

## Rationale

Agents often get stuck in loops that aren't perfectly consecutive (e.g., Tool A -> Tool B -> Tool A). Early warnings can help the LLM self-correct before the run is aborted.

