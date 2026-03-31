---
title: Dependency-Aware Knowledge Selection via Symbol Graph
summary: Introduce a `sigil.pipeline.discovery.get_project_graph()` function that
  uses `jedi` or `tree-sitter` to build a lightwe
status: open
complexity: large
disposition: issue
priority: 13
created: '2026-03-29T17:47:08Z'
---

# Dependency-Aware Knowledge Selection via Symbol Graph

## Description

Introduce a `sigil.pipeline.discovery.get_project_graph()` function that uses `jedi` or `tree-sitter` to build a lightweight symbol graph (imports, function calls, class inheritance). When an agent is working on a specific file, the `selector` agent uses this graph to find 'Directly Impacted' files (files that import the target file) and includes their signatures in the context. This prevents 'Butterfly Effect' bugs where changing a function signature in one file breaks a distant part of the codebase that Sigil didn't 'see'. This would be a new tool for the `selector` agent.

## Rationale

Sigil's current knowledge selection is based on keyword/semantic search, which often misses logical dependencies. Graph-aware selection is the key to safe architectural changes.

