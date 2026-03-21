import asyncio
import logging
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
    for attempt in range(1 + MAX_RETRIES):
        try:
            return await litellm.acompletion(**kwargs)
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
