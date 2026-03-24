import asyncio
import json
import logging
import re
from pathlib import Path

from sigil.config import SIGIL_DIR, MEMORY_DIR
from sigil.llm import acompletion, get_context_window, get_max_output_tokens
from sigil.utils import StatusCallback, arun, get_head, now_utc, read_file


log = logging.getLogger(__name__)

INDEX_FILE = "INDEX.md"
MAX_KNOWLEDGE_FILES = 150
RESERVED_FILES = frozenset({INDEX_FILE, "working.md"})
CHARS_PER_TOKEN = 4
PROMPT_OVERHEAD_TOKENS = 2000
MAX_SELECTED_FILES = 5

SELECT_TOOL = {
    "type": "function",
    "function": {
        "name": "load_knowledge_files",
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

READ_KNOWLEDGE_TOOL = {
    "type": "function",
    "function": {
        "name": "read_knowledge_file",
        "description": "Read the full content of a knowledge file from the knowledge base.",
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Filename to read (e.g. 'architecture.md')",
                },
            },
            "required": ["filename"],
        },
    },
}

INIT_PROMPT = """\
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

Rules for files:
- Each file covers ONE topic deeply and is self-contained
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

MAX_DIFF_CHARS_PER_FILE = 10_000
MAX_TOTAL_DIFF_CHARS = 100_000
MAX_INCREMENTAL_ROUNDS = 3
MAX_CONCURRENT_DIFFS = 20
MAX_TOOL_READ_CHARS = 100_000


def _memory_dir(repo: Path) -> Path:
    return repo / SIGIL_DIR / MEMORY_DIR


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
        return s.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")


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

    log.warning("Repaired truncated JSON — salvaged %d files", len(files))
    return {"files": files}


def _get_last_head(mdir: Path) -> str:
    index_path = mdir / INDEX_FILE
    if not index_path.exists():
        return ""
    content = read_file(index_path)
    match = re.search(r"head:\s*([a-f0-9]+)", content)
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


async def _get_per_file_diffs(repo: Path, last_head: str, changed_files: list[str]) -> str:
    sem = asyncio.Semaphore(MAX_CONCURRENT_DIFFS)
    results = await asyncio.gather(
        *[_diff_one_file(repo, last_head, f, sem) for f in changed_files]
    )

    parts = []
    total_chars = 0
    for filepath, diff_text in results:
        if not diff_text:
            continue
        if total_chars >= MAX_TOTAL_DIFF_CHARS:
            parts.append(f"\n--- {filepath} ---\n(diff omitted — total budget exceeded)")
            continue
        if len(diff_text) > MAX_DIFF_CHARS_PER_FILE:
            diff_text = diff_text[:MAX_DIFF_CHARS_PER_FILE] + "\n... (truncated)"
        section = f"\n--- {filepath} ---\n{diff_text}"
        parts.append(section)
        total_chars += len(section)

    return "\n".join(parts)


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
            log.warning("Skipping invalid/reserved file: %s", raw_filename)
            continue
        if not content:
            target = mdir / filename
            if target.exists():
                target.unlink()
                log.info("Deleted knowledge file: %s", filename)
            continue
        if on_status:
            on_status(f"Writing {filename}...")
        (mdir / filename).write_text(content.strip() + "\n")
        written[filename] = content
    return written


def _write_index(mdir: Path, index_content: str, head: str) -> None:
    meta_line = f"<!-- head: {head} | updated: {now_utc()} -->\n\n"
    (mdir / INDEX_FILE).write_text(meta_line + index_content.strip() + "\n")


def _fallback_rebuild_index(
    mdir: Path,
    existing: dict[str, str],
    head: str,
    on_status: StatusCallback | None = None,
) -> str:
    log.info("Rebuilding index from %d existing files (LLM output unusable)", len(existing))
    if on_status:
        on_status("Writing INDEX.md...")
    _write_index(mdir, _build_index(existing), head)
    return str(mdir / INDEX_FILE)


async def compact_knowledge(
    repo: Path, model: str, discovery_context: str, *, on_status: StatusCallback | None = None
) -> str:
    mdir = _memory_dir(repo)
    mdir.mkdir(parents=True, exist_ok=True)

    head = await get_head(repo)
    last_head = _get_last_head(mdir)

    if head and head == last_head:
        log.info("Knowledge is current (HEAD=%s) — skipping compaction", head[:8])
        return ""

    existing = _load_existing_knowledge(mdir)

    if existing and last_head:
        changed_files, commit_log = await asyncio.gather(
            _get_changed_files(repo, last_head),
            _get_commit_log(repo, last_head),
        )
        if changed_files and commit_log:
            per_file_diffs = await _get_per_file_diffs(repo, last_head, changed_files)
            if per_file_diffs:
                return await _incremental_compact(
                    mdir, model, existing, commit_log, per_file_diffs, head, on_status=on_status
                )
        log.warning("Incremental compaction unavailable — falling back to full compaction")

    return await _full_compact(mdir, model, discovery_context, existing, head, on_status=on_status)


async def _full_compact(
    mdir: Path,
    model: str,
    discovery_context: str,
    existing: dict[str, str],
    head: str,
    *,
    on_status: StatusCallback | None = None,
) -> str:
    budget_chars = _knowledge_budget(model)
    max_input = _max_input_chars(model)

    existing_text = _format_existing(existing)
    available_for_discovery = max_input - len(existing_text) - 2000
    if available_for_discovery < len(discovery_context):
        log.warning(
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

    response = await acompletion(
        label="knowledge:compact",
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=get_max_output_tokens(model),
    )

    raw = response.choices[0].message.content
    if not raw:
        return ""

    try:
        data = _parse_response(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        log.error("Failed to parse compaction response: %s", exc)
        if existing:
            return _fallback_rebuild_index(mdir, existing, head, on_status)
        return ""

    files = data.get("files", {})

    if not files:
        if existing:
            return _fallback_rebuild_index(mdir, existing, head, on_status)
        return ""

    _write_files(mdir, files, on_status=on_status)

    if on_status:
        on_status("Writing INDEX.md...")
    _write_index(mdir, _build_index(files), head)

    return str(mdir / INDEX_FILE)


async def _incremental_compact(
    mdir: Path,
    model: str,
    existing: dict[str, str],
    commit_log: str,
    per_file_diffs: str,
    head: str,
    *,
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

    messages: list[dict] = [{"role": "user", "content": prompt}]
    files_read: set[str] = set()
    tool_read_chars = 0
    response = None

    for _ in range(MAX_INCREMENTAL_ROUNDS):
        if on_status:
            on_status("Generating...")
        response = await acompletion(
            label="knowledge:incremental",
            model=model,
            messages=messages,
            tools=[READ_KNOWLEDGE_TOOL],
            temperature=0.0,
            max_tokens=get_max_output_tokens(model),
        )

        choice = response.choices[0]

        if not choice.message.tool_calls:
            break

        messages.append(choice.message)

        for tool_call in choice.message.tool_calls:
            if tool_call.function.name != "read_knowledge_file":
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": "Unknown tool.",
                    }
                )
                continue

            try:
                args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": "Invalid arguments.",
                    }
                )
                continue

            filename = args.get("filename", "").strip()

            if filename in files_read:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": f"Already loaded: {filename}",
                    }
                )
                continue

            if tool_read_chars >= MAX_TOOL_READ_CHARS:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": "Read budget exceeded — produce output with files already loaded.",
                    }
                )
                continue

            content = existing.get(filename, "")
            if not content:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": f"File not found: {filename}",
                    }
                )
            else:
                if on_status:
                    on_status(f"Reading {filename}...")
                files_read.add(filename)
                tool_read_chars += len(content)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": content,
                    }
                )

    if response is None:
        return ""

    raw = response.choices[0].message.content or ""

    if not raw:
        log.warning(
            "Incremental compaction produced no output after %d rounds", MAX_INCREMENTAL_ROUNDS
        )
        return ""

    try:
        data = _parse_response(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        log.error("Failed to parse incremental compaction response: %s", exc)
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
    _write_index(mdir, _build_index(all_files), head)

    return str(mdir / INDEX_FILE)


def _extract_h1s(content: str) -> list[str]:
    h1s = []
    in_fence = False
    for ln in content.strip().splitlines():
        if ln.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if ln.startswith("# ") and not ln.startswith("## "):
            h1s.append(ln.lstrip("#").strip())
    return h1s


def _build_index(files: dict[str, str]) -> str:
    parts = ["# Knowledge Index\n"]
    for name in sorted(files):
        h1s = _extract_h1s(files[name])
        if h1s:
            header_list = "\n".join(f"- {h}" for h in h1s)
            parts.append(f"## {name}\n{header_list}\n")
        else:
            parts.append(f"## {name}\n- (no headers)\n")
    return "\n".join(parts)


def load_index(repo: Path) -> str:
    return read_file(_memory_dir(repo) / INDEX_FILE)


def load_knowledge_file(repo: Path, filename: str) -> str:
    if Path(filename).name != filename:
        return ""
    return read_file(_memory_dir(repo) / filename)


def load_knowledge_files(repo: Path, filenames: list[str]) -> dict[str, str]:
    result = {}
    for name in filenames:
        content = load_knowledge_file(repo, name)
        if content:
            result[name] = content
    return result


_knowledge_cache: dict[str, dict[str, str]] = {}
_knowledge_lock: asyncio.Lock | None = None


def _get_knowledge_lock() -> asyncio.Lock:
    global _knowledge_lock
    if _knowledge_lock is None:
        _knowledge_lock = asyncio.Lock()
    return _knowledge_lock


def clear_knowledge_cache() -> None:
    global _knowledge_lock
    _knowledge_cache.clear()
    _knowledge_lock = None


async def select_knowledge(repo: Path, model: str, task_description: str) -> dict[str, str]:
    cache_key = str(repo.resolve())
    if cache_key in _knowledge_cache:
        return dict(_knowledge_cache[cache_key])

    async with _get_knowledge_lock():
        if cache_key in _knowledge_cache:
            return dict(_knowledge_cache[cache_key])

        index_md = load_index(repo)
        if not index_md:
            return {}

        prompt = (
            "You are an AI agent about to perform a task on a code repository. "
            "Read the knowledge index below and decide which files to load.\n\n"
            f"Your task: {task_description}\n\n"
            f"Knowledge index:\n\n{index_md}\n\n"
            "Use the load_knowledge_files tool to load the files you need. "
            f"Only load files that are relevant to your task — max {MAX_SELECTED_FILES} files."
        )

        response = await acompletion(
            label="knowledge:select",
            model=model,
            messages=[{"role": "user", "content": prompt}],
            tools=[SELECT_TOOL],
            tool_choice={"type": "function", "function": {"name": "load_knowledge_files"}},
            temperature=0.0,
            max_tokens=get_max_output_tokens(model),
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
            log.warning(
                "Knowledge selection requested %d files (max %d) — truncating",
                len(filenames),
                MAX_SELECTED_FILES,
            )
            filenames = filenames[:MAX_SELECTED_FILES]

        result = load_knowledge_files(repo, filenames)
        _knowledge_cache[cache_key] = result
        return dict(result)


async def is_knowledge_stale(repo: Path) -> bool:
    index_path = _memory_dir(repo) / INDEX_FILE
    if not index_path.exists():
        return True
    content = read_file(index_path)
    match = re.search(r"head:\s*([a-f0-9]+)", content)
    if not match:
        return True
    return match.group(1) != await get_head(repo)
