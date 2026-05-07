import ast
import logging
from fnmatch import fnmatch
from pathlib import Path

from sigil.core.utils import StatusCallback
from sigil.pipeline.models import Finding

logger = logging.getLogger(__name__)

_REQUESTS_METHODS = frozenset({"get", "post", "put", "delete", "patch", "head", "options"})


def scan_async_patterns(
    repo: Path,
    ignore: list[str],
    *,
    on_status: StatusCallback | None = None,
) -> list[Finding]:
    findings: list[Finding] = []
    py_files = _collect_python_files(repo, ignore)
    if on_status:
        on_status(f"Scanning {len(py_files)} files for async anti-patterns...")

    for filepath in py_files:
        rel = str(filepath.relative_to(repo))
        try:
            source = filepath.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        try:
            tree = ast.parse(source, filename=rel)
        except SyntaxError:
            logger.warning("Skipping %s: syntax error", rel)
            continue

        async_func_names = _collect_async_names(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                file_findings = _check_async_function(node, source, rel, async_func_names)
                findings.extend(file_findings)

    findings.sort(key=lambda f: f.priority)
    return findings


def _collect_python_files(repo: Path, ignore: list[str]) -> list[Path]:
    files: list[Path] = []
    for root, dirs, filenames in _walk(repo, ignore):
        for name in filenames:
            if not name.endswith(".py"):
                continue
            rel_root = str(root.relative_to(repo))
            rel_path = f"{rel_root}/{name}" if rel_root != "." else name
            if _is_ignored(rel_path, ignore):
                continue
            files.append(root / name)
    return files


def _walk(repo: Path, ignore: list[str]):
    skip_dirs: set[str] = {
        "__pycache__",
        ".venv",
        "venv",
        "env",
        ".git",
        ".sigil",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        "node_modules",
        "dist",
        "build",
    }
    for root, dirs, filenames in repo.walk():
        rel_root = str(root.relative_to(repo))
        filtered: list[str] = []
        for d in dirs:
            if d in skip_dirs:
                continue
            rel_dir = f"{rel_root}/{d}" if rel_root != "." else d
            if _is_ignored(f"{rel_dir}/_", ignore):
                continue
            filtered.append(d)
        dirs[:] = filtered
        yield root, dirs, filenames


def _is_ignored(path: str, patterns: list[str]) -> bool:
    return any(fnmatch(path, p) for p in patterns)


def _collect_async_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            names.add(node.name)
    return names


def _walk_skip_nested_async(node: ast.AST):
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.AsyncFunctionDef):
            continue
        yield child
        yield from _walk_skip_nested_async(child)


def _check_async_function(
    node: ast.AsyncFunctionDef,
    source: str,
    filepath: str,
    async_func_names: set[str],
) -> list[Finding]:
    findings: list[Finding] = []
    imports_time = _imports_time(source)
    imports_sleep_direct = _imports_sleep_direct(source)
    imports_requests = _imports_requests(source)

    for child in _walk_skip_nested_async(node):
        if isinstance(child, ast.Call):
            if _is_time_sleep(child, imports_time, imports_sleep_direct):
                findings.append(
                    Finding(
                        category="async_anti_pattern",
                        file=filepath,
                        line=child.lineno,
                        description=f"time.sleep() in async function '{node.name}'",
                        risk="medium",
                        suggested_fix="Replace with asyncio.sleep()",
                        disposition="pr",
                        priority=10,
                        rationale="time.sleep() blocks the event loop in async code",
                    )
                )

            if _is_sync_file_io(child):
                findings.append(
                    Finding(
                        category="async_anti_pattern",
                        file=filepath,
                        line=child.lineno,
                        description=f"Synchronous file I/O (open()) in async function '{node.name}'",
                        risk="medium",
                        suggested_fix="Use aiofiles or asyncio.to_thread()",
                        disposition="issue",
                        priority=20,
                        rationale="Synchronous file I/O blocks the event loop in async code",
                    )
                )

            if _is_requests_call(child, imports_requests):
                attr = _get_requests_attr(child)
                findings.append(
                    Finding(
                        category="async_anti_pattern",
                        file=filepath,
                        line=child.lineno,
                        description=f"requests.{attr}() in async function '{node.name}'",
                        risk="medium",
                        suggested_fix="Use httpx or aiohttp for async HTTP",
                        disposition="issue",
                        priority=30,
                        rationale="requests library is synchronous and blocks the event loop",
                    )
                )

        if isinstance(child, ast.Expr) and isinstance(child.value, ast.Call):
            if _is_unawaited_coroutine(child.value, async_func_names):
                func_name = _get_call_name(child.value)
                findings.append(
                    Finding(
                        category="async_anti_pattern",
                        file=filepath,
                        line=child.lineno,
                        description=f"Missing await on coroutine '{func_name}' in async function '{node.name}'",
                        risk="high",
                        suggested_fix="Add await keyword",
                        disposition="pr",
                        priority=5,
                        rationale="Unawaited coroutine silently does nothing",
                    )
                )

    if _has_sequential_await_loop(node, async_func_names, skip_nested=True):
        findings.append(
            Finding(
                category="async_anti_pattern",
                file=filepath,
                line=node.lineno,
                description=f"Sequential await in loop in async function '{node.name}'",
                risk="low",
                suggested_fix="Use asyncio.gather() for concurrent execution",
                disposition="issue",
                priority=40,
                rationale="Sequential awaits in a loop can be parallelized with asyncio.gather()",
            )
        )

    return findings


def _imports_time(source: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "time":
                    return True
        if isinstance(node, ast.ImportFrom):
            if node.module == "time":
                return True
    return False


def _imports_sleep_direct(source: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "time":
            for alias in node.names:
                if alias.name == "sleep":
                    return True
    return False


def _imports_requests(source: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "requests":
                    return True
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("requests"):
                return True
    return False


def _is_time_sleep(call: ast.Call, imports_time: bool, imports_sleep_direct: bool) -> bool:
    func = call.func
    if isinstance(func, ast.Attribute):
        if isinstance(func.value, ast.Name) and func.value.id == "time" and func.attr == "sleep":
            return True
    if isinstance(func, ast.Name) and func.id == "sleep" and imports_sleep_direct:
        return True
    if isinstance(func, ast.Name) and func.id == "sleep" and imports_time:
        return True
    return False


def _is_sync_file_io(call: ast.Call) -> bool:
    func = call.func
    if isinstance(func, ast.Name) and func.id == "open":
        return True
    return False


def _is_requests_call(call: ast.Call, imports_requests: bool) -> bool:
    if not imports_requests:
        return False
    func = call.func
    if isinstance(func, ast.Attribute):
        if isinstance(func.value, ast.Name) and func.value.id == "requests":
            if func.attr in _REQUESTS_METHODS:
                return True
    return False


def _get_requests_attr(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return "request"


def _is_unawaited_coroutine(call: ast.Call, async_func_names: set[str]) -> bool:
    func = call.func
    if isinstance(func, ast.Name) and func.id in async_func_names:
        return True
    return False


def _get_call_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return "<unknown>"


def _has_sequential_await_loop(
    node: ast.AsyncFunctionDef,
    async_func_names: set[str],
    *,
    skip_nested: bool = False,
) -> bool:
    walker = _walk_skip_nested_async(node) if skip_nested else ast.walk(node)
    for child in walker:
        if not isinstance(child, (ast.For, ast.While)):
            continue
        if child is node:
            continue
        has_await = False
        for body_node in ast.walk(child):
            if isinstance(body_node, ast.Await):
                has_await = True
                break
            if isinstance(body_node, ast.Call):
                if _is_unawaited_coroutine(body_node, async_func_names):
                    has_await = True
                    break
        if has_await:
            return True
    return False
