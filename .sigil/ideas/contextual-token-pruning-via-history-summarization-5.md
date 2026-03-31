---
title: Contextual Token Pruning via History Summarization
summary: Implement 'Contextual Token Pruning' in `sigil.core.llm.compact_messages`.
  Instead of just masking old tool outputs with
status: open
complexity: medium
disposition: issue
priority: 10
created: '2026-03-29T18:16:01Z'
---

# Contextual Token Pruning via History Summarization

## Description

Implement 'Contextual Token Pruning' in `sigil.core.llm.compact_messages`. Instead of just masking old tool outputs with placeholders, use a cheap model (Haiku) to generate a 1-2 sentence summary of what that tool call achieved (e.g., 'Read config.py and found no issues'). Replace the multi-kilobyte tool output with this summary. This preserves the 'semantic thread' of the conversation while aggressively reclaiming context window space, allowing for much longer agent trajectories (e.g., 100+ rounds) without hitting token limits or losing track of the goal.

## Rationale

Long-running agents (like the Engineer) often hit context limits or 'forget' early discoveries because of the current simple masking. Semantic pruning keeps the agent oriented for a fraction of the token cost.

