import random
from pathlib import Path

from sigil.core.config import memory_dir
from sigil.core.llm import acompletion, get_max_output_tokens, safe_max_tokens
from sigil.core.utils import StatusCallback, arun, read_truncated

STYLE_FILE = "style.md"
MAX_SAMPLE_FILES = 15
MIN_SAMPLE_FILES = 10
MAX_STYLE_INPUT_CHARS = 60_000
MAX_FILE_CHARS = 4_000

STYLE_PROMPT = """\
You are extracting a Style Lexicon for an AI coding agent.

Analyze the sampled source files below and infer consistent micro-idioms that
appear to be local conventions for this repository. Focus on patterns that are
actually repeated, not one-off quirks.

Extract only concise, useful guidance in markdown with sections for:
- Naming patterns: preferred variable, function, and helper naming styles
- Return style: early returns vs. else blocks, guard clauses, and nesting depth
- Comment and docstring density: when comments/docstrings are common or rare
- Expression style: terse vs. verbose code, use of temporary variables, chaining
- Error handling style: explicit exceptions, defensive checks, fallback patterns
- Structural cues: file/module layout and naming conventions if obvious

Rules:
- Prefer project-wide consistency over file-specific oddities
- Keep it short and practical, under 80 lines
- Do not mention secrets or sensitive data
- Write a Markdown document suitable for .sigil/memory/style.md

Sampled files:
{samples}
"""


def _style_path(repo: Path) -> Path:
    return memory_dir(repo) / STYLE_FILE


async def extract_style(
    repo: Path,
    model: str,
    *,
    on_status: StatusCallback | None = None,
) -> str | None:
    if on_status:
        on_status("extracting style lexicon")

    rc, stdout, _ = await arun(["git", "ls-files"], cwd=repo, timeout=30)
    if rc != 0:
        return None

    candidates = [
        line.strip()
        for line in stdout.splitlines()
        if line.strip().endswith((".py", ".md", ".toml", ".yaml", ".yml"))
        and not line.startswith(".sigil/")
    ]
    if not candidates:
        return None

    sample_size = min(len(candidates), MAX_SAMPLE_FILES)
    if len(candidates) <= MIN_SAMPLE_FILES:
        sampled = candidates
    else:
        sampled = random.sample(candidates, sample_size)

    parts: list[str] = []
    total_chars = 0
    for rel in sampled:
        text = read_truncated(repo / rel, max_chars=MAX_FILE_CHARS)
        if not text:
            continue
        chunk = f"## {rel}\n\n{text}\n"
        if total_chars + len(chunk) > MAX_STYLE_INPUT_CHARS:
            remaining = MAX_STYLE_INPUT_CHARS - total_chars
            if remaining <= 0:
                break
            parts.append(chunk[:remaining])
            break
        parts.append(chunk)
        total_chars += len(chunk)

    if not parts:
        return None

    prompt = STYLE_PROMPT.format(samples="\n".join(parts))
    response = await acompletion(
        label="memory:style",
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=safe_max_tokens(
            model, [{"role": "user", "content": prompt}], requested=get_max_output_tokens(model)
        ),
    )
    content = response.choices[0].message.content or ""
    if not content.strip():
        return None

    path = _style_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n")
    return str(path)
