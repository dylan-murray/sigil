---
title: Implement .sigilignore / config.ignore filtering logic
summary: Implement a filtering mechanism in `sigil.pipeline.discovery._summarize_source_files`
  and `sigil.pipeline.maintenance.an
status: open
complexity: medium
disposition: pr
priority: 2
boldness: balanced
created: '2026-03-29T20:19:02Z'
---

# Implement .sigilignore / config.ignore filtering logic

## Description

Implement a filtering mechanism in `sigil.pipeline.discovery._summarize_source_files` and `sigil.pipeline.maintenance.analyze` that respects the `ignore` list from `config.yml`. The implementation should use the `pathspec` library (or similar glob-matching logic) to filter out files and directories before they are sent to the LLM for analysis. This ensures that 'vendor', 'node_modules', or large generated files don't consume the token budget or cause hallucinations. Update `sigil.core.config.Config` to include a `is_ignored(path)` helper method.

## Rationale

The `ignore` field is currently documented as a 'Known Gap' in `configuration.md` and `project.md`. Implementing it prevents the agent from wasting budget on irrelevant files.

