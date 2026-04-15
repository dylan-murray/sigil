"""Behavioral contract checking via AST-level diffing."""

from __future__ import annotations

import ast
import hashlib
import subprocess
from pathlib import Path
from typing import Tuple

from sigil.pipeline.models import FileTracker


def _normalize_node(node: ast.AST) -> str:
    """Normalize an AST node for behavioral fingerprinting.

    Removes docstrings and dumps the AST without positional attributes.
    """
    # Remove docstring from FunctionDef and ClassDef bodies
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            # Remove the docstring (first statement if it's a string constant)
            node.body = node.body[1:]

    # Dump without attributes (line numbers, col offsets, etc.)
    return ast.dump(node, include_attributes=False)


def _compute_fingerprint(tree: ast.AST) -> dict[str, str]:
    """Compute behavioral fingerprints for all top-level functions and classes.

    Returns a mapping from qualified name to fingerprint hash.
    """
    fingerprints = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            # Normalize the node
            normalized = _normalize_node(node)
            # Compute SHA256 hash of the normalized AST dump
            fingerprint = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
            fingerprints[node.name] = fingerprint
    return fingerprints


def _get_file_content_at_commit(
    repo_path: Path, file_path: Path, commit: str = "HEAD"
) -> str | None:
    """Get file content from a specific commit using git show.

    Returns None if the file doesn't exist at that commit or on error.
    """
    try:
        # Use git show to get file content at commit
        result = subprocess.run(
            ["git", "show", f"{commit}:{file_path}"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def check_behavioral_contract(repo: Path, tracker: FileTracker) -> Tuple[bool, str]:
    """Check if behavioral contracts are preserved for modified files.

    Args:
        repo: Path to the git repository
        tracker: FileTracker containing information about modified files

    Returns:
        Tuple of (success, error_message) where success is True if all
        behavioral contracts are preserved, False otherwise.
    """
    violations = []

    for file_path in tracker.modified_files:
        full_path = repo / file_path

        # Skip if file doesn't exist in working tree (shouldn't happen for modified files)
        if not full_path.exists():
            continue

        # Get original content from HEAD
        original_content = _get_file_content_at_commit(repo, file_path)
        if original_content is None:
            # File is new (doesn't exist in HEAD) - no contract to violate
            continue

        # Get new content from working tree
        try:
            new_content = full_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # Skip unreadable files
            continue

        # Parse both versions
        try:
            original_tree = ast.parse(original_content)
        except SyntaxError:
            # Skip files with syntax errors in original version
            continue

        try:
            new_tree = ast.parse(new_content)
        except SyntaxError:
            # Skip files with syntax errors in new version
            continue

        # Compute fingerprints
        original_fps = _compute_fingerprint(original_tree)
        new_fps = _compute_fingerprint(new_tree)

        # Check for contract violations
        for name, orig_fp in original_fps.items():
            if name not in new_fps:
                violations.append(f"Function/class '{name}' removed in {file_path}")
            elif new_fps[name] != orig_fp:
                violations.append(f"Behavioral contract changed for '{name}' in {file_path}")

        # Check for new functions/classes (not considered violations)
        # New functions/classes don't violate existing contracts

    if violations:
        return False, "Behavioral contract violations detected:\n" + "\n".join(violations)
    return True, ""
