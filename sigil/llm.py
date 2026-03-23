import asyncio
import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import litellm
from litellm.exceptions import (
    InternalServerError,
    RateLimitError,
    ServiceUnavailableError,
)

litellm.suppress_debug_info = True

MAX_RETRIES = 3
INITIAL_DELAY = 1.0
BACKOFF_FACTOR = 2.0

log = logging.getLogger(__name__)

INPUT_COST_PER_MTK: dict[str, float] = {
    "anthropic/claude-sonnet-4-6-20250325": 3.00,
    "anthropic/claude-sonnet-4-6": 3.00,
    "anthropic/claude-opus-4-6-20250527": 15.00,
    "anthropic/claude-opus-4-6": 15.00,
    "anthropic/claude-haiku-4-5-20251001": 0.80,
    "anthropic/claude-haiku-4-5": 0.80,
}

OUTPUT_COST_PER_MTK: dict[str, float] = {
    "anthropic/claude-sonnet-4-6-20250325": 15.00,
    "anthropic/claude-sonnet-4-6": 15.00,
    "anthropic/claude-opus-4-6-20250527": 75.00,
    "anthropic/claude-opus-4-6": 75.00,
    "anthropic/claude-haiku-4-5-20251001": 4.00,
    "anthropic/claude-haiku-4-5": 4.00,
}


CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10


def compute_call_cost(
    model: str,
    prompt_tok: int,
    completion_tok: int,
    cache_read_tok: int = 0,
    cache_creation_tok: int = 0,
) -> float:
    input_rate = INPUT_COST_PER_MTK.get(model, 3.00)
    output_rate = OUTPUT_COST_PER_MTK.get(model, 15.00)
    return (
        prompt_tok * input_rate
        + cache_creation_tok * input_rate * CACHE_WRITE_MULTIPLIER
        + cache_read_tok * input_rate * CACHE_READ_MULTIPLIER
        + completion_tok * output_rate
    ) / 1_000_000


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    calls: int = 0
    cost_usd: float = 0.0
    by_model: dict[str, "TokenUsage"] = field(default_factory=dict)

    def record(
        self,
        model: str,
        prompt_tok: int,
        completion_tok: int,
        cache_read_tok: int = 0,
        cache_creation_tok: int = 0,
    ) -> None:
        self.prompt_tokens += prompt_tok
        self.completion_tokens += completion_tok
        self.cache_read_tokens += cache_read_tok
        self.cache_creation_tokens += cache_creation_tok
        self.calls += 1
        call_cost = compute_call_cost(
            model, prompt_tok, completion_tok, cache_read_tok, cache_creation_tok
        )
        self.cost_usd += call_cost

        if model not in self.by_model:
            self.by_model[model] = TokenUsage()
        m = self.by_model[model]
        m.prompt_tokens += prompt_tok
        m.completion_tokens += completion_tok
        m.cache_read_tokens += cache_read_tok
        m.cache_creation_tokens += cache_creation_tok
        m.calls += 1
        m.cost_usd += call_cost


@dataclass
class CallTrace:
    timestamp: str
    label: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    cost_usd: float


_traces: list[CallTrace] = []
_run_started_at: str = ""

_usage = TokenUsage()
_usage_lock = threading.Lock()


def get_usage() -> TokenUsage:
    return _usage


def get_usage_snapshot() -> tuple[int, int, float]:
    with _usage_lock:
        return _usage.calls, _usage.prompt_tokens + _usage.completion_tokens, _usage.cost_usd


def reset_usage() -> None:
    global _usage
    with _usage_lock:
        _usage = TokenUsage()


def reset_traces() -> None:
    global _run_started_at
    _traces.clear()
    _run_started_at = datetime.now(timezone.utc).isoformat()


def get_traces() -> list[CallTrace]:
    return list(_traces)


def _record_trace(
    label: str,
    model: str,
    prompt_tok: int,
    completion_tok: int,
    cache_read_tok: int,
    cache_creation_tok: int,
    cost_usd: float,
) -> None:
    _traces.append(
        CallTrace(
            timestamp=datetime.now(timezone.utc).isoformat(),
            label=label,
            model=model,
            prompt_tokens=prompt_tok,
            completion_tokens=completion_tok,
            cache_read_tokens=cache_read_tok,
            cache_creation_tokens=cache_creation_tok,
            cost_usd=cost_usd,
        )
    )


def write_trace_file(repo_root: Path) -> Path | None:
    if not _traces:
        return None

    traces_dir = repo_root / ".sigil" / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)
    out_path = traces_dir / "last-run.json"

    summary_by_label: dict[str, dict[str, float | int]] = {}
    for t in _traces:
        entry = summary_by_label.setdefault(
            t.label,
            {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0},
        )
        entry["calls"] += 1
        entry["prompt_tokens"] += t.prompt_tokens
        entry["completion_tokens"] += t.completion_tokens
        entry["cost_usd"] += t.cost_usd

    payload = {
        "started_at": _run_started_at,
        "total_cost_usd": sum(t.cost_usd for t in _traces),
        "total_calls": len(_traces),
        "calls": [asdict(t) for t in _traces],
        "summary_by_label": summary_by_label,
    }

    out_path.write_text(json.dumps(payload, indent=2) + "\n")
    return out_path


MODEL_OVERRIDES: dict[str, dict[str, int]] = {
    "anthropic/claude-sonnet-4-6-20250325": {
        "max_input_tokens": 200_000,
        "max_output_tokens": 64_000,
    },
    "anthropic/claude-opus-4-6-20250527": {
        "max_input_tokens": 1_000_000,
        "max_output_tokens": 32_000,
    },
    "anthropic/claude-haiku-4-5-20251001": {
        "max_input_tokens": 200_000,
        "max_output_tokens": 64_000,
    },
}


def _get_model_info(model: str) -> dict:
    try:
        return litellm.get_model_info(model)
    except Exception:
        return {}


def get_context_window(model: str) -> int:
    override = MODEL_OVERRIDES.get(model)
    if override:
        return override["max_input_tokens"]
    info = _get_model_info(model)
    return info.get("max_input_tokens", 0) or info.get("max_tokens", 32_000)


def get_max_output_tokens(model: str) -> int:
    override = MODEL_OVERRIDES.get(model)
    if override:
        return override["max_output_tokens"]
    info = _get_model_info(model)
    return info.get("max_output_tokens", 8_192)


AGENT_OUTPUT_CAPS: dict[str, int] = {
    "analyzer": 16_384,
    "ideator": 8_192,
    "validator": 8_192,
    "reviewer": 8_192,
    "arbiter": 8_192,
    "codegen": 32_768,
}


def get_agent_output_cap(agent: str, model: str) -> int:
    cap = AGENT_OUTPUT_CAPS.get(agent)
    model_max = get_max_output_tokens(model)
    if cap is None:
        return model_max
    return min(cap, model_max)


DOOM_LOOP_THRESHOLD = 3


def detect_doom_loop(messages: list[dict]) -> bool:
    recent_calls: list[tuple[str, str]] = []
    for msg in reversed(messages):
        if isinstance(msg, dict):
            role = msg.get("role", "")
            tool_calls = msg.get("tool_calls")
        else:
            role = getattr(msg, "role", "")
            tool_calls = getattr(msg, "tool_calls", None)
        if role != "assistant" or not tool_calls:
            continue
        for tc in tool_calls:
            if isinstance(tc, dict):
                name = tc.get("function", {}).get("name", "")
                args = tc.get("function", {}).get("arguments", "")
            else:
                fn = getattr(tc, "function", None)
                name = getattr(fn, "name", "") if fn else ""
                args = getattr(fn, "arguments", "") if fn else ""
            recent_calls.append((name, args))
            if len(recent_calls) >= DOOM_LOOP_THRESHOLD:
                break
        if len(recent_calls) >= DOOM_LOOP_THRESHOLD:
            break
    if len(recent_calls) < DOOM_LOOP_THRESHOLD:
        return False
    first = recent_calls[0]
    return all(c == first for c in recent_calls[1:])


class BudgetExceededError(Exception):
    pass


_max_budget: float | None = None


def set_budget(max_cost_usd: float) -> None:
    global _max_budget
    _max_budget = max_cost_usd


def _check_budget() -> None:
    if _max_budget is not None and _usage.cost_usd > _max_budget:
        raise BudgetExceededError(
            f"Run budget exceeded: ${_usage.cost_usd:.2f} > ${_max_budget:.2f} limit"
        )


_RETRYABLE = (InternalServerError, RateLimitError, ServiceUnavailableError)


async def acompletion(*, label: str = "unknown", **kwargs: Any) -> litellm.ModelResponse:
    last_exc: Exception | None = None
    model = kwargs.get("model", "unknown")
    for attempt in range(1 + MAX_RETRIES):
        try:
            response = await litellm.acompletion(**kwargs)
            usage = getattr(response, "usage", None)
            if usage:
                prompt_tok = getattr(usage, "prompt_tokens", 0) or 0
                completion_tok = getattr(usage, "completion_tokens", 0) or 0
                cache_read_tok = getattr(usage, "cache_read_input_tokens", 0) or 0
                cache_creation_tok = getattr(usage, "cache_creation_input_tokens", 0) or 0
                with _usage_lock:
                    _usage.record(
                        model, prompt_tok, completion_tok, cache_read_tok, cache_creation_tok
                    )
                call_cost = compute_call_cost(
                    model, prompt_tok, completion_tok, cache_read_tok, cache_creation_tok
                )
                _record_trace(
                    label,
                    model,
                    prompt_tok,
                    completion_tok,
                    cache_read_tok,
                    cache_creation_tok,
                    call_cost,
                )
                log.debug(
                    "LLM [%s] %s: %d in / %d out / %d cache_read / %d cache_write tokens",
                    label,
                    model,
                    prompt_tok,
                    completion_tok,
                    cache_read_tok,
                    cache_creation_tok,
                )
                _check_budget()
            return response
        except _RETRYABLE as exc:
            last_exc = exc
            if attempt == MAX_RETRIES:
                break
            delay = INITIAL_DELAY * (BACKOFF_FACTOR**attempt)
            log.warning(
                "LLM call failed (attempt %d/%d), retrying in %.1fs: %s",
                attempt + 1,
                MAX_RETRIES + 1,
                delay,
                exc,
            )
            await asyncio.sleep(delay)
    raise last_exc  # type: ignore[misc]


_MASKED_READ = "[file contents omitted — use read_file again if needed]"
_MASKED_MCP = "[tool result omitted — call again if needed]"
_MASKED_SEARCH = "[search results omitted — call search_tools again if needed]"

_KEEP_TOOLS = frozenset({"apply_edit", "create_file", "done"})
_REPORT_TOOLS = frozenset({"report_finding", "report_idea", "review_item", "resolve_item"})

_ERROR_MARKERS = (
    "Error",
    "error",
    "Traceback",
    "not found",
    "Access denied",
    "Invalid",
    "denied",
    "failed",
)


def _build_tool_name_map(messages: list[dict]) -> dict[str, str]:
    name_map: dict[str, str] = {}
    for msg in messages:
        tool_calls = None
        if isinstance(msg, dict):
            tool_calls = msg.get("tool_calls")
        else:
            tool_calls = getattr(msg, "tool_calls", None)
        if not tool_calls:
            continue
        for tc in tool_calls:
            if isinstance(tc, dict):
                tc_id = tc.get("id", "")
                tc_name = tc.get("function", {}).get("name", "")
            else:
                tc_id = getattr(tc, "id", "")
                fn = getattr(tc, "function", None)
                tc_name = getattr(fn, "name", "") if fn else ""
            if tc_id and tc_name:
                name_map[tc_id] = tc_name
    return name_map


def _looks_like_error(content: str) -> bool:
    return any(marker in content for marker in _ERROR_MARKERS)


def mask_old_tool_outputs(messages: list[dict], *, keep_recent: int = 10) -> list[dict]:
    if len(messages) <= keep_recent:
        return messages

    cutoff = len(messages) - keep_recent
    name_map = _build_tool_name_map(messages)

    for i in range(cutoff):
        msg = messages[i]
        if not isinstance(msg, dict):
            continue
        if msg.get("role") != "tool":
            continue

        content = msg.get("content", "")
        if not isinstance(content, str) or len(content) < 200:
            continue

        if _looks_like_error(content):
            continue

        tool_call_id = msg.get("tool_call_id", "")
        tool_name = name_map.get(tool_call_id, "")

        if tool_name in _KEEP_TOOLS or tool_name in _REPORT_TOOLS:
            continue

        if tool_name == "read_file":
            msg["content"] = _MASKED_READ
        elif tool_name == "search_tools":
            msg["content"] = _MASKED_SEARCH
        elif tool_name.startswith("mcp__"):
            msg["content"] = _MASKED_MCP
        elif tool_name == "":
            msg["content"] = _MASKED_MCP

    return messages


COMPACTION_PROMPT = """\
You are a conversation compactor. Summarize the conversation below into a \
concise briefing that preserves all information an AI agent needs to continue \
its work. Include:

1. **Goal**: what the agent is trying to accomplish
2. **Progress**: what has been done so far (tools called, files read/edited, decisions made)
3. **Key findings**: important facts, file paths, code snippets, or data discovered
4. **Next steps**: what the agent should do next based on the conversation trajectory

Be specific — include file paths, function names, line numbers, and exact values. \
Do NOT include raw file contents or tool output verbatim; summarize them instead. \
Keep the summary under 2000 tokens.

<conversation>
{conversation}
</conversation>
"""

DEFAULT_COMPACTION_THRESHOLD = 80_000


def estimate_tokens(messages: list[dict]) -> int:
    total = 0
    for msg in messages:
        if isinstance(msg, dict):
            content = msg.get("content", "")
        else:
            content = getattr(msg, "content", "") or ""
        if isinstance(content, str):
            total += len(content) // 4
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    total += len(block.get("text", "")) // 4
                else:
                    total += len(str(block)) // 4
        tool_calls = (
            msg.get("tool_calls") if isinstance(msg, dict) else getattr(msg, "tool_calls", None)
        )
        if tool_calls:
            for tc in tool_calls:
                if isinstance(tc, dict):
                    args = tc.get("function", {}).get("arguments", "")
                else:
                    fn = getattr(tc, "function", None)
                    args = getattr(fn, "arguments", "") if fn else ""
                total += len(args) // 4
    return total


def _split_at_tool_boundary(messages: list[dict], keep_recent: int) -> int:
    if len(messages) <= keep_recent:
        return len(messages)
    candidate = len(messages) - keep_recent
    while candidate > 0:
        msg = messages[candidate]
        if _is_tool_result(msg):
            candidate -= 1
            continue
        role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", "")
        if role == "assistant":
            tool_calls = (
                msg.get("tool_calls") if isinstance(msg, dict) else getattr(msg, "tool_calls", None)
            )
            if tool_calls:
                candidate -= 1
                continue
        break
    return max(1, candidate)


def _is_tool_result(msg: dict | object) -> bool:
    if isinstance(msg, dict):
        return msg.get("role") == "tool"
    return getattr(msg, "role", "") == "tool"


def _messages_to_text(messages: list[dict]) -> str:
    parts: list[str] = []
    for msg in messages:
        if isinstance(msg, dict):
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
        else:
            role = getattr(msg, "role", "unknown")
            content = getattr(msg, "content", "") or ""
        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict):
                    text_parts.append(block.get("text", ""))
                else:
                    text_parts.append(str(block))
            content = "\n".join(text_parts)
        if content:
            parts.append(f"[{role}] {content[:2000]}")
        tool_calls = (
            msg.get("tool_calls") if isinstance(msg, dict) else getattr(msg, "tool_calls", None)
        )
        if tool_calls:
            for tc in tool_calls:
                if isinstance(tc, dict):
                    name = tc.get("function", {}).get("name", "?")
                    args = tc.get("function", {}).get("arguments", "")
                else:
                    fn = getattr(tc, "function", None)
                    name = getattr(fn, "name", "?") if fn else "?"
                    args = getattr(fn, "arguments", "") if fn else ""
                parts.append(f"[tool_call] {name}({args[:200]})")
    return "\n".join(parts)


async def compact_messages(
    messages: list[dict],
    model: str,
    *,
    threshold_tokens: int = DEFAULT_COMPACTION_THRESHOLD,
    keep_recent: int = 5,
) -> bool:
    if estimate_tokens(messages) < threshold_tokens:
        return False

    split_idx = _split_at_tool_boundary(messages, keep_recent)
    if split_idx <= 1:
        return False

    old_messages = messages[:split_idx]
    conversation_text = _messages_to_text(old_messages)

    prompt = COMPACTION_PROMPT.replace("{conversation}", conversation_text)

    try:
        response = await acompletion(
            label="compaction",
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=2048,
        )
        summary = response.choices[0].message.content or ""
    except Exception as exc:
        log.warning("Compaction failed, skipping: %s", exc)
        return False

    if not summary.strip():
        return False

    summary_msg = {
        "role": "user",
        "content": f"[COMPACTED CONTEXT — summarized from earlier conversation]\n\n{summary}",
    }

    remaining = messages[split_idx:]
    messages.clear()
    messages.append(summary_msg)
    messages.extend(remaining)

    log.info(
        "Compacted %d messages into summary (%d tokens estimated → %d)",
        len(old_messages),
        estimate_tokens(old_messages),
        estimate_tokens(messages),
    )
    return True


CACHEABLE_PREFIXES = ("anthropic/",)


def supports_prompt_caching(model: str) -> bool:
    return any(model.startswith(p) for p in CACHEABLE_PREFIXES)


def cacheable_message(model: str, prompt: str) -> dict:
    if supports_prompt_caching(model):
        return {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        }
    return {"role": "user", "content": prompt}
