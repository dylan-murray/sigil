---
title: Contextual Token Pruning via History Summarization
summary: Implement 'Contextual Token Pruning' in the `Agent` framework (`sigil.core.agent.Agent`).
  Instead of just masking old to
status: open
complexity: medium
disposition: pr
priority: 8
created: '2026-03-29T16:46:19Z'
---

# Contextual Token Pruning via History Summarization

## Description

Implement 'Contextual Token Pruning' in the `Agent` framework (`sigil.core.agent.Agent`). Instead of just masking old tool outputs with placeholders, use a 'Pruning Agent' (or a cheap model call) to summarize the *intent* and *outcome* of previous tool interactions into a single 'History Summary' block. This summary replaces the actual tool call/response messages in the context window. Implementation: 1. Add `enable_pruning` to `Agent` config. 2. In `Agent._run`, when context exceeds a threshold, call a summarizer to condense the oldest 50% of tool history. 3. Replace those messages with a single `role: "system"` message containing the summary. 4. This preserves semantic history while drastically reducing token pressure.

## Rationale

Long-running executor or auditor tasks often hit context limits or become expensive due to repetitive tool outputs. Summarizing history instead of just masking it preserves the 'why' of previous attempts while keeping the 'what' compact.

