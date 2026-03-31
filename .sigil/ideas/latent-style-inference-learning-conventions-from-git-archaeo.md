---
title: 'Latent Style Inference: Learning Conventions from Git Archaeology'
summary: Implement 'Latent Style Inference' by performing a 'Git Archaeology' pass
  during discovery to extract the repo's actual
status: done
complexity: medium
disposition: pr
priority: 3
boldness: experimental
created: '2026-03-29T20:19:02Z'
---

# Latent Style Inference: Learning Conventions from Git Archaeology

## Description

Implement 'Latent Style Inference' by performing a 'Git Archaeology' pass during discovery to extract the repo's actual (not just documented) coding conventions.

Implementation:
1. Create `sigil.pipeline.discovery.archaeologist()`.
2. Use `git log -p -n 20` to fetch the last 20 manual (non-Sigil) commits.
3. Pass these diffs to a specialized Haiku agent to extract 'Latent Rules' (e.g., "Prefers early returns," "Uses f-strings for logging," "Avoids list comprehensions for complex logic").
4. Ingest these inferred rules into the `Instructions` object used by the Engineer and QA agents.

This allows Sigil to 'blend in' with the human team's style without requiring an explicit AGENTS.md.

## Rationale

Standard agent configs (AGENTS.md) are often outdated. Real truth lives in the git history. This makes Sigil's PRs look more 'human' and native to the target repo.

