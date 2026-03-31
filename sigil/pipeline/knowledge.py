import asyncio
import json
import logging
import re
from pathlib import Path

from sigil.core.agent import Agent, Tool, ToolResult
from sigil.core.config import MEMORY_DIR, SIGIL_DIR, memory_dir
from sigil.core.llm import (
    CHARS_PER_TOKEN,
    acompletion,
    get_context_window,
    get_max_output_tokens,
    safe_max_tokens,
)
from sigil.core.utils import StatusCallback, arun, get_head, now_utc, read_file
from sigil.pipeline.discovery import DiscoveryData
from sigil.state.memory import compute_manifest_hash


logger = logging.getLogger(__name__)

INDEX_FILE = "INDEX.md"
MAX_KNOWLEDGE_FILES = 150
RESERVED_FILES = frozenset({INDEX_FILE, "working.md"})
PROMPT_OVERHEAD_TOKENS = 2000
MAX_SELECTED_FILES = 5

SELECT_TOOL = {
    "type": "function",
    "function": {
        "name": "load_memory_files",
        "description": "Load specific knowledge files from the knowledge base.",
        "parameters": {
            "type": "object",
            "properties": {
                "filenames": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of filenames to load (e.g. ['architecture.md', 'patterns.md'])",
                },
            },
            "required": ["filenames"],
        },
    },
}

_KNOWLEDGE_FILE_RULES = """\
Rules for files:
- Each file covers ONE topic deeply and is self-contained
- Keep each file under 400 lines. If a topic is larger, split it into focused sub-files (e.g. api-models.md + api-pipeline.md instead of one huge api.md)
- Required: project.md (what, who, language, stack, build/test/lint) and architecture.md (modules, data flow, system design)
- Optional: patterns.md, dependencies.md, api.md, testing.md, or any other useful topic
- Up to {max_files} files total
- Filenames: lowercase, hyphens for multi-word, ending in .md
- Do NOT produce INDEX.md or working.md — those are managed separately
- Thorough but concise — substance over filler
- NEVER include API keys, secrets, tokens, or credentials

CRITICAL — H1 headers are how agents discover content. The index is built
automatically from your H1 (# Title) headers. Agents ONLY see H1 headers
when deciding which files to load — they do NOT see the body text. Therefore
EVERY H1 must be a self-contained description of the content that follows.

Bad H1 examples:  "# Overview", "# Configuration", "# Testing"
Good H1 examples:
  "# Sigil — Autonomous Repo Improvement Agent (Python 3.11/litellm/typer)"
  "# Config File Format — .sigil/config.yml with Agent and Model Settings"
  "# Worktree-Based Parallel Execution with Pre/Post Hook Pipeline"
  "# pytest + pytest-asyncio Test Setup with Mock Patterns"

Write H1s as if the reader will NEVER read the paragraph below — the header
alone must convey what the section is about and why you'd want to read it.

Total budget for ALL file contents combined: ~{budget_chars} characters.

CRITICAL: These files are committed to the repository and may be public.
NEVER include API keys, secrets, tokens, passwords, credentials, or any
sensitive information. Respond with ONLY the JSON object."""

INIT_PROMPT = (
    """\
You are building a knowledge base for an AI agent that will analyze and improve
a code repository. Produce a set of focused knowledge files that downstream
agents can selectively load.

Here is the raw discovery context from the repository:

{discovery_context}

Here are the existing knowledge files (may be empty on first run):

{existing_knowledge}

Respond with a single JSON object (no markdown fences, no commentary) with this
exact structure:

{{
  "files": {{
    "project.md": "full markdown content...",
    "architecture.md": "full markdown content...",
    ...more files as needed...
  }}
}}

"""
    + _KNOWLEDGE_FILE_RULES
)

INCREMENTAL_PROMPT = """\
You are updating a knowledge base for an AI agent that analyzes a code repository.
New commits have landed since the last update. Your job is to surgically update
only the knowledge files affected by these changes.

Here are the commits since the last knowledge update:

{commit_log}

Here are the per-file diffs for the changed source files:

{per_file_diffs}

Here is the knowledge index describing what each file covers:

{index_content}

First, use the read_knowledge_file tool to load any knowledge files that need
updating based on the diffs. Only read files that are actually affected.

Then, respond with a single JSON object (no markdown fences, no commentary):

{{
  "files": {{
    "architecture.md": "updated full content...",
    ...only affected files...
  }}
}}

Total budget for ALL updated file contents combined: ~{budget_chars} characters.

Rules:
- Only include files in "files" that actually changed — minimize output
- If a file's content should be empty string "", that means delete it
- Keep each file under 400 lines. If a file has grown too large, split it into focused sub-files (e.g. api-models.md + api-pipeline.md)
- Filenames: lowercase, hyphens, .md extension
- Do NOT produce INDEX.md or working.md
- NEVER include secrets, API keys, tokens, passwords, or credentials

CRITICAL — H1 headers are how agents discover content. The index is built
automatically from your H1 (# Title) headers. Agents ONLY see H1 headers
when deciding which files to load — they do NOT see the body text. Therefore
EVERY H1 must be a self-contained description of the content that follows.

Bad H1 examples:  "# Overview", "# Configuration", "# Testing"
Good H1 examples:
  "# Sigil — Autonomous Repo Improvement Agent (Python 3.11/litellm/typer)"
  "# Config File Format — .sigil/config.yml with Agent and Model Settings"
  "# Worktree-Based Parallel Execution with Pre/Post Hook Pipeline"
  "# pytest + pytest-asyncio Test Setup with Mock Patterns"

Write H1s as if the reader will NEVER read the paragraph below — the header
alone must convey what the section is about and why you'd want to read it.

CRITICAL: These files are committed to the repository and may be public.
Respond with ONLY the JSON object."""

STRUCTURAL_MAP_PROMPT = """\
You are building a structural map of a code repository. This is pass 1 of 2 —
you will receive source code in pass 2. For now, focus on understanding the
high-level architecture from metadata only.

Here is the repository metadata:

{metadata_context}

Respond with a single JSON object (no markdown fences, no commentary):

{{
  "structural_map": "A markdown document describing the repo's architecture, module boundaries, key components, and data flow. Be specific about directory structure and module responsibilities.",
  "priority_files": ["path/to/important/file.py", "path/to/core/module.py", ...]
}}

Rules for priority_files:
- List the 30-50 most important source files that a developer MUST read to understand this codebase
- Prioritize: entry points, core business logic, public APIs, config, data models
- Deprioritize: tests, generated code, vendor code, docs, config files already shown above
- Order by importance (most important first)

Rules for structural_map:
- Focus on module boundaries, key abstractions, and data flow
- Name specific directories, files, and their responsibilities
- Keep under 2000 words
- NEVER include API keys, secrets, tokens, or credentials"""

PASS2_PROMPT = (
    """\
You are building a knowledge base for an AI agent that will analyze and improve
a code repository. This is pass 2 of 2 — you already have the structural map
from pass 1. Now produce detailed knowledge files from the actual source code.

Structural map from pass 1:

{structural_map}

Source code of the most important files:

{source_context}

Here are the existing knowledge files (may be empty on first run):

{existing_knowledge}

Respond with a single JSON object (no markdown fences, no commentary) with this
exact structure:

{{
  "files": {{
    "project.md": "full markdown content...",
    "architecture.md": "full markdown content...",
    ...more files as needed...
  }}
}}

"""
    + _KNOWLEDGE_FILE_RULES
)

MAX_DIFF_CHARS_PER_FILE = 10_000
MAX_TOTAL_DIFF_CHARS = 100_000
MAX_INCREMENTAL_ROUNDS = 3
MAX_CONCURRENT_DIFFS = 20
MAX_TOOL_READ_CHARS = 100_000


def _load_existing_knowledge(mdir: Path) -> dict[str, str]:
    knowledge = {}
    for f in mdir.glob("*.md"):
        if f.name in RESERVED_FILES:
            continue
        knowledge[f.name] = read_file(f)
    return knowledge


def _format_existing(existing: dict[str, str]) -> str:
    if not existing:
        return "(no existing knowledge files — first run)"
    parts = []
    for name, content in sorted(existing.items()):
        parts.append(f"### {name}\n```\n{content}\n```")
    return "\n\n".join(parts)


def _knowledge_budget(model: str) -> int:
    context_window = get_context_window(model)
    budget_tokens = max(context_window // 4, 4000)
    budget_chars = budget_tokens * 4
    return min(budget_chars, 200_000)


def _max_input_chars(model: str) -> int:
    context_window = get_context_window(model)
    output_tokens = get_max_output_tokens(model)
    available = context_window - output_tokens - PROMPT_OVERHEAD_TOKENS
    return max(available * CHARS_PER_TOKEN, 16_000)


def _truncate_to_budget(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n... (truncated to fit context window)"


def _decode_json_string(s: str) -> str:
    try:
        return json.loads(f'"{s}"')
    except (json.JSONDecodeError, ValueError):
        return (
            s.replace("\\n", "\n")
            .replace("\\t", "\t")
            .replace("\\'", "'")
            .replace('\\"', '"')
            .replace("\\\\", "\\")
        )


def _parse_response(raw: str) -> dict:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        newline_pos = cleaned.find("\n")
        if newline_pos == -1:
            cleaned = ""
        else:
            cleaned = cleaned[newline_pos + 1 :]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    repaired = _repair_truncated_json(cleaned)
    if repaired is not None:
        return repaired

    raise json.JSONDecodeError("Failed to parse response as JSON", cleaned, 0)


def _repair_truncated_json(raw: str) -> dict | None:
    if '"files"' not in raw:
        return None

    files_match = re.search(r'"files"\s*:\s*\{', raw)
    if not files_match:
        return None

    files: dict[str, str] = {}
    pattern = re.compile(r'"([^"]+\.md)"\s*:\s*"((?:[^"\\]|\\.)*)"')
    for m in pattern.finditer(raw):
        files[m.group(1)] = _decode_json_string(m.group(2))

    if not files:
        return None

    logger.debug("Repaired truncated JSON — salvaged %d files", len(files))
    return {"files": files}


def _get_last_head(mdir: Path) -> str:
    index_path = mdir / INDEX_FILE
    if not index_path.exists():
        return ""
    content = read_file(index_path)
    match = re.search(r"head:\s*([a-f0-9]+)", content)
    return match.group(1) if match else ""


def _get_last_manifest_hash(mdir: Path) -> str:
    index_path = mdir / INDEX_FILE
    if not index_path.exists():
        return ""
    content = read_file(index_path)
    match = re.search(r"manifest:\s*([a-f0-9]{64})", content)
    return match.group(1) if match else ""


async def _get_changed_files(repo: Path, last_head: str) -> list[str]:
    rc, stdout, _ = await arun(
        ["git", "diff", "--name-only", f"{last_head}..HEAD"],
        cwd=repo,
        timeout=10,
    )
    if rc != 0:
        return []
    return [f for f in stdout.strip().splitlines() if f.strip()]


async def _diff_one_file(
    repo: Path, last_head: str, filepath: str, sem: asyncio.Semaphore
) -> tuple[str, str]:
    async with sem:
        rc, diff, _ = await arun(
            ["git", "diff", last_head, "HEAD", "--", filepath],
            cwd=repo,
            timeout=10,
        )
        if rc != 0 or not diff.strip():
            return filepath, ""
        return filepath, diff.strip()


DIFF_OMIT_THRESHOLD = 0.5


async def _get_per_file_diffs(
    repo: Path, last_head: str, changed_files: list[str]
) -> tuple[str, bool]:
    sem = asyncio.Semaphore(MAX_CONCURRENT_DIFFS)
    results = await asyncio.gather(
        *[_diff_one_file(repo, last_head, f, sem) for f in changed_files]
    )

    parts = []
    total_chars = 0
    files_with_diffs = 0
    omitted_count = 0
    for filepath, diff_text in results:
        if not diff_text:
            continue
        files_with_diffs += 1
        if total_chars >= MAX_TOTAL_DIFF_CHARS:
            parts.append(f"\n--- {filepath} ---\n(diff omitted — total budget exceeded)")
            omitted_count += 1
            continue
        if len(diff_text) > MAX_DIFF_CHARS_PER_FILE:
            diff_text = diff_text[:MAX_DIFF_CHARS_PER_FILE] + "\n... (truncated)"
        section = f"\n--- {filepath} ---\n{diff_text}"
        parts.append(section)
        total_chars += len(section)

    heavily_truncated = (
        files_with_diffs > 0 and omitted_count / files_with_diffs >= DIFF_OMIT_THRESHOLD
    )
    return "\n".join(parts), heavily_truncated


async def _get_commit_log(repo: Path, last_head: str) -> str:
    rc, stdout, _ = await arun(
        ["git", "log", "--oneline", f"{last_head}..HEAD"],
        cwd=repo,
        timeout=10,
    )
    if rc != 0:
        return ""
    return stdout.strip()


def _sanitize_filename(filename: str) -> str | None:
    filename = filename.strip()
    if not filename.endswith(".md"):
        filename += ".md"
    if Path(filename).name != filename:
        return None
    if filename in RESERVED_FILES:
        return None
    return filename


def _write_files(
    mdir: Path, files: dict[str, str], on_status: StatusCallback | None = None
) -> dict[str, str]:
    written = {}
    for raw_filename, content in files.items():
        filename = _sanitize_filename(raw_filename)
        if not filename:
            logger.debug("Skipping invalid/reserved file: %s", raw_filename)
            continue
        if not content:
            target = mdir / filename
            if target.exists():
                target.unlink()
                logger.info("Deleted knowledge file: %s", filename)
            continue
        if on_status:
            on_status(f"Writing {filename}...")
        (mdir / filename).write_text(content.strip() + "\n")
        written[filename] = content
    return written


def _write_index(mdir: Path, index_content: str, head: str, manifest_hash: str = "") -> None:
    manifest_part = f" | manifest: {manifest_hash}" if manifest_hash else ""
    meta_line = f"<!-- head: {head}{manifest_part} | updated: {now_utc()} -->\n\n"
    (mdir / INDEX_FILE).write_text(meta_line + index_content.strip() + "\n")


def _fallback_rebuild_index(
    mdir: Path,
    existing: dict[str, str],
    head: str,
    on_status: StatusCallback | None = None,
    *,
    manifest_hash: str = "",
) -> str:
    logger.info("Rebuilding index from %d existing files (LLM output unusable)", len(existing))
    if on_status:
        on_status("Writing INDEX.md...")
    _write_index(mdir, _build_index(existing), head, manifest_hash=manifest_hash)
    return str(mdir / INDEX_FILE)


async def compact_knowledge(
    repo: Path,
    model: str,
    discovery: DiscoveryData | str,
    *,
    force_full: bool = False,
    compactor_max_tokens: int | None = None,
    discovery_max_tokens: int | None = None,
    on_status: StatusCallback | None = None,
) -> str:
    if isinstance(discovery, str):
        discovery_context = discovery
        discovery_data = None
    else:
        discovery_context = discovery.to_context()
        discovery_data = discovery
    mdir = memory_dir(repo)
    mdir.mkdir(parents=True, exist_ok=True)

    head = await get_head(repo)
    last_head = _get_last_head(mdir)
    manifest_hash = await compute_manifest_hash(repo)
    last_manifest = _get_last_manifest_hash(mdir)

    if not force_full and manifest_hash and manifest_hash == last_manifest:
        logger.info("Knowledge is current (manifest=%s) — skipping compaction", manifest_hash[:12])
        return ""

    existing = _load_existing_knowledge(mdir)

    if not force_full and existing and last_head:
        changed_files, commit_log = await asyncio.gather(
            _get_changed_files(repo, last_head),
            _get_commit_log(repo, last_head),
        )
        if changed_files and commit_log:
            per_file_diffs, heavily_truncated = await _get_per_file_diffs(
                repo, last_head, changed_files
            )
            if heavily_truncated:
                logger.warning(
                    "Over half of diffs omitted (%d changed files) — falling back to full compaction",
                    len(changed_files),
                )
            elif per_file_diffs:
                return await _incremental_compact(
                    mdir,
                    model,
                    existing,
                    commit_log,
                    per_file_diffs,
                    head,
                    manifest_hash=manifest_hash,
                    max_tokens=discovery_max_tokens,
                    on_status=on_status,
                )
        logger.debug("Incremental compaction unavailable — falling back to full compaction")

    max_input = _max_input_chars(model)
    existing_text_len = len(_format_existing(existing))
    available = max_input - existing_text_len - 2000
    needs_multipass = (
        discovery_data is not None and available > 0 and len(discovery_context) > available
    )

    if needs_multipass:
        logger.info(
            "Discovery context (%d chars) exceeds budget (%d chars) — using multi-pass",
            len(discovery_context),
            available,
        )
        return await _multipass_compact(
            mdir,
            model,
            discovery_data,
            existing,
            head,
            manifest_hash=manifest_hash,
            max_tokens=compactor_max_tokens,
            max_input_chars=max_input,
            existing_text=_format_existing(existing),
            on_status=on_status,
        )

    return await _full_compact(
        mdir,
        model,
        discovery_context,
        existing,
        head,
        manifest_hash=manifest_hash,
        max_tokens=compactor_max_tokens,
        on_status=on_status,
    )


def _finalize_compact(
    raw: str | None,
    mdir: Path,
    existing: dict[str, str],
    head: str,
    *,
    manifest_hash: str = "",
    on_status: StatusCallback | None = None,
) -> str:
    if not raw:
        if existing:
            return _fallback_rebuild_index(
                mdir, existing, head, on_status, manifest_hash=manifest_hash
            )
        return ""

    try:
        data = _parse_response(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error("Failed to parse compaction response: %s", exc)
        if existing:
            return _fallback_rebuild_index(
                mdir, existing, head, on_status, manifest_hash=manifest_hash
            )
        return ""

    files = data.get("files", {})
    if not files:
        if existing:
            return _fallback_rebuild_index(
                mdir, existing, head, on_status, manifest_hash=manifest_hash
            )
        return ""

    _write_files(mdir, files, on_status=on_status)

    if on_status:
        on_status("Writing INDEX.md...")
    _write_index(mdir, _build_index(files), head, manifest_hash=manifest_hash)

    return str(mdir / INDEX_FILE)


async def _multipass_compact(
    mdir: Path,
    model: str,
    discovery: DiscoveryData,
    existing: dict[str, str],
    head: str,
    *,
    manifest_hash: str = "",
    max_tokens: int | None = None,
    max_input_chars: int | None = None,
    existing_text: str | None = None,
    on_status: StatusCallback | None = None,
) -> str:
    if on_status:
        on_status("Pass 1: Building structural map...")

    metadata = discovery.metadata_context
    pass1_msgs = [
        {"role": "user", "content": STRUCTURAL_MAP_PROMPT.format(metadata_context=metadata)}
    ]
    pass1_response = await acompletion(
        label="knowledge:compact:pass1",
        model=model,
        messages=pass1_msgs,
        temperature=0.0,
        max_tokens=safe_max_tokens(model, pass1_msgs, requested=4096),
    )

    pass1_raw = pass1_response.choices[0].message.content or ""
    try:
        pass1_data = _parse_response(pass1_raw)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Pass 1 parse failed — falling back to single-pass compaction")
        return await _full_compact(
            mdir,
            model,
            discovery.to_context(),
            existing,
            head,
            manifest_hash=manifest_hash,
            max_tokens=max_tokens,
            on_status=on_status,
        )

    structural_map = pass1_data.get("structural_map", "")
    priority_files = pass1_data.get("priority_files", [])

    if not structural_map:
        logger.warning("Pass 1 returned empty structural map — falling back to single-pass")
        return await _full_compact(
            mdir,
            model,
            discovery.to_context(),
            existing,
            head,
            manifest_hash=manifest_hash,
            max_tokens=max_tokens,
            on_status=on_status,
        )

    logger.info("Pass 1 complete: %d priority files identified", len(priority_files))

    if on_status:
        on_status(f"Pass 2: Reading {len(priority_files)} priority files...")

    mi = max_input_chars if max_input_chars is not None else _max_input_chars(model)
    et = existing_text if existing_text is not None else _format_existing(existing)
    overhead = len(structural_map) + len(et) + 4000
    source_budget = max(mi - overhead, 16_000)

    source_context = discovery.read_source_files(
        source_budget,
        priority_files=priority_files,
        on_status=on_status,
    )

    budget_chars = _knowledge_budget(model)
    pass2_prompt = PASS2_PROMPT.format(
        structural_map=structural_map,
        source_context=source_context,
        existing_knowledge=et,
        max_files=MAX_KNOWLEDGE_FILES,
        budget_chars=budget_chars,
    )

    if on_status:
        on_status("Pass 2: Generating knowledge files...")

    pass2_msgs = [{"role": "user", "content": pass2_prompt}]
    pass2_response = await acompletion(
        label="knowledge:compact:pass2",
        model=model,
        messages=pass2_msgs,
        temperature=0.0,
        max_tokens=safe_max_tokens(model, pass2_msgs, requested=max_tokens),
    )

    raw = pass2_response.choices[0].message.content
    return _finalize_compact(
        raw, mdir, existing, head, manifest_hash=manifest_hash, on_status=on_status
    )


async def _full_compact(
    mdir: Path,
    model: str,
    discovery_context: str,
    existing: dict[str, str],
    head: str,
    *,
    manifest_hash: str = "",
    max_tokens: int | None = None,
    on_status: StatusCallback | None = None,
) -> str:
    budget_chars = _knowledge_budget(model)
    max_input = _max_input_chars(model)

    existing_text = _format_existing(existing)
    available_for_discovery = max_input - len(existing_text) - 2000
    if available_for_discovery < len(discovery_context):
        logger.warning(
            "Discovery context (%d chars) exceeds budget (%d chars) — truncating",
            len(discovery_context),
            available_for_discovery,
        )
        discovery_context = _truncate_to_budget(discovery_context, available_for_discovery)

    prompt = INIT_PROMPT.format(
        discovery_context=discovery_context,
        existing_knowledge=existing_text,
        max_files=MAX_KNOWLEDGE_FILES,
        budget_chars=budget_chars,
    )

    if on_status:
        on_status("Compacting knowledge (full)...")

    msgs = [{"role": "user", "content": prompt}]
    response = await acompletion(
        label="knowledge:compact",
        model=model,
        messages=msgs,
        temperature=0.0,
        max_tokens=safe_max_tokens(model, msgs, requested=max_tokens),
    )

    raw = response.choices[0].message.content
    return _finalize_compact(
        raw, mdir, existing, head, manifest_hash=manifest_hash, on_status=on_status
    )


async def _incremental_compact(
    mdir: Path,
    model: str,
    existing: dict[str, str],
    commit_log: str,
    per_file_diffs: str,
    head: str,
    *,
    manifest_hash: str = "",
    max_tokens: int | None = None,
    on_status: StatusCallback | None = None,
) -> str:
    index_content = read_file(mdir / INDEX_FILE)
    if not index_content:
        index_content = _build_index(existing)

    budget_chars = _knowledge_budget(model)

    prompt = INCREMENTAL_PROMPT.format(
        commit_log=commit_log,
        per_file_diffs=per_file_diffs,
        index_content=index_content,
        budget_chars=budget_chars,
    )

    if on_status:
        on_status("Compacting knowledge (incremental)...")

    files_read: set[str] = set()
    tool_read_chars = 0

    async def _read_knowledge_handler(args: dict) -> ToolResult:
        nonlocal tool_read_chars
        filename = args.get("filename", "").strip()

        if filename in files_read:
            return ToolResult(content=f"Already loaded: {filename}")

        if tool_read_chars >= MAX_TOOL_READ_CHARS:
            return ToolResult(
                content="Read budget exceeded — produce output with files already loaded."
            )

        content = existing.get(filename, "")
        if not content:
            return ToolResult(content=f"File not found: {filename}")

        if on_status:
            on_status(f"Reading {filename}...")
        files_read.add(filename)
        tool_read_chars += len(content)
        return ToolResult(content=content)

    read_tool = Tool(
        name="read_knowledge_file",
        description="Read the full content of a knowledge file from the knowledge base.",
        parameters={
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Filename to read (e.g. 'architecture.md')",
                },
            },
            "required": ["filename"],
        },
        handler=_read_knowledge_handler,
    )

    agent = Agent(
        label="knowledge:incremental",
        model=model,
        tools=[read_tool],
        system_prompt=prompt,
        max_rounds=MAX_INCREMENTAL_ROUNDS,
        max_tokens=max_tokens,
        use_cache=False,
        enable_doom_loop=False,
        enable_masking=False,
        enable_compaction=False,
    )

    result = await agent.run(on_status=on_status)

    raw = result.last_content

    if not raw:
        logger.warning(
            "Incremental compaction produced no output after %d rounds", MAX_INCREMENTAL_ROUNDS
        )
        return ""

    try:
        data = _parse_response(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error("Failed to parse incremental compaction response: %s", exc)
        if existing:
            return _fallback_rebuild_index(mdir, existing, head, on_status)
        return ""

    files = data.get("files", {})

    written = _write_files(mdir, files, on_status=on_status)

    all_files = {**existing, **written}
    for name in files:
        if not files[name]:
            all_files.pop(name, None)

    if not all_files:
        return ""

    if on_status:
        on_status("Writing INDEX.md...")
    _write_index(mdir, _build_index(all_files), head, manifest_hash=manifest_hash)

    return str(mdir / INDEX_FILE)


def _extract_headers(content: str) -> tuple[list[str], list[str]]:
    h1s: list[str] = []
    h2s: list[str] = []
    in_fence = False
    for ln in content.strip().splitlines():
        if ln.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if ln.startswith("# ") and not ln.startswith("## "):
            h1s.append(ln.removeprefix("# ").strip())
        elif ln.startswith("## ") and not ln.startswith("### "):
            h2s.append(ln.removeprefix("## ").strip())
    return h1s, h2s


def _build_index(files: dict[str, str]) -> str:
    parts = ["# Knowledge Index\n"]
    for name in sorted(files):
        h1s, h2s = _extract_headers(files[name])
        title = h1s[0] if h1s else name.removesuffix(".md").replace("-", " ").title()
        if h2s:
            shown = h2s[:8]
            sections = ", ".join(shown)
            if len(h2s) > len(shown):
                sections += f", ... (+{len(h2s) - len(shown)} more)"
        else:
            sections = "(no sections)"
        parts.append(f"## {name}\n{title}: {sections}\n")
    return "\n".join(parts)


def rebuild_index(repo: Path) -> str:
    mdir = memory_dir(repo)
    if not mdir.exists():
        return ""
    existing = _load_existing_knowledge(mdir)
    if not existing:
        return ""
    head = _get_last_head(mdir) or "unknown"
    manifest = _get_last_manifest_hash(mdir)
    return _fallback_rebuild_index(mdir, existing, head, manifest_hash=manifest)


def load_index(repo: Path) -> str:
    return read_file(memory_dir(repo) / INDEX_FILE)


def load_knowledge_file(repo: Path, filename: str) -> str:
    if Path(filename).name != filename:
        return ""
    return read_file(memory_dir(repo) / filename)


def load_memory_files(repo: Path, filenames: list[str]) -> dict[str, str]:
    result = {}
    for name in filenames:
        content = load_knowledge_file(repo, name)
        if content:
            result[f"{SIGIL_DIR}/{MEMORY_DIR}/{name}"] = content
    return result


_memory_cache: dict[str, dict[str, str]] = {}
_memory_lock: asyncio.Lock | None = None


def _get_memory_lock() -> asyncio.Lock:
    global _memory_lock
    if _memory_lock is None:
        _memory_lock = asyncio.Lock()
    return _memory_lock


def clear_memory_cache() -> None:
    global _memory_lock
    _memory_cache.clear()
    _memory_lock = None


async def select_memory(
    repo: Path, model: str, task_description: str, *, max_tokens: int | None = None
) -> dict[str, str]:
    cache_key = str(repo.resolve())
    if cache_key in _memory_cache:
        return dict(_memory_cache[cache_key])

    async with _get_memory_lock():
        if cache_key in _memory_cache:
            return dict(_memory_cache[cache_key])

        index_md = load_index(repo)
        if not index_md:
            return {}

        prompt = (
            "You are an AI agent about to perform a task on a code repository. "
            "Read the knowledge index below and decide which files to load.\n\n"
            f"Your task: {task_description}\n\n"
            f"Knowledge index:\n\n{index_md}\n\n"
            "Use the load_memory_files tool to load the files you need. "
            f"Only load files that are relevant to your task — max {MAX_SELECTED_FILES} files."
        )

        msgs = [{"role": "user", "content": prompt}]
        response = await acompletion(
            label="knowledge:select",
            model=model,
            messages=msgs,
            tools=[SELECT_TOOL],
            tool_choice={"type": "function", "function": {"name": "load_memory_files"}},
            temperature=0.0,
            max_tokens=safe_max_tokens(model, msgs, tools=[SELECT_TOOL], requested=max_tokens),
        )

        choice = response.choices[0]
        if not choice.message.tool_calls:
            return {}

        tool_call = choice.message.tool_calls[0]
        try:
            args = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError:
            return {}

        filenames = args.get("filenames", [])
        if not isinstance(filenames, list):
            return {}

        if len(filenames) > MAX_SELECTED_FILES:
            logger.warning(
                "Knowledge selection requested %d files (max %d) — truncating",
                len(filenames),
                MAX_SELECTED_FILES,
            )
            filenames = filenames[:MAX_SELECTED_FILES]

        result = load_memory_files(repo, filenames)
        _memory_cache[cache_key] = result
        return dict(result)


async def is_knowledge_stale(repo: Path) -> bool:
    mdir = memory_dir(repo)
    last_manifest = _get_last_manifest_hash(mdir)
    if not last_manifest:
        return True
    current_manifest = await compute_manifest_hash(repo)
    return last_manifest != current_manifest
