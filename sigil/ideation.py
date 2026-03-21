import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import litellm
import yaml

from sigil.config import SIGIL_DIR, Config
from sigil.knowledge import select_knowledge
from sigil.memory import load_working
from sigil.utils import now_utc


IDEAS_DIR = "ideas"
LLM_MAX_TOKENS = 8192
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
                        "Detailed description of the feature: what it does, "
                        "how it fits into the project, and a rough implementation approach."
                    ),
                },
                "rationale": {
                    "type": "string",
                    "description": (
                        "Why this makes sense for THIS project specifically. "
                        "Reference actual code, gaps, or patterns."
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


def _run_ideation_pass(
    model: str,
    prompt: str,
    temperature: float,
    max_ideas: int,
) -> list[FeatureIdea]:
    messages: list[dict] = [{"role": "user", "content": prompt}]
    ideas: list[FeatureIdea] = []
    next_priority = 1

    for _ in range(MAX_LLM_ROUNDS):
        response = litellm.completion(
            model=model,
            messages=messages,
            tools=[REPORT_TOOL],
            temperature=temperature,
            max_tokens=LLM_MAX_TOKENS,
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

            idea = FeatureIdea(
                title=str(args.get("title", "")),
                description=str(args.get("description", "")),
                rationale=str(args.get("rationale", "")),
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


def ideate(repo: Path, config: Config) -> list[FeatureIdea]:
    if config.boldness == "conservative":
        return []

    working_md = load_working(repo)
    existing = _load_existing_ideas(repo, ttl_days=config.idea_ttl_days)

    task_desc = (
        "Propose new feature ideas and improvements for the repository. "
        f"Boldness: {config.boldness}."
    )
    knowledge_files = select_knowledge(repo, config.model, task_desc)
    knowledge_context = ""
    if knowledge_files:
        parts = []
        for name, content in knowledge_files.items():
            parts.append(f"### {name}\n{content}")
        knowledge_context = "\n\n".join(parts)

    max_ideas = config.max_ideas_per_run
    half = math.ceil(max_ideas / 2)

    low_temp, high_temp = TEMP_RANGES.get(config.boldness, TEMP_RANGES["balanced"])

    prompt = IDEATION_PROMPT.format(
        boldness=config.boldness,
        boldness_instructions=BOLDNESS_INSTRUCTIONS.get(
            config.boldness, BOLDNESS_INSTRUCTIONS["balanced"]
        ),
        knowledge_context=knowledge_context or "(no knowledge files yet)",
        working_memory=working_md or "(no prior runs)",
        existing_ideas=_format_existing_ideas(existing),
        max_ideas=half,
    )

    focused = _run_ideation_pass(config.model, prompt, low_temp, half)

    creative_prompt = prompt.replace(
        f"Report at most {half} ideas.",
        f"Report at most {max_ideas - half} ideas.",
    )
    creative_prompt += (
        "\n\nThink more creatively and expansively. Go beyond obvious improvements. "
        "Propose ideas that are surprising, novel, or unconventional."
    )

    creative = _run_ideation_pass(config.model, creative_prompt, high_temp, max_ideas - half)

    combined = focused + creative
    combined.sort(key=lambda i: i.priority)
    return _deduplicate(combined)[:max_ideas]


def save_ideas(repo: Path, ideas: list[FeatureIdea]) -> list[Path]:
    return [_save_idea(repo, idea) for idea in ideas]


REVIEW_TOOL = {
    "type": "function",
    "function": {
        "name": "review_idea",
        "description": (
            "Review a proposed feature idea and either approve it, adjust its "
            "disposition, or veto it. Call once per idea."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "idea_index": {
                    "type": "integer",
                    "description": "Zero-based index of the idea in the list.",
                },
                "action": {
                    "type": "string",
                    "enum": ["approve", "adjust", "veto"],
                    "description": (
                        "approve = keep as-is. "
                        "adjust = change disposition (e.g. pr -> issue). "
                        "veto = remove entirely."
                    ),
                },
                "new_disposition": {
                    "type": "string",
                    "enum": ["pr", "issue"],
                    "description": "New disposition (only required when action is 'adjust').",
                },
                "reason": {
                    "type": "string",
                    "description": "Brief reason for the decision.",
                },
            },
            "required": ["idea_index", "action", "reason"],
        },
    },
}

IDEA_VALIDATION_PROMPT = """\
You are a senior engineer reviewing feature ideas proposed by Sigil's ideation agent.
Your job is to evaluate each idea for value, feasibility, and originality.

Here is the project knowledge:

{knowledge_context}

Here is Sigil's working memory:

{working_memory}

Here are the proposed ideas:

{ideas_list}

Use the review_idea tool for each idea. You must review every idea.
- "approve" if the idea is valuable, feasible, and specific to this project
- "adjust" if the idea is good but the disposition is wrong (e.g. a complex idea marked as "pr" should be "issue")
- "veto" if the idea is:
  - Generic advice that applies to any project
  - Already implemented or in progress
  - Too vague to act on
  - Not valuable enough to pursue
  - Duplicates an existing idea

Be selective. Only approve ideas worth spending engineering time on.
"""


def _format_ideas(ideas: list[FeatureIdea]) -> str:
    lines = []
    for i, idea in enumerate(ideas):
        lines.append(
            f"[{i}] #{idea.priority} [{idea.disposition}] {idea.title} ({idea.complexity})\n"
            f"    {idea.description}\n"
            f"    Rationale: {idea.rationale}"
        )
    return "\n\n".join(lines)


def validate_ideas(repo: Path, config: Config, ideas: list[FeatureIdea]) -> list[FeatureIdea]:
    if not ideas:
        return []

    working_md = load_working(repo)

    task_desc = "Review and validate proposed feature ideas."
    knowledge_files = select_knowledge(repo, config.model, task_desc)
    knowledge_context = ""
    if knowledge_files:
        parts = []
        for name, content in knowledge_files.items():
            parts.append(f"### {name}\n{content}")
        knowledge_context = "\n\n".join(parts)

    prompt = IDEA_VALIDATION_PROMPT.format(
        knowledge_context=knowledge_context or "(no knowledge files yet)",
        working_memory=working_md or "(no prior runs)",
        ideas_list=_format_ideas(ideas),
    )

    messages: list[dict] = [{"role": "user", "content": prompt}]
    decisions: dict[int, tuple[str, str | None, str]] = {}

    for _ in range(MAX_LLM_ROUNDS):
        response = litellm.completion(
            model=config.model,
            messages=messages,
            tools=[REVIEW_TOOL],
            temperature=0.0,
            max_tokens=4096,
        )

        choice = response.choices[0]

        if not choice.message.tool_calls:
            break

        messages.append(choice.message)

        for tool_call in choice.message.tool_calls:
            if tool_call.function.name != "review_idea":
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

            idx = args.get("idea_index")
            if not isinstance(idx, int) or idx < 0 or idx >= len(ideas):
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": f"Invalid idea_index: {idx}",
                    }
                )
                continue

            action = str(args.get("action", "approve"))
            new_disp = args.get("new_disposition")
            reason = str(args.get("reason", ""))

            decisions[idx] = (action, new_disp, reason)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": f"Reviewed [{idx}]: {action}",
                }
            )

        if choice.finish_reason == "stop":
            break

    validated: list[FeatureIdea] = []
    for i, idea in enumerate(ideas):
        if i not in decisions:
            validated.append(idea)
            continue

        action, new_disp, reason = decisions[i]

        if action == "veto":
            continue

        if action == "adjust" and new_disp in ("pr", "issue"):
            validated.append(
                FeatureIdea(
                    title=idea.title,
                    description=idea.description,
                    rationale=idea.rationale,
                    complexity=idea.complexity,
                    disposition=new_disp,
                    priority=idea.priority,
                )
            )
        else:
            validated.append(idea)

    return validated
