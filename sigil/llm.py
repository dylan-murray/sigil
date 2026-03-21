import litellm

litellm.suppress_debug_info = True

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
