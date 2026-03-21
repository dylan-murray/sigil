from typing import Any

import litellm

litellm.suppress_debug_info = True


async def acomplete(
    model: str,
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.0,
    max_tokens: int = 4096,
    **kwargs: Any,
) -> str:
    response = await litellm.acompletion(
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
    except (litellm.exceptions.NotFoundError, litellm.exceptions.BadRequestError, KeyError):
        return 32_000
