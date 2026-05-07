import asyncio
import json
import re
import tomllib
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path

from sigil.core.llm import CHARS_PER_TOKEN, get_context_window
from sigil.core.utils import StatusCallback, arun, read_truncated

MAX_FILE_LIST = 500

BINARY_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".svg",
    ".webp",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".otf",
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".xz",
    ".7z",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".pyc",
    ".pyo",
    ".so",
    ".dylib",
    ".dll",
    ".exe",
    ".bin",
    ".dat",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".lock",
    ".map",
}

SKIP_DIRS = {
    "node_modules",
    "vendor",
    "dist",
    "build",
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "target",
    ".next",
    ".nuxt",
    "coverage",
    ".eggs",
    "egg-info",
}

ALREADY_READ_FILENAMES = {
    "README.md",
    "CLAUDE.md",
    "AGENTS.md",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "Gemfile",
    "pom.xml",
    "build.gradle",
    "mix.exs",
    "setup.py",
    "requirements.txt",
    "setup.cfg",
}

LANGUAGE_MARKERS = {
    "pyproject.toml": "python",
    "setup.py": "python",
    "requirements.txt": "python",
    "package.json": "javascript",
    "tsconfig.json": "typescript",
    "Cargo.toml": "rust",
    "go.mod": "go",
    "Gemfile": "ruby",
    "pom.xml": "java",
    "build.gradle": "java",
    "mix.exs": "elixir",
}

CI_MARKERS = {
    ".github/workflows": "github_actions",
    ".circleci": "circleci",
    ".gitlab-ci.yml": "gitlab",
    "Jenkinsfile": "jenkins",
    ".travis.yml": "travis",
}

PROMPT_OVERHEAD_TOKENS = 8_000
RESPONSE_RESERVE_TOKENS = 4_000

MAJOR_PYTHON_DEPS = {
    "fastapi",
    "flask",
    "django",
    "pydantic",
    "sqlalchemy",
    "celery",
    "requests",
    "httpx",
    "litellm",
    "typer",
    "click",
    "rich",
    "pytest",
    "numpy",
    "pandas",
    "scipy",
    "pillow",
    "torch",
    "tensorflow",
    "scikit-learn",
    "matplotlib",
}

MAJOR_NODE_DEPS = {
    "express",
    "next",
    "react",
    "vue",
    "typescript",
    "webpack",
    "vite",
    "eslint",
    "prettier",
    "jest",
    "mocha",
    "tailwindcss",
    "prisma",
    "axios",
    "lodash",
    "zod",
}


def _detect_language(repo: Path) -> str:
    for marker, lang in LANGUAGE_MARKERS.items():
        if (repo / marker).exists():
            return lang
    return "unknown"


def _normalize_dep_version(version: str) -> str:
    version = version.strip()
    version = re.sub(r"^[~>=<!=]+", "", version)
    version = re.sub(r"\s.*", "", version)
    if not version:
        return ""
    parts = version.split(".")
    if len(parts) >= 2:
        return f"~{parts[0]}.{parts[1]}"
    return f"~{version}"


def _detect_runtime_info(repo: Path) -> dict[str, str]:
    info: dict[str, str] = {}

    pyproject = repo / "pyproject.toml"
    if pyproject.exists():
        try:
            with open(pyproject, "rb") as f:
                data = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError):
            data = {}
        project = data.get("project", {})
        requires_python = project.get("requires-python", "")
        if requires_python:
            info["Python"] = requires_python
        deps = project.get("dependencies", [])
        for dep in deps:
            match = re.match(r"^([a-zA-Z0-9_-]+)\s*([~>=<!].+)", dep)
            if match:
                name = match.group(1).lower().replace("-", "_")
                if name in MAJOR_PYTHON_DEPS or name.replace("_", "-") in MAJOR_PYTHON_DEPS:
                    display = match.group(1)
                    ver = _normalize_dep_version(match.group(2))
                    if ver:
                        info[display] = ver

    package_json = repo / "package.json"
    if package_json.exists():
        try:
            data = json.loads(package_json.read_text())
        except (OSError, json.JSONDecodeError):
            data = {}
        engines = data.get("engines", {})
        if isinstance(engines, dict):
            node_ver = engines.get("node", "")
            if node_ver:
                info["Node"] = node_ver
        all_deps = {}
        all_deps.update(data.get("dependencies", {}))
        all_deps.update(data.get("devDependencies", {}))
        for name, ver in all_deps.items():
            if name.lower() in MAJOR_NODE_DEPS:
                normalized = _normalize_dep_version(str(ver))
                if normalized:
                    info[name] = normalized

    cargo_toml = repo / "Cargo.toml"
    if cargo_toml.exists():
        try:
            with open(cargo_toml, "rb") as f:
                data = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError):
            data = {}
        pkg = data.get("package", {})
        rust_version = pkg.get("rust-version", "")
        if rust_version:
            info["Rust"] = rust_version
        edition = pkg.get("edition", "")
        if edition:
            info["Rust edition"] = str(edition)

    go_mod = repo / "go.mod"
    if go_mod.exists():
        try:
            content = go_mod.read_text()
        except OSError:
            content = ""
        for line in content.splitlines():
            match = re.match(r"^go\s+(\S+)", line)
            if match:
                info["Go"] = match.group(1)
                break

    return info


def _detect_ci(repo: Path) -> str | None:
    for marker, provider in CI_MARKERS.items():
        if (repo / marker).exists():
            return provider
    return None


async def _list_files(repo: Path, ignore: list[str] | None = None) -> list[str]:
    rc, stdout, _ = await arun(["git", "ls-files"], cwd=repo, timeout=10)
    if rc != 0:
        return []
    files = stdout.strip().splitlines()
    if ignore:
        files = [f for f in files if not _is_ignored(f, ignore)]
    return files[:MAX_FILE_LIST]


def _top_level_dirs(repo: Path) -> list[str]:
    return sorted(d.name for d in repo.iterdir() if d.is_dir() and not d.name.startswith("."))


async def _recent_commits(repo: Path, n: int = 15) -> list[str]:
    rc, stdout, _ = await arun(["git", "log", f"-{n}", "--oneline"], cwd=repo, timeout=10)
    if rc == 0:
        return stdout.strip().splitlines()
    return []


def _read_package_manifest(repo: Path, language: str) -> str:
    manifests = {
        "python": "pyproject.toml",
        "javascript": "package.json",
        "typescript": "package.json",
        "rust": "Cargo.toml",
        "go": "go.mod",
    }
    manifest = manifests.get(language)
    if manifest:
        return read_truncated(repo / manifest)
    return ""


def _should_skip(path: str) -> bool:
    parts = Path(path).parts
    return any(p in SKIP_DIRS for p in parts)


def _is_already_read(path: str) -> bool:
    p = Path(path)
    return p.name in ALREADY_READ_FILENAMES and len(p.parts) == 1


def _is_binary(path: str) -> bool:
    return Path(path).suffix.lower() in BINARY_EXTENSIONS


def _is_ignored(path: str, patterns: list[str]) -> bool:
    return any(fnmatch(path, p) for p in patterns)


def _source_budget(model: str) -> int:
    context_window = get_context_window(model)
    usable = context_window - PROMPT_OVERHEAD_TOKENS - RESPONSE_RESERVE_TOKENS
    return max(usable * CHARS_PER_TOKEN, 20_000)


def _summarize_source_files(
    repo: Path,
    files: list[str],
    budget: int,
    *,
    ignore: list[str] | None = None,
    on_status: StatusCallback | None = None,
) -> str:
    source_files = [
        f
        for f in files
        if not _is_binary(f)
        and not _should_skip(f)
        and not _is_already_read(f)
        and not (ignore and _is_ignored(f, ignore))
    ]

    chunks: list[str] = []
    total_chars = 0

    for filepath in source_files:
        if total_chars >= budget:
            remaining = len(source_files) - len(chunks)
            chunks.append(f"\n... ({remaining} more files not shown, context budget reached)")
            break

        full_path = repo / filepath
        if not full_path.exists():
            continue

        if on_status:
            on_status(f"Reading {filepath}...")

        try:
            content = full_path.read_text(errors="replace")
        except OSError:
            continue

        chunk = f"\n--- {filepath} ---\n{content}"

        budget_left = budget - total_chars
        if len(chunk) > budget_left:
            chunk = chunk[:budget_left] + "\n... (truncated, budget limit)"

        chunks.append(chunk)
        total_chars += len(chunk)

    return "".join(chunks)


@dataclass
class DiscoveryData:
    name: str = ""
    language: str = "unknown"
    ci: str | None = None
    dirs: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    readme: str = ""
    manifest: str = ""
    commits: list[str] = field(default_factory=list)
    source_text: str = ""
    repo_path: Path = field(default_factory=lambda: Path("."))
    ignore: list[str] = field(default_factory=list)
    runtime_info: dict[str, str] = field(default_factory=dict)

    @property
    def metadata_context(self) -> str:
        lines = [
            f"Name: {self.name}",
            f"Language: {self.language}",
            f"CI: {self.ci or 'none detected'}",
            f"Top-level dirs: {', '.join(self.dirs) or 'none'}",
            f"File count: {len(self.files)}",
            f"\nFiles:\n{chr(10).join(self.files)}",
            f"\nREADME:\n{self.readme or '(no README found)'}",
            f"\nPackage manifest:\n{self.manifest or '(no manifest found)'}",
            f"\nRecent commits:\n{chr(10).join(self.commits) or '(no commits)'}",
        ]
        if self.runtime_info:
            runtime_lines = ", ".join(f"{k} {v}" for k, v in sorted(self.runtime_info.items()))
            lines.append(f"\nRuntime: {runtime_lines}")
        return "\n".join(lines)

    def to_context(self) -> str:
        return (
            self.metadata_context
            + f"\n\nSource files:\n{self.source_text or '(no source files found)'}"
        )

    def read_source_files(
        self,
        budget: int,
        *,
        priority_files: list[str] | None = None,
        on_status: StatusCallback | None = None,
    ) -> str:
        ordered_files = list(self.files)
        if priority_files:
            files_set = set(ordered_files)
            priority_set = set(priority_files)
            front = [f for f in priority_files if f in files_set]
            rest = [f for f in ordered_files if f not in priority_set]
            ordered_files = front + rest
        return _summarize_source_files(
            self.repo_path, ordered_files, budget, ignore=self.ignore or None, on_status=on_status
        )


async def discover(
    repo: Path,
    model: str,
    *,
    ignore: list[str] | None = None,
    on_status: StatusCallback | None = None,
) -> DiscoveryData:
    language = _detect_language(repo)
    ci = _detect_ci(repo)
    dirs = _top_level_dirs(repo)

    if on_status:
        on_status("Listing files and reading git log...")
    files, commits = await asyncio.gather(_list_files(repo, ignore=ignore), _recent_commits(repo))

    if on_status:
        on_status("Reading README and manifest...")
    readme = read_truncated(repo / "README.md")
    manifest = _read_package_manifest(repo, language)
    budget = _source_budget(model)
    source_text = _summarize_source_files(repo, files, budget, ignore=ignore, on_status=on_status)

    runtime_info = _detect_runtime_info(repo)

    return DiscoveryData(
        name=repo.resolve().name,
        language=language,
        ci=ci,
        dirs=dirs,
        files=files,
        readme=readme,
        manifest=manifest,
        commits=commits,
        source_text=source_text,
        repo_path=repo,
        ignore=ignore or [],
        runtime_info=runtime_info,
    )
