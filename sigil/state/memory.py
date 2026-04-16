import hashlib
import logging
from pathlib import Path

import yaml

from sigil.core.config import MEMORY_DIR, SIGIL_DIR, memory_dir
from sigil.core.llm import acompletion, safe_max_tokens
from sigil.core.utils import arun, now_utc, read_file

logger = logging.getLogger(__name__)

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
    from sigil.pipeline.cost_tracker import load_cost_tracker

    existing = load_working(repo)
    timestamp = now_utc()

    # Inject cost insights into run context if available
    try:
        tracker = load_cost_tracker(repo)
        insights = tracker.analyze()
        if insights.summary:
            run_context = f"{run_context}\n\nCost Efficiency Insights:\n{insights.summary}"
    except Exception as exc:
        logger.debug("Could not load cost tracker for working memory update: %s", exc)

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
