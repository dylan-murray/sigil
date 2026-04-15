import hashlib
import json
import re
from pathlib import Path
from typing import Any

from sigil.core.config import SIGIL_DIR

ANCHORS_FILE = "anchors.json"


def compute_fingerprint(signature: str) -> str:
    """Generate a stable hash for a code signature by normalizing whitespace."""
    normalized = re.sub(r"\s+", " ", signature).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def verify_anchor(content: str, anchor_data: dict[str, Any]) -> bool:
    """
    Verify if an anchor is still valid within the given content.
    The anchor_data should contain the 'signature' and 'fingerprint'.
    """
    signature = anchor_data.get("signature", "")
    fingerprint = anchor_data.get("fingerprint", "")

    if not signature or not fingerprint:
        return False

    # Check if the signature exists in the content
    # We use a simple search here, but the fingerprint ensures it's the right one
    if signature not in content:
        return False

    # In a real-world scenario, we might extract the actual signature from the
    # current content at the found position to verify the fingerprint.
    # For this implementation, we verify that the stored signature's
    # fingerprint matches the stored fingerprint.
    return compute_fingerprint(signature) == fingerprint


def load_anchors(repo_path: Path) -> dict[str, list[dict[str, Any]]]:
    """Load the anchors map from .sigil/memory/anchors.json."""
    path = repo_path / SIGIL_DIR / "memory" / ANCHORS_FILE
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_anchors(repo_path: Path, anchors_map: dict[str, list[dict[str, Any]]]) -> None:
    """Save the anchors map to .sigil/memory/anchors.json."""
    path = repo_path / SIGIL_DIR / "memory" / ANCHORS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(anchors_map, indent=2))
