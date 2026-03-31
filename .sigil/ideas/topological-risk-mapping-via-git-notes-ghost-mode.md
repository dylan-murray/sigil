---
title: Topological Risk Mapping via Git Notes (Ghost Mode)
summary: Implement 'Sigil Ghost Mode' using `git notes`. When Sigil is running in
  a shared repository, it can leave 'Ghost Commen
status: open
complexity: large
disposition: issue
priority: 2
created: '2026-03-29T16:46:19Z'
---

# Topological Risk Mapping via Git Notes (Ghost Mode)

## Description

Implement 'Sigil Ghost Mode' using `git notes`. When Sigil is running in a shared repository, it can leave 'Ghost Comments' (invisible to standard git logs but readable via `git notes show`) on specific lines of code it identifies as problematic but isn't 'bold' enough to fix yet. Other Sigil instances (or the same one in a future run) can aggregate these 'Ghost Notes' as a high-signal priority heat map. This allows the Auditor agent to build a long-term 'Topological Risk Map' of the codebase that persists in the git object store without polluting the file system or creating issue noise until a threshold of 'ghost sightings' is reached.

## Rationale

Current discovery is ephemeral and budget-constrained. Using git notes provides a decentralized, permanent, and non-intrusive way for an autonomous agent to build long-term 'intuition' about a codebase's technical debt hotspots.

