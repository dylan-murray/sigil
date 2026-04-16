import ast
from pathlib import Path
from pydantic import BaseModel, Field


class MissingTypeHint(BaseModel):
    file: str
    line: int
    function_name: str
    missing_element: str  # e.g., "argument: x" or "return type"


class UnsafeTypeUsage(BaseModel):
    file: str
    line: int
    context: str  # e.g., "argument: x" or "return type"


class TypeCoverageReport(BaseModel):
    total_functions: int = 0
    covered_functions: int = 0
    coverage_percentage: float = 0.0
    missing_hints: list[MissingTypeHint] = Field(default_factory=list)
    unsafe_types: list[UnsafeTypeUsage] = Field(default_factory=list)


class TypeVisitor(ast.NodeVisitor):
    def __init__(self, filename: str):
        self.filename = filename
        self.missing_hints: list[MissingTypeHint] = []
        self.unsafe_types: list[UnsafeTypeUsage] = []
        self.total_functions = 0
        self.covered_functions = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._analyze_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._analyze_function(node)
        self.generic_visit(node)

    def _analyze_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.total_functions += 1
        is_covered = True

        # Check arguments
        for arg in node.args.args:
            if arg.arg == "self" or arg.arg == "cls":
                continue

            if arg.annotation is None:
                self.missing_hints.append(
                    MissingTypeHint(
                        file=self.filename,
                        line=node.lineno,
                        function_name=node.name,
                        missing_element=f"argument '{arg.arg}'",
                    )
                )
                is_covered = False
            else:
                self._check_for_any(arg.annotation, node.lineno, f"argument '{arg.arg}'")

        # Check return type
        # Skip __init__ as it's implicitly None and often not annotated
        if node.name != "__init__":
            if node.returns is None:
                self.missing_hints.append(
                    MissingTypeHint(
                        file=self.filename,
                        line=node.lineno,
                        function_name=node.name,
                        missing_element="return type",
                    )
                )
                is_covered = False
            else:
                self._check_for_any(node.returns, node.lineno, "return type")

        if is_covered:
            self.covered_functions += 1

    def _check_for_any(self, node: ast.AST, line: int, context: str) -> None:
        # We look for the name 'Any' in the annotation
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and child.id == "Any":
                self.unsafe_types.append(
                    UnsafeTypeUsage(file=self.filename, line=line, context=context)
                )


def analyze_type_coverage(repo: Path) -> TypeCoverageReport:
    report = TypeCoverageReport()
    all_py_files = list(repo.rglob("*.py"))

    total_funcs = 0
    covered_funcs = 0
    all_missing = []
    all_unsafe = []

    for py_file in all_py_files:
        try:
            content = py_file.read_text(encoding="utf-8")
            tree = ast.parse(content)
            visitor = TypeVisitor(str(py_file))
            visitor.visit(tree)

            total_funcs += visitor.total_functions
            covered_funcs += visitor.covered_functions
            all_missing.extend(visitor.missing_hints)
            all_unsafe.extend(visitor.unsafe_types)
        except (SyntaxError, UnicodeDecodeError):
            continue

    report.total_functions = total_funcs
    report.covered_functions = covered_funcs
    report.missing_hints = all_missing
    report.unsafe_types = all_unsafe

    if total_funcs > 0:
        report.coverage_percentage = (covered_funcs / total_funcs) * 100
    else:
        report.coverage_percentage = 100.0

    return report
