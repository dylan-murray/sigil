---
title: Agentic MCP Tool Brokering for Infinite Extensibility
summary: Add an 'MCP Tool Brokering' agent that sits between the pipeline and the
  MCP servers. Instead of providing all MCP tools
status: open
complexity: medium
disposition: pr
priority: 5
boldness: balanced
created: '2026-03-29T19:34:15Z'
---

# Agentic MCP Tool Brokering for Infinite Extensibility

## Description

Add an 'MCP Tool Brokering' agent that sits between the pipeline and the MCP servers. Instead of providing all MCP tools to every agent (which wastes context tokens), the pipeline first sends the Task + Tool Descriptions to the Broker. The Broker returns a subset of 'Active Tools' for that specific turn. This is especially critical for 'deferred loading' scenarios. If the Engineer needs to 'talk to Slack' to find a requirement, the Broker enables those tools only for that sub-task. This effectively allows Sigil to support hundreds of MCP tools without blowing the token budget on tool definitions.

## Rationale

As the MCP ecosystem grows, 'tool-definition bloat' will become the primary bottleneck for autonomous agents. Brokering is the industry-standard solution for high-extensibility systems.

