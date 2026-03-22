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


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    cost_usd: float = 0.0
    by_model: dict[str, "TokenUsage"] = field(default_factory=dict)

    def record(self, model: str, prompt_tok: int, completion_tok: int) -> None:
        self.prompt_tokens += prompt_tok
        self.completion_tokens += completion_tok
        self.calls += 1
        input_rate = INPUT_COST_PER_MTK.get(model, 3.00)
        output_rate = OUTPUT_COST_PER_MTK.get(model, 15.00)
        call_cost = (prompt_tok * input_rate + completion_tok * output_rate) / 1_000_000
        self.cost_usd += call_cost

        if model not in self.by_model:
            self.by_model[model] = TokenUsage()
        m = self.by_model[model]
        m.prompt_tokens += prompt_tok
        m.completion_tokens += completion_tok
        m.calls += 1
        m.cost_usd += call_cost


_usage = TokenUsage()
_usage_lock = threading.Lock()


def get_usage() -> TokenUsage:
    return _usage


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
                with _usage_lock:
                    _usage.record(model, prompt_tok, completion_tok)
                log.debug(
                    "LLM %s: %d in / %d out tokens",
                    model,
                    prompt_tok,
                    completion_tok,
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
