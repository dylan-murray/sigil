from __future__ import annotations

from typing import Any

import litellm

litellm.suppress_debug_info = True


def complete(
    model: str,
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.0,
    max_tokens: int = 4096,
    **kwargs: Any,
) -> str:
    response = litellm.completion(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        **kwargs,
    )
    return response.choices[0].message.content


def get_context_window(model: str) -> int:
    try:
        info = litellm.get_model_info(model)
        return info.get("max_input_tokens", 0) or info.get("max_tokens", 32_000)
    except Exception:
        return 32_000
