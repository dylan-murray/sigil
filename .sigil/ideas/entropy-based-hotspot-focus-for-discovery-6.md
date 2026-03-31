---
title: Entropy-Based Hotspot Focus for Discovery
summary: Introduce 'Sigil Entropy-Based Focus' (EBF) in sigil.pipeline.discovery.
  Instead of static focus areas (tests, docs, etc
status: open
complexity: medium
disposition: pr
priority: 9
boldness: balanced
created: '2026-03-31T00:41:14Z'
---

# Entropy-Based Hotspot Focus for Discovery

## Description

Introduce 'Sigil Entropy-Based Focus' (EBF) in sigil.pipeline.discovery. Instead of static focus areas (tests, docs, etc.), Sigil will analyze the project's 'Change Entropy' by examining git commit frequency vs. file complexity (using a lightweight cyclomatic complexity check or file size). High-entropy files (frequently changed but complex) are automatically prioritized for the Auditor agent. This turns Sigil from a generic scanner into a 'Hotspot' specialist that finds bugs where they are most likely to live. Implementation: 1. Add `_calculate_entropy()` to discovery.py using `git log --format=oneline -- <file> | wc -l`. 2. Add a `focus_entropy: bool` flag to Config. 3. Adjust the prompt for the Auditor agent in maintenance.py to prioritize these high-entropy paths.

## Rationale

Generic scanners miss the 'why' of a codebase. By targeting high-churn, high-complexity files, Sigil addresses the most volatile and bug-prone areas of a project first, which is how senior engineers actually prioritize their time.

