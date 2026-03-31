---
title: Implement .sigilignore / config.ignore filtering logic
summary: Implement a robust filtering mechanism in `sigil.pipeline.discovery._summarize_source_files`
  and `sigil.pipeline.mainten
status: open
complexity: medium
disposition: pr
priority: 2
boldness: experimental
created: '2026-03-29T19:34:15Z'
---

# Implement .sigilignore / config.ignore filtering logic

## Description

Implement a robust filtering mechanism in `sigil.pipeline.discovery._summarize_source_files` and `sigil.pipeline.maintenance.analyze` that respects the `ignore` list from `config.yml`. Currently, the `ignore` field is documented but unused. The implementation should: 1. Use the `pathspec` library (or `fnmatch` for simpler cases) to match file paths against the ignore patterns. 2. Filter out ignored files during the initial `git ls-files` discovery phase. 3. Ensure the Auditor agent's `read_file` tool also respects these boundaries to prevent accidental analysis of vendor/generated code. 4. Add a default set of ignores (e.g., `.git/`, `.sigil/`, `node_modules/`) that are always active.

## Rationale

The `project.md` explicitly lists 'config.ignore field is documented but currently unused' as a known bug. Fixing this reduces token waste and prevents hallucinations on irrelevant files.

