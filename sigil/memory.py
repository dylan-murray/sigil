from __future__ import annotations

from pathlib import Path

from sigil.config import SIGIL_DIR, MEMORY_DIR
from sigil.llm import complete
from sigil.utils import get_head, now_utc

PROJECT_FILE = "project.md"
WORKING_FILE = "working.md"


def _memory_dir(repo: Path) -> Path:
    return repo / SIGIL_DIR / MEMORY_DIR


def _read_file(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text()
    except OSError:
        return ""


def _parse_head(text: str) -> str:
    for line in text.splitlines()[:5]:
        if line.startswith("head:"):
            return line.split(":", 1)[1].strip()
    return ""


def load_project(repo: Path) -> str:
    return _read_file(_memory_dir(repo) / PROJECT_FILE)


def load_working(repo: Path) -> str:
    return _read_file(_memory_dir(repo) / WORKING_FILE)


def load_head(repo: Path) -> str:
    text = load_project(repo)
    return _parse_head(text)


def is_stale(repo: Path) -> bool:
    stored_head = load_head(repo)
    if not stored_head:
        return True
    return stored_head != get_head(repo)


COMPACT_PROJECT_PROMPT = """\
You maintain a living knowledge document about a code repository. This document
is read by an AI agent (Sigil) at the start of every run to understand the project
without re-analyzing everything from scratch.

{existing_section}

Here is fresh context from the current state of the repo:

{discovery_context}

Write an updated project.md that captures everything important about this project.

CRITICAL: This file is committed to the repository and may be public. NEVER include
API keys, secrets, tokens, passwords, credentials, or any sensitive information.
Only store non-sensitive project knowledge.

Include:
- What the project is and who it's for
- Language, stack, key dependencies
- Architecture and key components
- Coding conventions and patterns
- How to test, lint, and build
- Any important constraints or design decisions

Compact and distill — don't just append. If old information is outdated, replace it.
Keep it concise but thorough. A new AI agent reading only this file should deeply
understand the project.

HARD LIMIT: Keep the file under 200 lines. If you need to cut, prioritize:
1. What commands to run (test, lint, build) — always keep
2. Architecture and key components — always keep
3. Conventions and patterns — always keep
4. Recent activity and in-progress work — summarize aggressively

Start the file with exactly these two metadata lines:
head: {head}
last_updated: {timestamp}

Then write the rest as clean markdown."""


COMPACT_WORKING_PROMPT = """\
You maintain Sigil's working memory — a living document tracking what the AI agent
has done, tried, learned, and should focus on next for this repository.

{existing_section}

Here is what happened this run:

{run_context}

Write an updated working.md that captures Sigil's evolving knowledge.

CRITICAL: This file is committed to the repository and may be public. NEVER include
API keys, secrets, tokens, passwords, credentials, or any sensitive information.
Only store non-sensitive operational knowledge.

Include:
- What Sigil has done so far (PRs opened, issues filed, changes made)
- What was tried and didn't work (so we don't repeat mistakes)
- What was proposed and rejected by the user
- What to focus on next run
- Any patterns or insights learned about this specific codebase

Compact and distill — old run details should fade into summaries. Recent runs
get more detail. The goal is a fixed-size working memory, not a growing log.
Keep it under 100 lines.

Start with:
last_updated: {timestamp}

Then write the rest as clean markdown."""


def update_project(repo: Path, model: str, discovery_context: str) -> str:
    existing = load_project(repo)
    head = get_head(repo)
    timestamp = now_utc()

    existing_section = (
        f"Here is the existing project.md:\n\n{existing}"
        if existing
        else "No existing project.md — this is the first run."
    )

    prompt = COMPACT_PROJECT_PROMPT.format(
        existing_section=existing_section,
        discovery_context=discovery_context,
        head=head,
        timestamp=timestamp,
    )

    content = complete(model=model, messages=[{"role": "user", "content": prompt}])

    mdir = _memory_dir(repo)
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / PROJECT_FILE).write_text(content)
    return content


def update_working(repo: Path, model: str, run_context: str) -> str:
    existing = load_working(repo)
    timestamp = now_utc()

    existing_section = (
        f"Here is the existing working.md:\n\n{existing}"
        if existing
        else "No existing working.md — this is Sigil's first run on this repo."
    )

    prompt = COMPACT_WORKING_PROMPT.format(
        existing_section=existing_section,
        run_context=run_context,
        timestamp=timestamp,
    )

    content = complete(model=model, messages=[{"role": "user", "content": prompt}])

    mdir = _memory_dir(repo)
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / WORKING_FILE).write_text(content)
    return content
