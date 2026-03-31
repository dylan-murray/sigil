---
title: Human-in-the-Loop Style Learning from PR Comments
summary: Add a `fetch_pr_feedback` method to `sigil.integrations.github.GitHubClient`
  that scans the last 5 closed or merged Sigi
status: open
complexity: medium
disposition: pr
priority: 7
boldness: balanced
created: '2026-03-29T19:34:15Z'
---

# Human-in-the-Loop Style Learning from PR Comments

## Description

Add a `fetch_pr_feedback` method to `sigil.integrations.github.GitHubClient` that scans the last 5 closed or merged Sigil PRs for human comments. These comments are then passed to the `memory` agent during `update_working`. Implementation: 1. `GitHubClient` fetches comments from recent Sigil-authored PRs. 2. The `memory` agent identifies 'Negative Constraints' (e.g., "Don't use f-strings in logs", "We prefer composition over inheritance here"). 3. These constraints are saved in `working.md` under a `## Style & Preference Constraints` section. 4. This allows Sigil to 'learn' a team's specific preferences over time without manual config.

## Rationale

The most valuable feedback Sigil gets is from human code reviews. Capturing this feedback and persisting it in working memory allows the agent to stop making the same stylistic 'mistakes' in future PRs.

