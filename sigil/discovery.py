from __future__ import annotations

import json
import subprocess
from pathlib import Path

MAX_SNIPPET_CHARS = 3000
MAX_FILE_LIST = 200

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


def _read_snippet(path: Path, max_chars: int = MAX_SNIPPET_CHARS) -> str:
    if not path.exists():
        return ""
    text = path.read_text(errors="replace")
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
            files = result.stdout.strip().splitlines()
            return files[:MAX_FILE_LIST]
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


def discover(repo: Path, model: str) -> str:
    language = _detect_language(repo)
    files = _list_files(repo)
    ci = _detect_ci(repo)
    dirs = _top_level_dirs(repo)
    commits = _recent_commits(repo)
    readme = _read_snippet(repo / "README.md")
    claude_md = _read_snippet(repo / "CLAUDE.md")
    manifest = _read_package_manifest(repo, language)

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
    ]

    return "\n".join(sections)
