---
title: Contextual Token Pruning via History Summarization
summary: Implement 'Contextual Token Pruning' in the `Agent` framework (`sigil.core.agent.Agent`).
  Instead of just masking old to
status: open
complexity: medium
disposition: pr
priority: 6
boldness: experimental
created: '2026-03-29T19:34:15Z'
---

# Contextual Token Pruning via History Summarization

## Description

Implement 'Contextual Token Pruning' in the `Agent` framework (`sigil.core.agent.Agent`). Instead of just masking old tool outputs with placeholders, the agent should use a 'Summarizer' agent to compress the *content* of old tool outputs into a concise summary while preserving the *fact* that the tool was called and what it returned. This keeps the context window clean while retaining the logical flow of the conversation. Implementation: 1. Add a `summarize_history` method to `Agent`. 2. When `enable_compaction` is triggered, instead of `mask_old_tool_outputs`, call a lightweight model (Haiku) to summarize the oldest 50% of tool results. 3. Replace the original messages with the summarized versions.

## Rationale

Long-running executor agents currently struggle with context limits. Intelligent summarization is superior to simple masking for maintaining logical consistency in complex tasks.

