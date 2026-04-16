import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Set, Dict, List


@dataclass(frozen=True)
class DeadCodeCandidate:
    file: Path
    name: str
    type: str  # "function", "class", "import"
    line: int


class DefinitionVisitor(ast.NodeVisitor):
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.definitions: List[tuple[str, str, int]] = []  # name, type, line
        self.imports: Dict[str, int] = {}  # name -> line
        self.entry_points: Set[str] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef):
        # Check for @app.command()
        is_command = any(
            isinstance(dec, ast.Call)
            and isinstance(dec.func, ast.Attribute)
            and dec.func.attr == "command"
            for dec in node.decorator_list
        )

        # Check for CLI entry points
        is_cli_entry = "sigil/cli.py" in str(self.file_path) and node.name in ("main", "_run")

        # Check for test functions
        is_test = "tests/" in str(self.file_path) and node.name.startswith("test_")

        if is_command or is_cli_entry or is_test:
            self.entry_points.add(node.name)

        self.definitions.append((node.name, "function", node.lineno))
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        self.definitions.append((node.name, "class", node.lineno))
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            name = alias.asname or alias.name
            self.imports[name] = node.lineno
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        for alias in node.names:
            if alias.name == "*":
                continue
            name = alias.asname or alias.name
            self.imports[name] = node.lineno
        self.generic_visit(node)


class UsageVisitor(ast.NodeVisitor):
    def __init__(self):
        self.usages: Set[str] = set()

    def visit_Name(self, node: ast.Name):
        if isinstance(node.ctx, ast.Load):
            self.usages.add(node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        self.usages.add(node.attr)
        self.generic_visit(node)


def find_dead_code(repo: Path) -> List[DeadCodeCandidate]:
    all_definitions: Dict[str, List[DeadCodeCandidate]] = {}
    all_usages: Set[str] = set()
    file_imports: Dict[Path, Dict[str, int]] = {}
    file_usages: Dict[Path, Set[str]] = {}

    python_files = list(repo.rglob("*.py"))

    # First pass: Collect definitions and imports
    for path in python_files:
        try:
            content = path.read_text(encoding="utf-8")
            tree = ast.parse(content)
            visitor = DefinitionVisitor(path)
            visitor.visit(tree)

            for name, dtype, line in visitor.definitions:
                candidate = DeadCodeCandidate(path, name, dtype, line)
                all_definitions.setdefault(name, []).append(candidate)
                if name in visitor.entry_points:
                    all_usages.add(name)

            file_imports[path] = visitor.imports
        except (SyntaxError, UnicodeDecodeError):
            continue

    # Second pass: Collect usages
    for path in python_files:
        try:
            content = path.read_text(encoding="utf-8")
            tree = ast.parse(content)
            visitor = UsageVisitor()
            visitor.visit(tree)

            all_usages.update(visitor.usages)
            file_usages[path] = visitor.usages
        except (SyntaxError, UnicodeDecodeError):
            continue

    candidates: List[DeadCodeCandidate] = []

    # Check top-level definitions
    for name, candidates_list in all_definitions.items():
        if name not in all_usages:
            candidates.extend(candidates_list)

    # Check unused imports per file
    for path, imports in file_imports.items():
        usages = file_usages.get(path, set())
        for name, line in imports.items():
            if name not in usages:
                candidates.append(DeadCodeCandidate(path, name, "import", line))

    return candidates
