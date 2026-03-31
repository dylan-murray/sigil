---
title: Contextual Token Pruning via History Summarization
summary: Implement 'Contextual Token Pruning' in the `Agent` framework (`sigil.core.agent.Agent`).
  Instead of just masking old to
status: open
complexity: medium
disposition: pr
priority: 6
boldness: experimental
created: '2026-03-31T00:41:14Z'
---

# Contextual Token Pruning via History Summarization

## Description

Implement 'Contextual Token Pruning' in the `Agent` framework (`sigil.core.agent.Agent`). Instead of just masking old tool outputs with placeholders, use a 'Summarizer' agent to compress the middle of the conversation history when it exceeds 50% of the context window. Implementation: 1. In `Agent._run`, check token count of `self.messages`. 2. If > threshold, identify the oldest 30% of tool-use rounds. 3. Pass these rounds to a cheap model (Haiku) to produce a single 'Summary of previous steps' message. 4. Replace the original messages with this summary. 5. This preserves the 'intent' and 'findings' of early rounds without the raw token weight of large file reads or tool outputs.

## Rationale

Long-running executor passes (max 50 tool calls) quickly hit context limits or become extremely expensive. Masking is a 'dumb' fix; semantic summarization allows the agent to maintain a much longer effective memory for complex multi-file refactors.

