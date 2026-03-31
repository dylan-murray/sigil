from pathlib import Path

from sigil.core.config import Config
from sigil.core.utils import StatusCallback
from sigil.pipeline.knowledge import compact_knowledge


async def sync_knowledge_after_merge(
    repo: Path,
    config: Config,
    discovery_context: str,
    *,
    on_status: StatusCallback | None = None,
) -> str:
    compact_model = config.model_for("compactor")
    return await compact_knowledge(
        repo,
        compact_model,
        discovery_context,
        force_full=False,
        on_status=on_status,
    )
