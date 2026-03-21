import json
import re
from pathlib import Path

import litellm

from sigil.config import SIGIL_DIR, MEMORY_DIR
from sigil.llm import get_context_window
from sigil.utils import get_head, now_utc, read_file


INDEX_FILE = "INDEX.md"
MAX_KNOWLEDGE_FILES = 150
LLM_MAX_TOKENS = 8192
MAX_LLM_ROUNDS = 10

WRITE_TOOL = {
    "type": "function",
    "function": {
        "name": "write_knowledge_file",
        "description": (
            "Write a knowledge file to the project's knowledge base. "
            "Call this once per file. Each file should cover ONE topic deeply."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": (
                        "Filename ending in .md, lowercase, hyphens for multi-word. "
                        "e.g. 'project.md', 'architecture.md', 'error-handling.md'"
                    ),
                },
                "content": {
                    "type": "string",
                    "description": "Full markdown content of the knowledge file.",
                },
            },
            "required": ["filename", "content"],
        },
    },
}

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

COMPACT_PROMPT = """\
You are building a knowledge base for an AI agent that will analyze and improve
a code repository. Your job is to take raw discovery context and produce a set
of focused knowledge files that downstream agents can selectively load.

Here is the raw discovery context from the repository:

{discovery_context}

Here are the existing knowledge files (may be empty on first run):

{existing_knowledge}

Use the write_knowledge_file tool to create each file. Call it once per file.
Each file should cover ONE topic deeply and be self-contained — an agent reading
just that file should fully understand that aspect of the project.

Required files (always produce these):
- project.md — what the project is, who it's for, language, stack, how to build/test/lint
- architecture.md — modules, components, data flow, how the system fits together

Optional files (produce if there's enough content):
- patterns.md — coding conventions, naming patterns, error handling style, import conventions
- dependencies.md — external dependencies, their purpose, internal module dependency graph
- api.md — public APIs, interfaces, key data structures, function signatures
- testing.md — test framework, test patterns, coverage gaps, how tests are organized
- Any other topic-specific file that would help an agent understand this codebase

Rules:
- Each file should be thorough but concise — capture substance, not filler
- Up to {max_files} files total
- File names must be lowercase, use hyphens for multi-word names, end in .md
- Do NOT write working.md — that is managed separately
- Do NOT write INDEX.md — that is generated automatically
- If an existing file is still accurate, rewrite it with the same content
- If information is outdated, update or remove it
- NEVER include API keys, secrets, tokens, or credentials

CRITICAL: These files are committed to the repository and may be public. NEVER include
API keys, secrets, tokens, passwords, credentials, or any sensitive information.

Total budget for ALL files combined: ~{budget_chars} characters. Distribute budget
based on how much content each topic warrants.
"""

INDEX_PROMPT = """\
You are generating an INDEX.md file for a knowledge base. This index is the
BRAIN — it's the first thing an AI agent reads to decide which knowledge files
to load for its task.

Each entry MUST have a thorough, multi-line description. The agent must deeply
understand what each file contains WITHOUT reading it. Vague one-liners are
useless — be specific about what's in each file and when an agent should read it.

Here are the knowledge files and their contents:

{file_summaries}

Generate an INDEX.md with this structure:

```
# Knowledge Index

## <filename>
<thorough multi-line description of what's in this file, what topics it covers,
and when an agent should load it>

## <filename>
...
```

Rules:
- Every file gets an entry — only files that actually exist
- Descriptions must be 3-5 lines minimum — specific enough to decide relevance
- Include "Read this when..." guidance in each description
- Order files by importance (project.md first, then architecture, etc.)

Respond with ONLY the markdown content for INDEX.md. No JSON wrapping, no fences.
"""


def _memory_dir(repo: Path) -> Path:
    return repo / SIGIL_DIR / MEMORY_DIR


def _load_existing_knowledge(mdir: Path) -> dict[str, str]:
    knowledge = {}
    skip = {INDEX_FILE, "working.md"}
    for f in mdir.glob("*.md"):
        if f.name in skip:
            continue
        knowledge[f.name] = read_file(f)
    return knowledge


def _knowledge_budget(model: str) -> int:
    context_window = get_context_window(model)
    budget_tokens = max(context_window // 4, 4000)
    budget_chars = budget_tokens * 4
    return min(budget_chars, 200_000)


async def compact_knowledge(repo: Path, model: str, discovery_context: str) -> str:
    mdir = _memory_dir(repo)
    mdir.mkdir(parents=True, exist_ok=True)

    existing = _load_existing_knowledge(mdir)
    existing_section = ""
    if existing:
        parts = []
        for name, content in sorted(existing.items()):
            parts.append(f"### {name}\n```\n{content}\n```")
        existing_section = "\n\n".join(parts)
    else:
        existing_section = "(no existing knowledge files — first run)"

    budget_chars = _knowledge_budget(model)

    prompt = COMPACT_PROMPT.format(
        discovery_context=discovery_context,
        existing_knowledge=existing_section,
        max_files=MAX_KNOWLEDGE_FILES,
        budget_chars=budget_chars,
    )

    messages = [{"role": "user", "content": prompt}]
    files_written: dict[str, str] = {}

    for _ in range(MAX_LLM_ROUNDS):
        response = await litellm.acompletion(
            model=model,
            messages=messages,
            tools=[WRITE_TOOL],
            temperature=0.0,
            max_tokens=LLM_MAX_TOKENS,
        )

        choice = response.choices[0]

        if not choice.message.tool_calls:
            break

        messages.append(choice.message)

        for tool_call in choice.message.tool_calls:
            if tool_call.function.name != "write_knowledge_file":
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
                        "content": "Invalid JSON arguments.",
                    }
                )
                continue

            filename = args.get("filename", "").strip()
            content = args.get("content", "").strip()

            if not filename or not content:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": "Missing filename or content.",
                    }
                )
                continue

            if not filename.endswith(".md"):
                filename += ".md"

            if filename in (INDEX_FILE, "working.md"):
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": f"Cannot write {filename} — managed separately.",
                    }
                )
                continue

            (mdir / filename).write_text(content + "\n")
            files_written[filename] = content

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": f"Written {filename} ({len(content)} chars).",
                }
            )

        if choice.finish_reason == "stop":
            break

    if not files_written:
        return ""

    head = await get_head(repo)
    await _generate_index(repo, model, head)

    return str(mdir / INDEX_FILE)


async def _generate_index(repo: Path, model: str, head: str) -> None:
    mdir = _memory_dir(repo)
    all_files = {}
    for f in sorted(mdir.glob("*.md")):
        if f.name == INDEX_FILE:
            continue
        all_files[f.name] = read_file(f)

    if not all_files:
        return

    parts = []
    for name, content in all_files.items():
        parts.append(f"### {name}\n{content}")
    file_summaries = "\n\n".join(parts)

    prompt = INDEX_PROMPT.format(file_summaries=file_summaries)
    response = await litellm.acompletion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=4096,
    )
    index_body = response.choices[0].message.content

    meta_line = f"<!-- head: {head} | updated: {now_utc()} -->\n\n"
    (mdir / INDEX_FILE).write_text(meta_line + index_body.strip() + "\n")


def load_index(repo: Path) -> str:
    return read_file(_memory_dir(repo) / INDEX_FILE)


def load_knowledge_file(repo: Path, filename: str) -> str:
    return read_file(_memory_dir(repo) / filename)


def load_knowledge_files(repo: Path, filenames: list[str]) -> dict[str, str]:
    result = {}
    for name in filenames:
        content = load_knowledge_file(repo, name)
        if content:
            result[name] = content
    return result


async def select_knowledge(repo: Path, model: str, task_description: str) -> dict[str, str]:
    index_md = load_index(repo)
    if not index_md:
        return {}

    prompt = (
        "You are an AI agent about to perform a task on a code repository. "
        "Read the knowledge index below and decide which files to load.\n\n"
        f"Your task: {task_description}\n\n"
        f"Knowledge index:\n\n{index_md}\n\n"
        "Use the load_knowledge_files tool to load the files you need. "
        "Only load files that are relevant to your task."
    )

    response = await litellm.acompletion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        tools=[SELECT_TOOL],
        tool_choice={"type": "function", "function": {"name": "load_knowledge_files"}},
        temperature=0.0,
        max_tokens=1024,
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

    return load_knowledge_files(repo, filenames)


async def is_knowledge_stale(repo: Path) -> bool:
    index_path = _memory_dir(repo) / INDEX_FILE
    if not index_path.exists():
        return True
    content = read_file(index_path)
    match = re.search(r"head:\s*([a-f0-9]+)", content)
    if not match:
        return True
    return match.group(1) != await get_head(repo)
