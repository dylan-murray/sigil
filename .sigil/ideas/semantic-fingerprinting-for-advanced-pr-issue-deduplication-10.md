---
title: Semantic Fingerprinting for Advanced PR/Issue Deduplication
summary: Implement a 'Semantic Diff Analysis' tool for the `integrations/github` module.
  Instead of comparing strings for dedupli
status: open
complexity: medium
disposition: pr
priority: 13
boldness: balanced
created: '2026-03-29T20:19:02Z'
---

# Semantic Fingerprinting for Advanced PR/Issue Deduplication

## Description

Implement a 'Semantic Diff Analysis' tool for the `integrations/github` module. Instead of comparing strings for deduplication, use an LLM (or a local embedding model) to generate 'Semantic Fingerprints' of existing PRs and issues. This would allow Sigil to detect that an existing PR titled 'Fix async race in llm' is semantically identical to its new finding 'Resolve concurrency issue in acompletion', even if the words and file paths differ slightly. This prevents duplicate PRs where Jaccard similarity (current method) fails due to different naming conventions.

## Rationale

Current dedup in `integrations/github.py` uses Jaccard similarity (0.6 threshold). This is brittle against varied natural language descriptions of the same technical problem.

