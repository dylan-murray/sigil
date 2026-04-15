import logging
from pathlib import Path
import yaml

from sigil.core.config import memory_dir

logger = logging.getLogger(__name__)

VETOES_FILE = "vetoes.yaml"


def load_vetoes(repo: Path) -> dict[str, str]:
    """Load vetoes from .sigil/memory/vetoes.yaml."""
    path = memory_dir(repo) / VETOES_FILE
    if not path.exists():
        return {}
    try:
        content = path.read_text()
        data = yaml.safe_load(content)
        if isinstance(data, dict):
            return data
    except Exception as exc:
        logger.warning("Failed to load vetoes from %s: %s", path, exc)
    return {}


def save_veto(repo: Path, fingerprint: str, reason: str) -> None:
    """Save a single veto to .sigil/memory/vetoes.yaml."""
    vetoes = load_vetoes(repo)
    vetoes[fingerprint] = reason

    path = memory_dir(repo) / VETOES_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.dump(vetoes, default_flow_style=False, sort_keys=False))
    except Exception as exc:
        logger.error("Failed to save veto for %s: %s", fingerprint, exc)
