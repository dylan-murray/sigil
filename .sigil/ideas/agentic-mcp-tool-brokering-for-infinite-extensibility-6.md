---
title: Agentic MCP Tool Brokering for Infinite Extensibility
summary: Implement an 'MCP Tool Brokering' agent that dynamically negotiates which
  MCP tools are needed for a task to minimize co
status: open
complexity: medium
disposition: issue
priority: 16
created: '2026-03-29T18:16:01Z'
---

# Agentic MCP Tool Brokering for Infinite Extensibility

## Description

Implement an 'MCP Tool Brokering' agent that dynamically negotiates which MCP tools are needed for a task to minimize context bloat and cost.

Implementation:
1. New agent `broker` in `sigil/core/mcp.py`.
2. Instead of the current 'Deferred Loading' logic (which is rule-based in `core/mcp.py`), the `broker` is a tiny, fast model (Haiku) that sees ONLY the task description and a list of tool NAMES + descriptions.
3. It outputs a subset of tools actually relevant to the task.
4. Only the schemas for these SELECTED tools are injected into the `engineer` or `auditor` prompt.
5. This allows Sigil to support hundreds of MCP tools (e.g., full AWS SDK, Jira, Slack, Docs) without ever hitting context limits or 'confusing' the agent with irrelevant capabilities.

Current logic uses a hard 10-tool limit; this replaces it with an 'Intelligent Broker' that scales to massive toolsets.

## Rationale

The current MCP implementation uses a 'all-or-nothing' or 'manual search' approach. As the MCP ecosystem grows, 'Tool Selection' becomes a bottleneck for both cost and reasoning quality. An agentic broker is the industry-standard solution for large-scale tool use.

