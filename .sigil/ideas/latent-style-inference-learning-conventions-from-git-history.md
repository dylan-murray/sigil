---
title: 'Latent Style Inference: Learning Conventions from Git History Diffs'
summary: Implement 'Latent Instruction Discovery' in `sigil.core.instructions`. Beyond
  just reading `AGENTS.md`, Sigil should per
status: open
complexity: small
disposition: pr
priority: 10
boldness: experimental
created: '2026-03-29T19:34:15Z'
---

# Latent Style Inference: Learning Conventions from Git History Diffs

## Description

Implement 'Latent Instruction Discovery' in `sigil.core.instructions`. Beyond just reading `AGENTS.md`, Sigil should perform a `git log -p -n 5` on recent PR merges to 'Incorporate Latent Style.' It analyzes the diffs and comments of recently accepted work to infer project conventions that haven't been documented (e.g., 'always use f-strings,' 'prefer early returns'). These inferred rules are appended to the `Instructions` object used by all agents. This allows Sigil to 'learn' the house style of a repo just by watching its history. 1. Add `_infer_style_from_history` to `instructions.py`. 2. Injects a 'Style Inferences' section into the system prompt.

## Rationale

Documentation is always out of date. Git history is the only true source of current engineering conventions.

