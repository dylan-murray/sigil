import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def load_json_safe(path: Path, default: Any = None) -> Any:
    """
    Safely load a JSON file with error handling and logging.

    Returns the parsed JSON content if successful, otherwise returns the default value.
    """
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning(f"JSON file not found: {path}. Returning default: {default}")
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to decode JSON from {path}: {e}. Returning default: {default}")
    except OSError as e:
        logger.warning(f"OS error reading JSON file {path}: {e}. Returning default: {default}")

    return default
