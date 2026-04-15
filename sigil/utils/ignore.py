from pathlib import Path
from typing import Set


class SigilIgnore:
    """
    Handles simplified .sigilignore logic using glob-pattern matching.
    """

    def __init__(self, repo_path: Path):
        self.repo_path = repo_path.resolve()
        self.patterns: Set[str] = set()
        self._load_patterns()

    def _load_patterns(self) -> None:
        ignore_file = self.repo_path / ".sigilignore"
        if not ignore_file.exists():
            return

        try:
            content = ignore_file.read_text()
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                self.patterns.add(line)
        except OSError as e:
            # Log error but don't crash; just result in no patterns loaded
            import logging

            logging.getLogger(__name__).warning("Failed to read .sigilignore: %s", e)

    def is_ignored(self, path: str | Path) -> bool:
        """
        Checks if a relative path matches any of the loaded glob patterns.
        """
        if isinstance(path, Path):
            rel_path = path
        else:
            rel_path = Path(path)

        # Ensure we are working with a relative path for matching
        if rel_path.is_absolute():
            try:
                rel_path = rel_path.relative_to(self.repo_path)
            except ValueError:
                # Path is absolute but not relative to repo root
                return False

        path_str = str(rel_path).replace("\\", "/")

        for pattern in self.patterns:
            # Path.match handles glob patterns.
            # We check both the full relative path and the filename.
            if rel_path.match(pattern) or Path(path_str).match(pattern):
                return True

            # Handle directory-style patterns like 'tmp/'
            if pattern.endswith("/") and any(
                part == pattern.rstrip("/") for part in rel_path.parts
            ):
                return True

        return False
