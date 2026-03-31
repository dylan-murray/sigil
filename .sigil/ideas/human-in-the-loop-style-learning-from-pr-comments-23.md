---
title: Human-in-the-Loop Style Learning from PR Comments
summary: Add a `fetch_pr_feedback` method to `GitHubClient` that scans the last 10
  closed or merged Sigil PRs for human comments.
status: open
complexity: medium
disposition: issue
priority: 4
boldness: experimental
created: '2026-03-31T00:41:14Z'
---

# Human-in-the-Loop Style Learning from PR Comments

## Description

Add a `fetch_pr_feedback` method to `GitHubClient` that scans the last 10 closed or merged Sigil PRs for human comments.

Implementation:
1. Fetch PRs created by the Sigil user.
2. Extract comments from maintainers (e.g., 'Please don't use library X', 'We prefer Y here').
3. The `memory` agent processes these comments into a 'Maintainer Preferences' section in `working.md`.
4. These preferences are injected into future Validation and Execution prompts.
5. This creates a true reinforcement learning loop where Sigil gets better by listening to the feedback it receives on its own PRs.

## Rationale

Currently, if a human corrects a Sigil PR, Sigil might make the same mistake in the next run. This feature allows Sigil to learn from human review, just like a junior dev.

