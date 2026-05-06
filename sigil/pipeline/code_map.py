import re
from pathlib import Path

from sigil.core.utils import arun, read_file
from sigil.pipeline.maintenance import Finding
from sigil.state.chronic import WorkItem

_PYTHON_FUNC_RE = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\(", re.MULTILINE)
_CALL_RE = re.compile(r"(\w+)\s*\(")

_BUILTINS_AND_KEYWORDS: frozenset[str] = frozenset(
    {
        "print",
        "len",
        "range",
        "int",
        "str",
        "float",
        "list",
        "dict",
        "set",
        "tuple",
        "bool",
        "type",
        "isinstance",
        "issubclass",
        "hasattr",
        "getattr",
        "setattr",
        "delattr",
        "super",
        "property",
        "staticmethod",
        "classmethod",
        "enumerate",
        "zip",
        "map",
        "filter",
        "sorted",
        "reversed",
        "iter",
        "next",
        "abs",
        "min",
        "max",
        "sum",
        "any",
        "all",
        "open",
        "input",
        "repr",
        "id",
        "hash",
        "dir",
        "vars",
        "help",
        "format",
        "bytes",
        "bytearray",
        "memoryview",
        "complex",
        "round",
        "pow",
        "divmod",
        "hex",
        "oct",
        "bin",
        "ord",
        "chr",
        "ascii",
        "breakpoint",
        "callable",
        "compile",
        "eval",
        "exec",
        "globals",
        "locals",
        "object",
        "frozenset",
        "slice",
        "if",
        "elif",
        "else",
        "for",
        "while",
        "try",
        "except",
        "finally",
        "with",
        "as",
        "and",
        "or",
        "not",
        "in",
        "is",
        "return",
        "yield",
        "raise",
        "assert",
        "del",
        "pass",
        "break",
        "continue",
        "class",
        "def",
        "from",
        "import",
        "lambda",
        "global",
        "nonlocal",
        "async",
        "await",
    }
)

_MAX_CALLERS = 5
_MAX_CALLEES = 5
_MAX_TEST_FILES = 3


def _build_path_marker(file_path: str, label: str) -> str:
    parts = file_path.replace("\\", "/").split("/")
    if len(parts) <= 1:
        return f"{file_path} ← [{label}]"
    dirs = [p + "/" for p in parts[:-1]]
    tree = " → ".join(dirs) + " → " + parts[-1]
    return f"{tree} ← [{label}]"


def _extract_python_functions(content: str) -> list[str]:
    return _PYTHON_FUNC_RE.findall(content)


async def _find_callers(repo: Path, func_names: list[str], source_file: str) -> list[str]:
    seen: set[str] = set()
    results: list[str] = []
    source_stem = Path(source_file).stem
    for name in func_names[:_MAX_CALLERS]:
        rc, stdout, _ = await arun(
            ["git", "grep", "-l", f"{name}(", "--", "*.py"],
            cwd=repo,
            timeout=10,
        )
        if rc != 0:
            continue
        for line in stdout.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            stem = Path(line).stem
            if stem == source_stem:
                continue
            if stem not in seen:
                seen.add(stem)
                results.append(stem)
                if len(results) >= _MAX_CALLERS:
                    return results
    return results


def _find_callees(content: str) -> list[str]:
    seen: set[str] = set()
    results: list[str] = []
    for match in _CALL_RE.finditer(content):
        name = match.group(1)
        if name.startswith("_") or name in _BUILTINS_AND_KEYWORDS:
            continue
        if name not in seen:
            seen.add(name)
            results.append(name)
            if len(results) >= _MAX_CALLEES:
                break
    return results


async def _find_test_files(repo: Path, source_file: str) -> list[str]:
    stem = Path(source_file).stem
    rc, stdout, _ = await arun(["git", "ls-files"], cwd=repo, timeout=10)
    if rc != 0:
        return []
    results: list[str] = []
    for line in stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if "test" in line.lower() and stem in line:
            results.append(line)
            if len(results) >= _MAX_TEST_FILES:
                break
    return results


async def generate_code_map(repo: Path, item: WorkItem) -> str:
    if isinstance(item, Finding):
        file_path = item.file
        label = f"{item.category.upper()}: {item.description.split('.')[0]}"
    else:
        if not item.relevant_files:
            return ""
        file_path = item.relevant_files[0]
        label = item.title

    if not file_path:
        return ""

    full_path = repo / file_path
    content = read_file(full_path)
    if not content and not full_path.exists():
        return ""

    marker = _build_path_marker(file_path, label)
    is_python = file_path.endswith(".py")

    if is_python:
        func_names = _extract_python_functions(content)
        callers = await _find_callers(repo, func_names, file_path)
        callees = _find_callees(content)
    else:
        callers = ["unknown"]
        callees = ["unknown"]

    test_files = await _find_test_files(repo, file_path)

    lines = [marker]
    if is_python:
        callers_str = ", ".join(callers) if callers else "none"
        callees_str = ", ".join(callees) if callees else "none"
    else:
        callers_str = "unknown"
        callees_str = "unknown"
    lines.append(f"  callers: {callers_str}")
    lines.append(f"  callees: {callees_str}")
    lines.append(f"  tests: {', '.join(test_files) if test_files else 'none'}")
    return "\n".join(lines)
