import logging
from pathlib import Path
from typing import Any
from sigil.core.learning import OutcomeTracker

logger = logging.getLogger(__name__)


async def poll_outcomes(client: Any, repo: Path) -> None:
    """
    Polls GitHub for recent Sigil PRs and updates the local outcome store.
    """
    try:
        tracker = OutcomeTracker(repo)
        await tracker.refresh_outcomes(client)
        logger.info("Successfully refreshed PR outcomes from GitHub")
    except Exception as e:
        logger.warning("Failed to poll PR outcomes: %s", e)
