---
title: Recursive Tool Call Detection & Soft Recovery Warning
summary: Add a 'detect_tool_recursion' helper to sigil.core.llm that identifies when
  an agent is calling the same tool with ident
status: open
complexity: small
disposition: pr
priority: 14
boldness: balanced
created: '2026-03-31T00:41:14Z'
---

# Recursive Tool Call Detection & Soft Recovery Warning

## Description

Add a 'detect_tool_recursion' helper to sigil.core.llm that identifies when an agent is calling the same tool with identical or near-identical arguments in a loop, even if not consecutive (e.g., Tool A -> Tool B -> Tool A). If detected, the Agent framework should inject a 'System Warning' message into the conversation: 'You are repeating tool calls. Try a different approach or use the done tool to exit.' Implementation: 1. Implement detect_tool_recursion using a hash set of (tool_name, args) in the Agent loop. 2. If a duplicate is found, append the warning message to the history before the next LLM call. 3. This complements the existing 'doom loop' detection which only looks at consecutive calls.

## Rationale

Agents often get stuck in 'circular' logic that isn't strictly consecutive. This saves tokens and prevents infinite loops by nudging the agent to break the cycle. Reference: sigil.core.llm.detect_doom_loop and sigil.core.agent.Agent.run.

