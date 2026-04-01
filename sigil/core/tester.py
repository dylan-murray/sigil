from pathlib import Path

from sigil.core.utils import arun


async def get_relevant_tests(repo_path: Path, modified_files: set[str]) -> list[str]:
    tests: list[str] = []
    seen: set[str] = set()
    tests_dir = repo_path / "tests"
    if not tests_dir.exists():
        return []
    for file in sorted(modified_files):
        if file.startswith("tests/"):
            if file not in seen:
                tests.append(file)
                seen.add(file)
            continue
        module = _module_name(file)
        if not module:
            continue
        rc, stdout, _ = await arun(["grep", "-rlE", module, "tests"], cwd=repo_path, timeout=30)
        if rc != 0:
            continue
        for match in stdout.splitlines():
            match = match.strip()
            if not match or match in seen:
                continue
            tests.append(match)
            seen.add(match)
    return tests


def _module_name(file: str) -> str:
    path = Path(file)
    if path.suffix != ".py":
        return ""
    parts = list(path.with_suffix("").parts)
    if not parts:
        return ""
    return ".".join(parts)
