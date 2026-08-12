import logging

import litellm

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"


async def get_embedding(text: str, model: str | None = None) -> list[float]:
    """
    Generate an embedding for the given text using LiteLLM.
    """
    model = model or DEFAULT_EMBEDDING_MODEL
    try:
        response = await litellm.embedding(
            model=model,
            input=[text],
        )
        # litellm.embedding returns a list of embeddings for the inputs
        return response.data[0]["embedding"]
    except Exception as exc:
        logger.error("Failed to generate embedding with model %s: %s", model, exc)
        raise


async def get_embeddings(texts: list[str], model: str | None = None) -> list[list[float]]:
    """
    Generate embeddings for a list of texts.
    """
    model = model or DEFAULT_EMBEDDING_MODEL
    try:
        response = await litellm.embedding(
            model=model,
            input=texts,
        )
        return [item["embedding"] for item in response.data]
    except Exception as exc:
        logger.error("Failed to generate embeddings with model %s: %s", model, exc)
        raise


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """
    Compute the cosine similarity between two vectors.
    """
    import math

    dot_product = sum(a * b for a, b in zip(v1, v2))
    norm_a = math.sqrt(sum(a * a for a in v1))
    norm_b = math.sqrt(sum(b * b for b in v2))

    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot_product / (norm_a * norm_b)
