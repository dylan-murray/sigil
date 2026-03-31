---
title: Agentic MCP Tool Brokering for High-Density Toolsets
summary: Introduce 'Agentic MCP Tool Brokering' (ATB) to handle the 'MCP Explosion'
  problem where providing too many tool schemas
status: done
complexity: medium
disposition: pr
priority: 2
boldness: experimental
created: '2026-03-29T19:34:15Z'
---

# Agentic MCP Tool Brokering for High-Density Toolsets

## Description

Introduce 'Agentic MCP Tool Brokering' (ATB) to handle the 'MCP Explosion' problem where providing too many tool schemas dilutes the LLM's attention. Instead of the current static 'deferred' logic, create a specialized 'Broker Agent' that receives the task and the full list of names/descriptions of available MCP tools. The Broker responds with a subset of tools (max 5) that are actually relevant. These specific tool schemas are then injected into the primary agent's context. This allows Sigil to support hundreds of MCP tools (e.g., Slack, Jira, AWS, Local Shell) without hitting context limits or causing model confusion. Change `sigil.core.mcp.prepare_mcp_for_agent` to involve a cheap Haiku call to select the toolset before the main Sonnet/Opus run.

## Rationale

As the MCP ecosystem grows, agents become 'blind' when given 50+ tool schemas. Brokering mimics how humans use documentation—lookup first, then application.

