import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def parse_yaml_safe(content: str, default: Any = None) -> Any:
    """Parses a YAML string safely, returning a default value on error."""
    if not content or not content.strip():
        return default
    try:
        return yaml.safe_load(content)
    except yaml.YAMLError as e:
        logger.warning(f"Failed to parse YAML content: {e}")
        return default


def load_yaml_safe(path: Path, default: Any = None) -> Any:
    """Reads a YAML file and parses it safely, returning a default value on error."""
    try:
        content = path.read_text()
        return parse_yaml_safe(content, default=default)
    except (FileNotFoundError, OSError) as e:
        logger.warning(f"Failed to read YAML file at {path}: {e}")
        return default


def dump_yaml(data: Any) -> str:
    """Dumps data to a YAML string."""
    return yaml.dump(data, default_flow_style=False, sort_keys=False).strip()


def load_yaml(path: Path) -> Any:
    """Reads a YAML file and parses it. Raises ValueError on failure."""
    try:
        content = path.read_text()
        return yaml.safe_load(content)
    except (yaml.YAMLError, OSError) as e:
        raise ValueError(f"Invalid YAML in {path}: {e}") from e
