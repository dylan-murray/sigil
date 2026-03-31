---
title: 'Churn-Aware Discovery: Prioritizing High-Entropy Code Hotspots'
summary: Implement 'Entropy-Based Discovery' in `sigil.pipeline.discovery`. Instead
  of just summarizing files by size or alphabet
status: open
complexity: medium
disposition: issue
priority: 6
boldness: experimental
created: '2026-03-29T19:34:15Z'
---

# Churn-Aware Discovery: Prioritizing High-Entropy Code Hotspots

## Description

Implement 'Entropy-Based Discovery' in `sigil.pipeline.discovery`. Instead of just summarizing files by size or alphabetical order, calculate a 'Change Entropy' score for every file in the repo using `git log --numstat`. Files with high churn (high entropy) are given more budget in the `_summarize_source_files` loop, while stable files (low entropy) are summarized minimally. This forces Sigil's 'attention' toward the parts of the codebase that are actually being evolved by humans, leading to more relevant findings and ideas. Data flow: `git log` → `entropy_score` → `summarization_priority`.

## Rationale

Sigil shouldn't spend tokens analyzing stable library code. It should focus where the 'action' is, as defined by historical developer activity.

