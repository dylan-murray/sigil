# Agent Framework — Unified Tool and Agent Abstractions

Sigil uses a custom agent framework defined in `sigil/core/agent.py` to manage LLM interactions. This framework provides structured tool dispatch and conversation management.

## Core Classes
- **`Tool`:** Encapsulates a tool's name, description, JSON schema, and async handler. Handlers return a `ToolResult`.
- **`Agent`:** Manages the LLM loop, including tool calls, system prompt injection, and circuit breakers.
- **`AgentCoordinator`:** Manages multiple agents with persistent histories for complex multi-agent flows (e.g., Architect -> Engineer).

## Agent Features
- **Doom Loop Detection:** Breaks the loop if the agent repeats the same tool call 5 times without progress.
- **Observation Masking:** Truncates old tool outputs in the context window to save tokens.
- **Context Compaction:** Uses a cheap model to summarize long conversations when they exceed 80k tokens.
- **Truncation Handling:** Automatically requests the agent to continue if a response is cut off by the model's output limit.
- **Tool Call Handling:** The agent loop correctly continues when the LLM returns `finish_reason="stop"` but includes tool calls; it only exits when there are no tool calls or when truncation occurs. This prevents premature termination when the model signals stop after producing tool calls.
