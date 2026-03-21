import litellm

litellm.suppress_debug_info = True


def get_context_window(model: str) -> int:
    try:
        info = litellm.get_model_info(model)
        return info.get("max_input_tokens", 0) or info.get("max_tokens", 32_000)
    except (litellm.exceptions.NotFoundError, litellm.exceptions.BadRequestError, KeyError):
        return 32_000
