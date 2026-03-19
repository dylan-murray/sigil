from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from sigil.llm import complete_json
from sigil.memory import Memory
from sigil.models import Component, RepoModel

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

TEST_COMMANDS = {
    "python": ["pytest", "uv run pytest", "python -m pytest"],
    "javascript": ["npm test", "yarn test", "pnpm test"],
    "typescript": ["npm test", "yarn test", "pnpm test"],
    "rust": ["cargo test"],
    "go": ["go test ./..."],
    "ruby": ["bundle exec rspec", "rake test"],
    "java": ["mvn test", "gradle test"],
}

LINT_COMMANDS = {
    "python": ["ruff format .", "ruff check .", "black .", "flake8"],
    "javascript": ["npm run lint", "eslint ."],
    "typescript": ["npm run lint", "eslint ."],
    "rust": ["cargo clippy"],
    "go": ["golangci-lint run"],
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


def _detect_test_command(repo: Path, language: str) -> str | None:
    if language == "python":
        manifest = repo / "pyproject.toml"
        if manifest.exists():
            text = manifest.read_text()
            if "pytest" in text:
                if (repo / "pyproject.toml").exists() and "uv" in text:
                    return "uv run pytest"
                return "pytest"
    if language in ("javascript", "typescript"):
        pkg = repo / "package.json"
        if pkg.exists():
            try:
                data = json.loads(pkg.read_text())
                scripts = data.get("scripts", {})
                if "test" in scripts:
                    return "npm test"
            except json.JSONDecodeError:
                pass
    candidates = TEST_COMMANDS.get(language, [])
    return candidates[0] if candidates else None


def _detect_lint_command(repo: Path, language: str) -> str | None:
    if language == "python":
        manifest = repo / "pyproject.toml"
        if manifest.exists():
            text = manifest.read_text()
            if "ruff" in text:
                return "uv run ruff format ." if "uv" in text else "ruff format ."
    candidates = LINT_COMMANDS.get(language, [])
    return candidates[0] if candidates else None


def _gather_context(repo: Path) -> dict:
    language = _detect_language(repo)
    files = _list_files(repo)
    return {
        "name": repo.resolve().name,
        "language": language,
        "ci_provider": _detect_ci(repo),
        "top_level_dirs": _top_level_dirs(repo),
        "file_count": len(files),
        "files": files,
        "readme": _read_snippet(repo / "README.md"),
        "claude_md": _read_snippet(repo / "CLAUDE.md"),
        "package_manifest": _read_package_manifest(repo, language),
        "recent_commits": _recent_commits(repo),
        "test_command": _detect_test_command(repo, language),
        "lint_command": _detect_lint_command(repo, language),
    }


DISCOVERY_PROMPT = """\
You are analyzing a code repository to build a deep understanding of what it is,
what it does, and how it's structured. You will use this understanding to suggest
improvements later.

Here is everything I've gathered about the repo:

Name: {name}
Language: {language}
CI: {ci_provider}
Top-level dirs: {top_level_dirs}
File count: {file_count}

Files:
{files}

README:
{readme}

CLAUDE.md:
{claude_md}

Package manifest:
{package_manifest}

Recent commits:
{recent_commits}

Based on this information, produce a JSON object with these fields:
- "purpose": A 1-2 sentence description of what this project does and who it's for.
- "stack": A list of key technologies, frameworks, and libraries used (e.g. ["python", "fastapi", "postgresql", "react"]).
- "key_components": A list of objects with "name", "path", and "description" for the major modules/components.
- "conventions": A list of coding conventions you can infer (import style, naming, patterns, etc).
- "build_command": The build command if you can infer one, or null.
- "open_issues_summary": A brief summary of what work appears to be in progress based on recent commits and any issue references.

Return ONLY valid JSON, no markdown fences."""


def _get_head(repo: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=repo,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return ""


def _commits_since(repo: Path, since_commit: str, n: int = 30) -> list[str]:
    if not since_commit:
        return []
    try:
        result = subprocess.run(
            ["git", "log", f"{since_commit}..HEAD", f"-{n}", "--oneline"],
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


def discover(repo: Path, model: str, memory: Memory | None = None) -> tuple[RepoModel, str]:
    head = _get_head(repo)

    if memory and memory.has_repo_model and memory.repo_model_head:
        new_commits = _commits_since(repo, memory.repo_model_head)
        if not new_commits:
            return memory.repo_model, "cached"

    ctx = _gather_context(repo)

    prompt = DISCOVERY_PROMPT.format(
        name=ctx["name"],
        language=ctx["language"],
        ci_provider=ctx["ci_provider"] or "none detected",
        top_level_dirs=", ".join(ctx["top_level_dirs"]) or "none",
        file_count=ctx["file_count"],
        files="\n".join(ctx["files"]),
        readme=ctx["readme"] or "(no README found)",
        claude_md=ctx["claude_md"] or "(no CLAUDE.md found)",
        package_manifest=ctx["package_manifest"] or "(no manifest found)",
        recent_commits="\n".join(ctx["recent_commits"]) or "(no commits)",
    )

    raw = complete_json(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        if raw.endswith("```"):
            raw = raw[: raw.rfind("```")]
    data = json.loads(raw)

    components = [
        Component(name=c["name"], path=c["path"], description=c["description"])
        for c in data.get("key_components", [])
    ]

    discovery_mode = "full" if not (memory and memory.has_repo_model) else "incremental"

    repo_model = RepoModel(
        name=ctx["name"],
        language=ctx["language"],
        stack=data.get("stack", []),
        purpose=data.get("purpose", ""),
        key_components=components,
        conventions=data.get("conventions", []),
        test_command=ctx["test_command"],
        lint_command=ctx["lint_command"],
        build_command=data.get("build_command"),
        ci_provider=ctx["ci_provider"],
        open_issues_summary=data.get("open_issues_summary", ""),
        file_count=ctx["file_count"],
        top_level_dirs=ctx["top_level_dirs"],
        readme_snippet=ctx["readme"],
        claude_md_snippet=ctx["claude_md"],
        recent_commits=ctx["recent_commits"],
    )
    return repo_model, discovery_mode
