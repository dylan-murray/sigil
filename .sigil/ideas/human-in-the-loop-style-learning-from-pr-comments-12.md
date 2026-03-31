---
title: Human-in-the-Loop Style Learning from PR Comments
summary: Add a `sigil.integrations.github.GitHubClient.fetch_pr_feedback()` method
  that scans the last 5 closed/merged Sigil PRs
status: open
complexity: medium
disposition: pr
priority: 14
boldness: balanced
created: '2026-03-29T19:34:15Z'
---

# Human-in-the-Loop Style Learning from PR Comments

## Description

Add a `sigil.integrations.github.GitHubClient.fetch_pr_feedback()` method that scans the last 5 closed/merged Sigil PRs for human comments. These comments are summarized by the `memory` agent and added to `working.md` as 'Style Preferences' (e.g., 'Prefers list comprehensions over map()', 'Always use double underscores for internal helpers'). These preferences are then injected into the `engineer` and `qa` agent prompts. This allows Sigil to 'learn' the specific coding style and preferences of a team over time without manual configuration.

## Rationale

Every team has unwritten rules. By 'listening' to PR feedback, Sigil transitions from a generic bot to a team member that actually adapts to the local culture.

