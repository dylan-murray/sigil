import hashlib
from pathlib import Path

import yaml
from pydantic import BaseModel

from sigil.core.config import MEMORY_DIR, SIGIL_DIR, memory_dir
from sigil.core.llm import CHARS_PER_TOKEN, acompletion, safe_max_tokens, structured_completion
from sigil.core.utils import arun, now_utc, read_file

WORKING_FILE = "working.md"
MEMORY_EXCLUDE_PREFIX = f"{SIGIL_DIR}/{MEMORY_DIR}/"


def _write_frontmatter(meta: dict, body: str) -> str:
    front = yaml.dump(meta, default_flow_style=False, sort_keys=False).strip()
    return f"---\n{front}\n---\n\n{body}\n"


def load_working(repo: Path) -> str:
    return read_file(memory_dir(repo) / WORKING_FILE)


COMPACT_WORKING_PROMPT = """\
You maintain Sigil's working memory — a living document tracking what the AI agent
has done, tried, learned, and should focus on next for this repository.

{existing_section}

Here is what happened this run:

{run_context}

Write the BODY of an updated working.md. Do NOT include frontmatter (the --- block)
— that is added automatically.

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

Write clean markdown."""


async def compute_manifest_hash(repo: Path) -> str:
    rc, stdout, _ = await arun(
        ["git", "ls-tree", "-r", "HEAD"],
        cwd=repo,
        timeout=30,
    )
    if rc != 0:
        return ""
    lines = [
        line
        for line in stdout.strip().splitlines()
        if not line.split("\t", 1)[-1].startswith(MEMORY_EXCLUDE_PREFIX)
    ]
    digest = hashlib.sha256("\n".join(sorted(lines)).encode()).hexdigest()
    return digest


def load_manifest_hash(repo: Path) -> str:
    content = load_working(repo)
    if not content:
        return ""
    if not content.startswith("---"):
        return ""
    end = content.find("---", 3)
    if end == -1:
        return ""
    try:
        meta = yaml.safe_load(content[3:end])
    except yaml.YAMLError:
        return ""
    return meta.get("manifest_hash", "") if isinstance(meta, dict) else ""


async def update_working(
    repo: Path,
    model: str,
    run_context: str,
    *,
    manifest_hash: str | None = None,
    max_tokens: int | None = None,
) -> str:
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
    )

    msgs = [{"role": "user", "content": prompt}]
    response = await acompletion(
        label="memory:compact",
        model=model,
        messages=msgs,
        temperature=0.0,
        max_tokens=safe_max_tokens(model, msgs, requested=max_tokens or 4_096),
    )
    body = response.choices[0].message.content
    meta: dict[str, str] = {"last_updated": timestamp}
    if manifest_hash:
        meta["manifest_hash"] = manifest_hash
    content = _write_frontmatter(meta, body)

    mdir = memory_dir(repo)
    mdir.mkdir(parents=True, exist_ok=True)
    target = mdir / WORKING_FILE
    target.write_text(content)
    return str(target)


class _WorkingMemoryCompaction(BaseModel):
    trimmed_body: str
    extracted_patterns: str


COMPACT_IF_LARGE_PROMPT = """\
You are compacting Sigil's working memory. The file has grown too large.

Here is the current working.md:

{working_content}

Do two things:
1. Extract long-term patterns, insights, and lessons from OLDER entries into
   `extracted_patterns`. These are observations that remain useful across runs
   (e.g., "type:ignore removals are safe", "security tests expose real bugs").
   Write them as concise bullet points under category headings.
2. Return a `trimmed_body` that keeps only RECENT entries (last 1-2 runs) and
   the "Focus for Next Run" section. Remove old run details that have been
   summarized into patterns. Target ~100 lines.

Do NOT include frontmatter in trimmed_body — it is added automatically.

CRITICAL: This file is committed to the repository and may be public. NEVER include
API keys, secrets, tokens, passwords, credentials, or any sensitive information."""


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    if not content.startswith("---"):
        return {}, content
    end = content.find("---", 3)
    if end == -1:
        return {}, content
    try:
        meta = yaml.safe_load(content[3:end])
    except yaml.YAMLError:
        return {}, content
    if not isinstance(meta, dict):
        return {}, content
    body = content[end + 3 :].strip()
    return meta, body


async def compact_working_if_large(
    repo: Path,
    model: str,
    *,
    max_tokens: int | None = None,
    limit: int = 4000,
) -> int:
    content = load_working(repo)
    if not content:
        return 0
    original_tokens = len(content) // CHARS_PER_TOKEN
    if original_tokens <= limit:
        return 0

    prompt = COMPACT_IF_LARGE_PROMPT.format(working_content=content)
    msgs = [{"role": "user", "content": prompt}]
    result = await structured_completion(
        label="memory:compact_if_large",
        model=model,
        messages=msgs,
        schema=_WorkingMemoryCompaction,
        temperature=0.0,
        max_tokens=max_tokens or 4_096,
    )

    meta, _ = _parse_frontmatter(content)
    timestamp = now_utc()
    meta["last_updated"] = timestamp
    new_content = _write_frontmatter(meta, result.trimmed_body)

    mdir = memory_dir(repo)
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / WORKING_FILE).write_text(new_content)

    if result.extracted_patterns.strip():
        patterns_path = mdir / "patterns.md"
        existing_patterns = read_file(patterns_path)
        date_str = now_utc()[:10]
        section = f"\n## Extracted {date_str}\n\n{result.extracted_patterns.strip()}\n"
        if existing_patterns:
            patterns_path.write_text(existing_patterns.rstrip() + "\n" + section)
        else:
            patterns_path.write_text(f"# Coding Patterns\n{section}")

    new_tokens = len(new_content) // CHARS_PER_TOKEN
    return original_tokens - new_tokens
