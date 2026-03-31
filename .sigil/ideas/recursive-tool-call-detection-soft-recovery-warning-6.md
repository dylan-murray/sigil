---
title: Recursive Tool Call Detection & Soft Recovery Warning
summary: Add a `detect_tool_recursion` helper to `sigil.core.llm` that identifies
  when an agent is calling the same tool with ide
status: open
complexity: small
disposition: pr
priority: 2
created: '2026-03-29T18:16:01Z'
---

# Recursive Tool Call Detection & Soft Recovery Warning

## Description

Add a `detect_tool_recursion` helper to `sigil.core.llm` that identifies when an agent is calling the same tool with identical arguments multiple times in a row (a 'soft' doom loop). Implementation: 1. Track tool call history in the `Agent` class. 2. If the last 2 calls are identical, inject a system warning: "Warning: You just called {tool} with these exact arguments. If it didn't work the first time, try a different approach or read more context." 3. This provides a 'nudge' to the LLM to break out of repetitive patterns before the hard 'doom loop' (3 calls) terminates the agent.

## Rationale

LLMs often get stuck in 'looping' behavior where they try the same failing command twice. A soft warning can often redirect the model's strategy, saving the execution from failure.

