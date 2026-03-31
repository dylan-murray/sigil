---
title: Pre-Execution Planning Phase (Spec-First Engineering)
summary: Introduce a 'Spec-First' execution mode in `sigil.pipeline.executor`. Before
  the Engineer agent is allowed to use `apply
status: open
complexity: medium
disposition: pr
priority: 10
boldness: experimental
created: '2026-03-29T20:19:02Z'
---

# Pre-Execution Planning Phase (Spec-First Engineering)

## Description

Introduce a 'Spec-First' execution mode in `sigil.pipeline.executor`. Before the Engineer agent is allowed to use `apply_edit` or `create_file`, it must first call a `propose_plan` tool that outputs a structured implementation plan (files to change, specific logic updates, and potential side effects). This plan is then reviewed by the QA agent *before* any code is written. If the QA agent rejects the plan, the Engineer must iterate. This mirrors senior engineering workflows where design is decoupled from implementation. Implementation: 1. Add `propose_plan` tool to the Engineer agent. 2. Update the execution loop in `executor.py` to require a successful plan phase before enabling write tools. 3. Pass the plan to the QA agent for a 'pre-flight' check.

## Rationale

Current execution often jumps straight into edits, leading to hallucinations or partial implementations that fail post-hooks. A planning phase reduces 'trial and error' token waste and improves the quality of complex multi-file changes.

