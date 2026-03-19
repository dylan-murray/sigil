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
    return _strip_fences(response.choices[0].message.content)


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[: text.rfind("```")]
    return text.strip()


def get_context_window(model: str) -> int:
    try:
        info = litellm.get_model_info(model)
        return info.get("max_input_tokens", 0) or info.get("max_tokens", 32_000)
    except Exception:
        return 32_000
