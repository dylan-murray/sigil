import ast
import logging
from fnmatch import fnmatch
from pathlib import Path

from sigil.pipeline.models import Finding

logger = logging.getLogger(__name__)


def _is_ignored(rel_path: str, patterns: list[str]) -> bool:
    return any(fnmatch(rel_path, p) for p in patterns)


def _contains_any(node: ast.expr) -> bool:
    if isinstance(node, ast.Name) and node.id == "Any":
        return True
    if isinstance(node, ast.Attribute) and node.attr == "Any":
        return True
    if isinstance(node, ast.Subscript):
        return _contains_any(node.slice) or _contains_any(node.value)
    if isinstance(node, ast.Tuple):
        return any(_contains_any(elt) for elt in node.elts)
    if isinstance(node, ast.BinOp):
        return _contains_any(node.left) or _contains_any(node.right)
    return False


def _scan_file(rel_path: str, source: str, boldness: str) -> list[Finding]:
    try:
        tree = ast.parse(source, filename=rel_path)
    except SyntaxError:
        logger.warning("Skipping %s: syntax error", rel_path)
        return []

    findings: list[Finding] = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            is_public = not node.name.startswith("_")

            if is_public and node.returns is None:
                findings.append(
                    Finding(
                        category="types",
                        file=rel_path,
                        line=node.lineno,
                        description=f"Public function '{node.name}' missing return type annotation",
                        risk="low",
                        suggested_fix=f"Add return type annotation to '{node.name}'",
                        disposition="pr",
                        priority=50,
                        rationale="Missing return type on public function reduces type safety",
                        boldness=boldness,
                    )
                )

            all_args = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
            for arg in all_args:
                if arg.arg in ("self", "cls"):
                    continue
                if arg.annotation is None:
                    findings.append(
                        Finding(
                            category="types",
                            file=rel_path,
                            line=arg.lineno,
                            description=f"Argument '{arg.arg}' in '{node.name}' missing type annotation",
                            risk="low",
                            suggested_fix=f"Add type annotation to parameter '{arg.arg}'",
                            disposition="pr",
                            priority=50,
                            rationale="Untyped parameter reduces type safety",
                            boldness=boldness,
                        )
                    )
                elif _contains_any(arg.annotation):
                    findings.append(
                        Finding(
                            category="types",
                            file=rel_path,
                            line=arg.lineno,
                            description=f"Argument '{arg.arg}' in '{node.name}' uses typing.Any",
                            risk="medium",
                            suggested_fix=f"Replace Any with a more specific type for parameter '{arg.arg}'",
                            disposition="pr",
                            priority=40,
                            rationale="typing.Any disables type checking for this parameter",
                            boldness=boldness,
                        )
                    )

            if node.returns is not None and _contains_any(node.returns):
                findings.append(
                    Finding(
                        category="types",
                        file=rel_path,
                        line=node.lineno,
                        description=f"Return type of '{node.name}' uses typing.Any",
                        risk="medium",
                        suggested_fix=f"Replace Any with a more specific return type for '{node.name}'",
                        disposition="pr",
                        priority=40,
                        rationale="typing.Any in return type disables type checking",
                        boldness=boldness,
                    )
                )

        elif isinstance(node, ast.ExceptHandler) and node.type is None:
            findings.append(
                Finding(
                    category="security",
                    file=rel_path,
                    line=node.lineno,
                    description="Bare except clause catches all exceptions including SystemExit and KeyboardInterrupt",
                    risk="high",
                    suggested_fix="Catch a specific exception class, or use 'except Exception:' instead of bare 'except:'",
                    disposition="pr",
                    priority=30,
                    rationale="Bare except can mask bugs and prevent graceful shutdown",
                    boldness=boldness,
                )
            )

    return findings


def ast_type_safety_scan(
    repo: Path, ignore: list[str], boldness: str = "balanced"
) -> list[Finding]:
    findings: list[Finding] = []
    for py_file in repo.rglob("*.py"):
        rel_path = str(py_file.relative_to(repo))
        if _is_ignored(rel_path, ignore):
            continue
        try:
            source = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("Skipping %s: %s", rel_path, exc)
            continue
        findings.extend(_scan_file(rel_path, source, boldness))
    return findings
