---
title: Pre-Execution Planning Phase (Spec-First Engineering)
summary: Introduce a 'Spec-First' execution mode in `sigil.pipeline.executor`. Before
  the Engineer agent is allowed to use `apply
status: open
complexity: medium
disposition: pr
priority: 3
boldness: experimental
created: '2026-03-31T00:41:14Z'
---

# Pre-Execution Planning Phase (Spec-First Engineering)

## Description

Introduce a 'Spec-First' execution mode in `sigil.pipeline.executor`. Before the Engineer agent is allowed to use `apply_edit` or `create_file`, it must first call a new tool `propose_plan` with a detailed step-by-step implementation plan. This plan is then automatically reviewed by a 'Planner' persona (a separate Agent instance) that checks for architectural consistency and potential side effects. If the plan is approved, the Engineer proceeds; if not, it must refine the plan. This adds a 'think-before-you-code' layer that reduces the number of retries caused by logical errors. Implementation: 1. Add `propose_plan` tool to `ExecutorAgent`. 2. Add a `PlannerAgent` to `sigil.pipeline.executor`. 3. Modify the execution loop to require a successful `propose_plan` call before enabling write tools.

## Rationale

Complex executions currently hit retry limits (as noted in working memory). A planning phase helps catch architectural mistakes before expensive code generation begins.

