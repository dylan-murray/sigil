# Agent Framework — Unified Tool and Agent Abstractions

Sigil uses a custom agent framework defined in `sigil/core/agent.py` to manage LLM interactions. This framework provides structured tool dispatch and conversation management.

## Core Classes
- **`Tool`:** Encapsulates a tool's name, description, JSON schema, and async handler. Handlers return a `ToolResult`. Supports `mutating` and `idempotent` flags.
- **`Agent`:** Manages the LLM loop, including tool calls, system prompt injection, and circuit breakers.
- **`AgentCoordinator`:** Manages multiple agents with persistent histories for complex multi-agent flows (e.g., Architect -> Engineer).

## Agent Features
- **Doom Loop Detection:** Breaks the loop if the agent repeats the same tool call 5 times without progress. On first detection, injects a recovery nudge message; only aborts if the agent repeats the call again after the nudge.
- **Repeated Idempotent Call Short-Circuiting:** If the agent repeats an idempotent tool call (e.g., `read_file`, `grep`, `list_directory`) with identical canonicalized arguments from the previous round, the call is short-circuited with a "Skipped:" result instead of re-executing. This breaks fixation loops. The short-circuit is cleared whenever a mutating call runs.
- **Observation Masking:** Truncates old tool outputs in the context window to save tokens.
- **Context Compaction:** Uses a cheap model to summarize long conversations when they exceed 80k tokens.
- **Truncation Handling:** Automatically requests the agent to continue if a response is cut off by the model's output limit.

## Doom Loop Recovery

When a doom loop is first detected (same tool call repeated `DOOM_LOOP_MAX_REPEATS` times), the agent injects a user nudge message telling the model to stop repeating the call and take a different action. The loop continues. If the model repeats the call again after the nudge, the agent aborts with `doom_loop=True`.

- The nudge index is recomputed each round because compaction rebuilds the message list in place; if the nudge was compacted away, scanning from 0 cannot re-trigger on pre-recovery repeats.
- `detect_doom_loop(messages, start=...)` scans only messages after the nudge once a nudge has been injected.
- Tool call signatures are canonicalized (JSON key order normalized) so key-order jitter still counts as a repeat.

## Idempotent Call Short-Circuiting

Tools marked `idempotent=True` (read-only tools like `read_file`, `grep`, `list_directory`) are tracked across rounds. If the agent issues the same idempotent call (same name + canonicalized args) in consecutive rounds with no intervening mutating call, the call is short-circuited:

- The tool handler is NOT executed.
- A synthetic `ToolResult` with content starting `"Skipped:"` is returned, telling the model the output is already in context.
- The call is still recorded in traces (`record_tool_call` / `record_tool_result`).
- Any mutating call in a round clears the previous-round read set, so reads after a mutation are always re-executed.
- Non-idempotent tools (e.g., stateful `task_progress`) and unknown tools are never short-circuited.
