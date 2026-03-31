---
title: Recursive Tool Call Detection & Soft Recovery Warning
summary: Add a `sigil.core.llm.detect_tool_recursion` helper that identifies when
  an agent is calling the same tool with the same
status: open
complexity: small
disposition: pr
priority: 21
boldness: balanced
created: '2026-03-31T00:14:08Z'
---

# Recursive Tool Call Detection & Soft Recovery Warning

## Description

Add a `sigil.core.llm.detect_tool_recursion` helper that identifies when an agent is calling the same tool with the same arguments in a loop (distinct from the 'doom loop' of identical messages). When detected, the agent is injected with a 'System Warning' message explaining that it is repeating itself and must try a different approach (e.g., 'You have tried to read this file 3 times with the same offset. If the information is not there, try searching elsewhere.'). Implementation: Update `sigil.core.agent.Agent._run` to track tool call signatures (name + hashed args) and trigger the warning.

## Rationale

The current 'doom loop' detection in `llm.py` is a blunt instrument that breaks the loop. A 'Soft Warning' approach allows the agent to recover and try a different strategy before hitting the hard limit, which is especially useful for the Executor when it struggles to find the right line numbers for `apply_edit`.

