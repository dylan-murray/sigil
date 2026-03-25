from pathlib import Path

import yaml

from sigil.core.config import SIGIL_DIR, MEMORY_DIR
from sigil.core.llm import acompletion, get_max_output_tokens
from sigil.core.utils import now_utc, read_file

WORKING_FILE = "working.md"


def _memory_dir(repo: Path) -> Path:
    return repo / SIGIL_DIR / MEMORY_DIR


def _write_frontmatter(meta: dict, body: str) -> str:
    front = yaml.dump(meta, default_flow_style=False, sort_keys=False).strip()
    return f"---\n{front}\n---\n\n{body}\n"


def load_working(repo: Path) -> str:
    return read_file(_memory_dir(repo) / WORKING_FILE)


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


async def update_working(repo: Path, model: str, run_context: str) -> str:
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

    response = await acompletion(
        label="memory:compact",
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=get_max_output_tokens(model) // 4,
    )
    body = response.choices[0].message.content
    meta = {"last_updated": timestamp}
    content = _write_frontmatter(meta, body)

    mdir = _memory_dir(repo)
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / WORKING_FILE).write_text(content)
    return content
