import asyncio
import json
import logging
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from sigil.agent_config import AgentConfigResult
from sigil.config import DEFAULT_CHEAP_MODEL, SIGIL_DIR, Config
from sigil.llm import (
    acompletion,
    cacheable_message,
    compact_messages,
    detect_doom_loop,
    get_agent_output_cap,
    mask_old_tool_outputs,
)
from sigil.knowledge import select_knowledge
from sigil.memory import load_working
from sigil.utils import StatusCallback, now_utc

log = logging.getLogger(__name__)


IDEAS_DIR = "ideas"
MAX_LLM_ROUNDS = 10

TEMP_RANGES = {
    "balanced": (0.1, 0.5),
    "bold": (0.2, 0.7),
    "experimental": (0.3, 0.9),
}


@dataclass(frozen=True)
class FeatureIdea:
    title: str
    description: str
    rationale: str
    complexity: str
    disposition: str
    priority: int


REPORT_TOOL = {
    "type": "function",
    "function": {
        "name": "report_idea",
        "description": (
            "Propose a single feature idea for the repository. "
            "Call once per idea, in priority order (1 = highest). "
            "Only propose ideas that are specific to THIS repository."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Short, specific title for the feature idea.",
                },
                "description": {
                    "type": "string",
                    "description": (
                        "Brief description (2-4 sentences max): what it does and "
                        "a rough implementation approach. Be concise."
                    ),
                },
                "rationale": {
                    "type": "string",
                    "description": (
                        "One or two sentences: why this matters for THIS project. "
                        "Reference actual code or gaps."
                    ),
                },
                "complexity": {
                    "type": "string",
                    "enum": ["small", "medium", "large"],
                    "description": (
                        "small = a few lines/one file. "
                        "medium = multiple files, moderate effort. "
                        "large = significant new functionality or architecture change."
                    ),
                },
                "disposition": {
                    "type": "string",
                    "enum": ["pr", "issue"],
                    "description": (
                        "pr = small and safe enough for an AI agent to auto-implement. "
                        "issue = needs human review or is too complex for auto-implementation."
                    ),
                },
                "priority": {
                    "type": "integer",
                    "description": "Priority rank, 1 = highest. No duplicates.",
                },
            },
            "required": [
                "title",
                "description",
                "rationale",
                "complexity",
                "disposition",
                "priority",
            ],
        },
    },
}

BOLDNESS_INSTRUCTIONS = {
    "conservative": None,
    "balanced": (
        "Propose only obvious gaps and low-risk additions: missing error handling, "
        "missing CLI flags, incomplete implementations, straightforward quality-of-life "
        "improvements. Stay close to what already exists."
    ),
    "bold": (
        "Propose ambitious but scoped features: new commands, integrations, "
        "significant new behavior, developer experience improvements. "
        "Ideas should be achievable in a single PR or a small series."
    ),
    "experimental": (
        "Propose anything that could make this project significantly better. "
        "Cross-cutting ideas, architectural shifts, moonshot features, novel "
        "approaches. No idea is too ambitious — but it must be specific, not vague."
    ),
}

IDEATION_PROMPT = """\
You are Sigil, an autonomous repo improvement agent. Your job is to study this
repository deeply and propose feature ideas that would make it meaningfully better.

This is NOT about finding bugs or maintenance issues — that's handled separately.
You are proposing NEW FUNCTIONALITY, improvements, and capabilities.

Boldness: {boldness}
{boldness_instructions}

Here is the project knowledge (selected based on relevance to this task):

{knowledge_context}

Here are the repo's coding conventions from its agent config files (respect these):

{repo_conventions}

Here is what Sigil has already done in prior runs:

{working_memory}

Here are ideas that have already been proposed (do NOT re-propose these):

{existing_ideas}

How to reason:
1. What does this project do? What is its purpose and audience?
2. What does it do well? What are obvious gaps?
3. What would a senior engineer add next?
4. What patterns exist in similar projects that this one lacks?
5. What would make this project 10x better for its users?

Use the report_idea tool for each idea. Call it once per idea, in priority order
(priority 1 = most impactful). Report at most {max_ideas} ideas.

Rules:
- Every idea must be specific to THIS repository — no generic advice
- Reference actual code, actual gaps, actual architecture in your rationale
- Small+confident ideas should have enough detail to implement
- Do not re-propose ideas listed in the "already proposed" section
- If nothing meaningful comes to mind, do not call the tool at all
"""


def _ideas_dir(repo: Path) -> Path:
    return repo / SIGIL_DIR / IDEAS_DIR


def _load_existing_ideas(repo: Path, ttl_days: int = 180) -> list[dict]:
    idir = _ideas_dir(repo)
    if not idir.exists():
        return []

    now = datetime.now(timezone.utc)
    ideas = []
    for f in sorted(idir.glob("*.md")):
        content = f.read_text()
        if not content.startswith("---"):
            continue
        parts = content.split("---", 2)
        if len(parts) < 3:
            continue
        try:
            meta = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            continue

        created = meta.get("created", "")
        if created and ttl_days > 0:
            try:
                created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                age_days = (now - created_dt).days
                if age_days > ttl_days:
                    f.unlink()
                    continue
            except (ValueError, TypeError):
                pass

        meta["filename"] = f.name
        ideas.append(meta)
    return ideas


def _format_existing_ideas(ideas: list[dict]) -> str:
    if not ideas:
        return "(no ideas proposed yet — this is the first ideation run)"
    lines = []
    for idea in ideas:
        status = idea.get("status", "open")
        title = idea.get("title", "?")
        summary = idea.get("summary", "")
        complexity = idea.get("complexity", "?")
        entry = f"- [{status}] {title} ({complexity})"
        if summary:
            entry += f" — {summary}"
        lines.append(entry)
    return "\n".join(lines)


def _slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:60]


def _save_idea(repo: Path, idea: FeatureIdea) -> Path:
    idir = _ideas_dir(repo)
    idir.mkdir(parents=True, exist_ok=True)

    slug = _slug(idea.title)
    path = idir / f"{slug}.md"

    counter = 2
    while path.exists():
        path = idir / f"{slug}-{counter}.md"
        counter += 1

    summary = idea.description[:120].replace("\n", " ").strip()

    meta = {
        "title": idea.title,
        "summary": summary,
        "status": "open",
        "complexity": idea.complexity,
        "disposition": idea.disposition,
        "priority": idea.priority,
        "created": now_utc(),
    }
    front = yaml.dump(meta, default_flow_style=False, sort_keys=False).strip()
    body = (
        f"# {idea.title}\n\n"
        f"## Description\n\n{idea.description}\n\n"
        f"## Rationale\n\n{idea.rationale}\n"
    )
    path.write_text(f"---\n{front}\n---\n\n{body}\n")
    return path


async def _run_ideation_pass(
    model: str,
    prompt: str,
    temperature: float,
    max_ideas: int,
    *,
    on_status: StatusCallback | None = None,
) -> list[FeatureIdea]:
    messages: list[dict] = [cacheable_message(model, prompt)]
    ideas: list[FeatureIdea] = []
    next_priority = 1

    all_tools = [REPORT_TOOL]

    for _ in range(MAX_LLM_ROUNDS):
        if detect_doom_loop(messages):
            log.warning("Doom loop detected in ideator — breaking")
            break
        mask_old_tool_outputs(messages)
        await compact_messages(messages, DEFAULT_CHEAP_MODEL)
        if on_status:
            on_status("Generating...")
        response = await acompletion(
            label="ideation",
            model=model,
            messages=messages,
            tools=all_tools,
            temperature=temperature,
            max_tokens=get_agent_output_cap("ideator", model),
        )

        choice = response.choices[0]

        if not choice.message.tool_calls:
            break

        messages.append(choice.message)

        for tool_call in choice.message.tool_calls:
            if tool_call.function.name != "report_idea":
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

            complexity = str(args.get("complexity", "medium"))
            if complexity not in ("small", "medium", "large"):
                complexity = "medium"

            disposition = str(args.get("disposition", "issue"))
            if disposition not in ("pr", "issue"):
                disposition = "issue"

            if on_status:
                on_status(f"Proposing idea: {args.get('title', '')[:60]}...")

            idea = FeatureIdea(
                title=str(args.get("title", ""))[:120],
                description=str(args.get("description", ""))[:500],
                rationale=str(args.get("rationale", ""))[:300],
                complexity=complexity,
                disposition=disposition,
                priority=int(args.get("priority", next_priority)),
            )
            ideas.append(idea)
            next_priority = max(next_priority, idea.priority) + 1

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": f"Recorded: [{idea.disposition}] {idea.title} ({idea.complexity})",
                }
            )

        if choice.finish_reason == "stop":
            break

    ideas.sort(key=lambda i: i.priority)
    return ideas[:max_ideas]


def _deduplicate(ideas: list[FeatureIdea]) -> list[FeatureIdea]:
    seen: set[str] = set()
    unique: list[FeatureIdea] = []
    for idea in ideas:
        key = _slug(idea.title)
        if key not in seen:
            seen.add(key)
            unique.append(idea)
    return unique


async def ideate(
    repo: Path,
    config: Config,
    *,
    agent_config: AgentConfigResult | None = None,
    on_status: StatusCallback | None = None,
) -> list[FeatureIdea]:
    if config.boldness == "conservative":
        return []

    working_md = load_working(repo)
    existing = _load_existing_ideas(repo, ttl_days=config.idea_ttl_days)

    task_desc = (
        "Propose new feature ideas and improvements for the repository. "
        f"Boldness: {config.boldness}."
    )
    if on_status:
        on_status("Selecting relevant knowledge...")
    model = config.model_for("ideator")
    knowledge_files = await select_knowledge(repo, config.model_for("selector"), task_desc)
    knowledge_context = ""
    if knowledge_files:
        parts = []
        for name, content in knowledge_files.items():
            parts.append(f"### {name}\n{content}")
        knowledge_context = "\n\n".join(parts)

    repo_conventions = "(none detected)"
    if agent_config and agent_config.has_config:
        repo_conventions = agent_config.format_for_prompt()

    max_ideas = config.max_ideas_per_run
    half = math.ceil(max_ideas / 2)

    low_temp, high_temp = TEMP_RANGES.get(config.boldness, TEMP_RANGES["balanced"])

    prompt = IDEATION_PROMPT.format(
        boldness=config.boldness,
        boldness_instructions=BOLDNESS_INSTRUCTIONS.get(
            config.boldness, BOLDNESS_INSTRUCTIONS["balanced"]
        ),
        knowledge_context=knowledge_context or "(no knowledge files yet)",
        repo_conventions=repo_conventions,
        working_memory=working_md or "(no prior runs)",
        existing_ideas=_format_existing_ideas(existing),
        max_ideas=half,
    )

    creative_prompt = prompt.replace(
        f"Report at most {half} ideas.",
        f"Report at most {max_ideas - half} ideas.",
    )
    creative_prompt += (
        "\n\nThink more creatively and expansively. Go beyond obvious improvements. "
        "Propose ideas that are surprising, novel, or unconventional."
    )

    focused, creative = await asyncio.gather(
        _run_ideation_pass(
            model,
            prompt,
            low_temp,
            half,
            on_status=on_status,
        ),
        _run_ideation_pass(
            model,
            creative_prompt,
            high_temp,
            max_ideas - half,
            on_status=on_status,
        ),
    )

    combined = focused + creative
    combined.sort(key=lambda i: i.priority)
    return _deduplicate(combined)[:max_ideas]


def save_ideas(repo: Path, ideas: list[FeatureIdea]) -> list[Path]:
    return [_save_idea(repo, idea) for idea in ideas]
