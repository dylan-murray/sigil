from __future__ import annotations

import subprocess
from pathlib import Path

from sigil.llm import get_context_window
from sigil.summarizer import EXTENSION_TO_LANGUAGE, summarize

MAX_FILE_LIST = 500

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

CHARS_PER_TOKEN = 4
PROMPT_OVERHEAD_TOKENS = 8_000
RESPONSE_RESERVE_TOKENS = 4_000


def _read_snippet(path: Path, max_chars: int = 3000) -> str:
    if not path.exists():
        return ""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return ""
    if len(text) > max_chars:
        return text[:max_chars] + "\n... (truncated)"
    return text


def _detect_language(repo: Path) -> str:
    for marker, lang in LANGUAGE_MARKERS.items():
        if (repo / marker).exists():
            return lang
    return "unknown"


def _detect_ci(repo: Path) -> str | None:
    for marker, provider in CI_MARKERS.items():
        if (repo / marker).exists():
            return provider
    return None


def _list_files(repo: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            capture_output=True,
            text=True,
            cwd=repo,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip().splitlines()[:MAX_FILE_LIST]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return []


def _top_level_dirs(repo: Path) -> list[str]:
    return sorted(d.name for d in repo.iterdir() if d.is_dir() and not d.name.startswith("."))


def _recent_commits(repo: Path, n: int = 15) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "log", f"-{n}", "--oneline"],
            capture_output=True,
            text=True,
            cwd=repo,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip().splitlines()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
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
        return _read_snippet(repo / manifest)
    return ""


def _should_skip(path: str) -> bool:
    parts = Path(path).parts
    return any(p in SKIP_DIRS for p in parts)


def _is_already_read(path: str) -> bool:
    return Path(path).name in ALREADY_READ_FILENAMES


CONFIG_EXTENSIONS = {
    ".yaml",
    ".yml",
    ".toml",
    ".json",
    ".xml",
    ".sql",
    ".graphql",
    ".proto",
    ".tf",
    ".hcl",
    ".html",
    ".css",
    ".scss",
}


def _is_source_file(path: str) -> bool:
    return Path(path).suffix.lower() in EXTENSION_TO_LANGUAGE


def _is_config_file(path: str) -> bool:
    return Path(path).suffix.lower() in CONFIG_EXTENSIONS


def _source_budget(model: str) -> int:
    context_window = get_context_window(model)
    usable = context_window - PROMPT_OVERHEAD_TOKENS - RESPONSE_RESERVE_TOKENS
    return max(usable * CHARS_PER_TOKEN, 20_000)


def _summarize_source_files(repo: Path, files: list[str], budget: int) -> str:
    source_files = [
        f
        for f in files
        if (_is_source_file(f) or _is_config_file(f))
        and not _should_skip(f)
        and not _is_already_read(f)
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

        try:
            content = full_path.read_text(errors="replace")
        except OSError:
            continue

        summary = summarize(content, filepath)
        if not summary:
            continue
        chunk = f"\n--- {filepath} ---\n{summary}"

        budget_left = budget - total_chars
        if len(chunk) > budget_left:
            chunk = chunk[:budget_left] + "\n... (truncated, budget limit)"

        chunks.append(chunk)
        total_chars += len(chunk)

    return "".join(chunks)


def discover(repo: Path, model: str) -> str:
    language = _detect_language(repo)
    files = _list_files(repo)
    ci = _detect_ci(repo)
    dirs = _top_level_dirs(repo)
    commits = _recent_commits(repo)
    readme = _read_snippet(repo / "README.md")
    claude_md = _read_snippet(repo / "CLAUDE.md")
    manifest = _read_package_manifest(repo, language)
    budget = _source_budget(model)
    source_summaries = _summarize_source_files(repo, files, budget)

    sections = [
        f"Name: {repo.resolve().name}",
        f"Language: {language}",
        f"CI: {ci or 'none detected'}",
        f"Top-level dirs: {', '.join(dirs) or 'none'}",
        f"File count: {len(files)}",
        f"\nFiles:\n{chr(10).join(files)}",
        f"\nREADME:\n{readme or '(no README found)'}",
        f"\nCLAUDE.md:\n{claude_md or '(no CLAUDE.md found)'}",
        f"\nPackage manifest:\n{manifest or '(no manifest found)'}",
        f"\nRecent commits:\n{chr(10).join(commits) or '(no commits)'}",
        f"\nSource file summaries:\n{source_summaries or '(no source files found)'}",
    ]

    return "\n".join(sections)
