---
title: Contextual Token Pruning via History Summarization
summary: Implement 'Contextual Token Pruning' in the Agent framework (sigil.core.agent.Agent).
  Instead of just masking old tool o
status: open
complexity: medium
disposition: issue
priority: 2
created: '2026-03-29T17:47:08Z'
---

# Contextual Token Pruning via History Summarization

## Description

Implement 'Contextual Token Pruning' in the Agent framework (sigil.core.agent.Agent). Instead of just masking old tool outputs with a static placeholder, use a 'Summarizer' agent to compress the history of completed tool interactions into a concise 'Observation Log'.

Implementation:
1. Add a `summarize_history` method to `Agent`.
2. When `threshold_tokens` is exceeded, instead of `mask_old_tool_outputs`, call a Haiku-based summarizer.
3. The summarizer takes the messages and produces a single `system` message: "Previous Observations: [Summary of files read, edits made, and results]".
4. Replace the pruned messages with this summary.
5. Update `sigil.core.llm.compact_messages` to use this more intelligent approach.

This preserves the 'mental model' of the agent across long execution loops (like complex refactors) while staying within context limits and reducing costs.

## Rationale

The current `mask_old_tool_outputs` is a 'dumb' truncation that can cause the agent to lose track of what it has already tried, leading to doom loops. Intelligent pruning is essential for the 'Engineer' agent's 50-iteration limit.

