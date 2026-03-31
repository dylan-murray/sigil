---
title: Refactor executor branch sentinel to Optional[str]
summary: Update `sigil.pipeline.executor.execute_parallel` and its return type hints
  to use `str | None` for branch names instead
status: open
complexity: small
disposition: pr
priority: 2
boldness: balanced
created: '2026-03-29T19:34:15Z'
---

# Refactor executor branch sentinel to Optional[str]

## Description

Update `sigil.pipeline.executor.execute_parallel` and its return type hints to use `str | None` for branch names instead of an empty string `""` sentinel. This aligns with modern Python type hinting practices (PEP 604) used elsewhere in the repo and makes the 'no branch created' state explicit. Update `sigil.cli._run` to handle the `None` case when reporting results.

## Rationale

Identified as a 'Known Bug' in `project.md`. Using `None` is more idiomatic and safer than empty string sentinels.

