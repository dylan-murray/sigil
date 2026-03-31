---
title: Recursive Tool Call Detection & Soft Recovery Warning
summary: Add a `detect_tool_recursion` helper to `sigil.core.llm` that identifies
  when an agent is calling the same tool with ide
status: open
complexity: small
disposition: pr
priority: 7
boldness: experimental
created: '2026-03-29T20:19:02Z'
---

# Recursive Tool Call Detection & Soft Recovery Warning

## Description

Add a `detect_tool_recursion` helper to `sigil.core.llm` that identifies when an agent is calling the same tool with identical or near-identical arguments multiple times in a row.

Implementation:
1. In `sigil.core.agent.Agent._run`, maintain a short history of tool calls (name + hashed args).
2. If the same tool is called with the same args 3 times (or 2 times if the previous output was an error), trigger a 'Soft Recovery'.
3. The 'Soft Recovery' injects a system message: 'WARNING: You are in a tool-use loop. The previous 3 attempts to use [Tool] failed to progress the state. Try a different approach or read a different file.'
4. This is a more proactive version of the existing 'Doom Loop' detection which just kills the agent. It gives the agent a chance to pivot.

## Rationale

Agents often get stuck trying to `apply_edit` to the same line repeatedly when a linter fails. Proactive recursion detection with a 'hint' can save significant tokens and improve success rates.

