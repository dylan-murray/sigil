import asyncio
import logging
import threading
from dataclasses import dataclass, field
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
        input_rate = INPUT_COST_PER_MTK.get(model, 3.00)
        output_rate = OUTPUT_COST_PER_MTK.get(model, 15.00)
        call_cost = (
            prompt_tok * input_rate
            + cache_creation_tok * input_rate * CACHE_WRITE_MULTIPLIER
            + cache_read_tok * input_rate * CACHE_READ_MULTIPLIER
            + completion_tok * output_rate
        ) / 1_000_000
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


_RETRYABLE = (InternalServerError, RateLimitError, ServiceUnavailableError)


async def acompletion(**kwargs: Any) -> litellm.ModelResponse:
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
                log.debug(
                    "LLM %s: %d in / %d out / %d cache_read / %d cache_write tokens",
                    model,
                    prompt_tok,
                    completion_tok,
                    cache_read_tok,
                    cache_creation_tok,
                )
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
