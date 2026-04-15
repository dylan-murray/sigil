"""Universal Semantic Anchor tool for extracting semantic anchors from Python files."""

import ast
import logging
from pathlib import Path
from typing import List, Set

from sigil.core.agent import Tool, ToolResult
from sigil.core.config import SIGIL_DIR
from sigil.core.security import validate_path
from sigil.core.utils import StatusCallback

logger = logging.getLogger(__name__)


class UniversalSemanticAnchorTool:
    """Tool that extracts semantic anchors (functions, classes) from Python files."""

    def __init__(self, repo: Path, on_status: StatusCallback | None = None):
        self.repo = repo.resolve()
        self.on_status = on_status

    def __call__(self, args: dict) -> ToolResult:
        """Execute the USA tool to extract semantic anchors."""
        try:
            anchors = self._extract_anchors()
            self._write_anchors(anchors)
            return ToolResult(
                content=f"Extracted {len(anchors)} semantic anchors and wrote to .sigil/memory/anchors.md"
            )
        except Exception as e:
            logger.exception("Failed to extract semantic anchors")
            return ToolResult(content=f"Error extracting semantic anchors: {e}")

    def _extract_anchors(self) -> List[str]:
        """Extract semantic anchors from all Python files in the repository."""
        anchors: Set[str] = set()

        # Walk the repository and find all Python files
        for py_file in self._find_python_files():
            try:
                file_anchors = self._extract_anchors_from_file(py_file)
                anchors.update(file_anchors)
            except Exception as e:
                logger.warning("Failed to extract anchors from %s: %s", py_file, e)
                continue

        return sorted(anchors)

    def _find_python_files(self) -> List[Path]:
        """Find all Python files in the repository, excluding hidden and ignored directories."""
        python_files = []
        exclude_dirs = {
            ".git",
            ".sigil",
            "__pycache__",
            ".ruff_cache",
            ".pytest_cache",
            "node_modules",
            ".venv",
            "env",
            "build",
            "dist",
        }

        for path in self.repo.rglob("*.py"):
            # Skip files in excluded directories
            if any(part in exclude_dirs for part in path.parts):
                continue
            # Skip files that are outside the repository (shouldn't happen with rglob, but safe)
            try:
                path.resolve().relative_to(self.repo.resolve())
            except ValueError:
                continue
            python_files.append(path)

        return python_files

    def _extract_anchors_from_file(self, file_path: Path) -> Set[str]:
        """Extract semantic anchors from a single Python file."""
        anchors: Set[str] = set()

        try:
            content = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as e:
            logger.warning("Could not read %s: %s", file_path, e)
            return anchors

        try:
            tree = ast.parse(content)
        except SyntaxError as e:
            logger.warning("Could not parse %s: %s", file_path, e)
            return anchors

        # Get the module path relative to repo root
        try:
            relative_path = file_path.relative_to(self.repo)
        except ValueError:
            # File is outside repo (shouldn't happen)
            return anchors

        # Convert path to module notation (remove .py, replace / with .)
        module_parts = list(relative_path.parts[:-1]) + [relative_path.stem]
        # Handle __init__.py files - they represent the package itself
        if module_parts[-1] == "__init__":
            module_parts = module_parts[:-1]
            if not module_parts:  # Root __init__.py
                module_parts = [""]

        module_path = ".".join(part for part in module_parts if part)

        # Extract anchors from AST
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                # Function anchor: module.function_name
                if module_path:
                    anchor = f"{module_path}.{node.name}"
                else:
                    anchor = node.name
                anchors.add(anchor)
            elif isinstance(node, ast.AsyncFunctionDef):
                # Async function anchor
                if module_path:
                    anchor = f"{module_path}.{node.name}"
                else:
                    anchor = node.name
                anchors.add(anchor)
            elif isinstance(node, ast.ClassDef):
                # Class anchor: module.ClassName
                if module_path:
                    anchor = f"{module_path}.{node.name}"
                else:
                    anchor = node.name
                anchors.add(anchor)

        return anchors

    def _write_anchors(self, anchors: List[str]) -> None:
        """Write anchors to .sigil/memory/anchors.md."""
        memory_dir = self.repo / SIGIL_DIR / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)

        anchors_file = memory_dir / "anchors.md"

        # Write in markdown format
        lines = [
            "# Semantic Anchors\n",
            "\n",
            "This file contains stable semantic anchors for the codebase.\n",
            "Anchors are extracted from Python functions and classes using their fully qualified names.\n",
            "\n",
            "## Anchors\n",
        ]

        for anchor in anchors:
            lines.append(f"- `{anchor}`\n")

        lines.append(f"\n*Total: {len(anchors)} anchors*\n")

        anchors_file.write_text("".join(lines), encoding="utf-8")
        logger.info("Wrote %d semantic anchors to %s", len(anchors), anchors_file)


def make_usa_tool(
    repo: Path,
    on_status: StatusCallback | None = None,
) -> Tool:
    """Create the Universal Semantic Anchor tool."""
    usa_tool = UniversalSemanticAnchorTool(repo, on_status)

    return Tool(
        name="universal_semantic_anchor",
        description=(
            "Extract semantic anchors (functions, classes) from Python files in the repository. "
            "Anchors are stored in .sigil/memory/anchors.md and provide stable reference points "
            "that survive refactoring as long as module and symbol names remain unchanged."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
        handler=usa_tool,
    )
