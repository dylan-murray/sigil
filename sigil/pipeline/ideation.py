import asyncio
import logging
import math
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from sigil.core.agent import Agent, Tool, ToolResult
from sigil.core.config import SIGIL_DIR, Config
from sigil.core.instructions import Instructions
from sigil.core.utils import StatusCallback, now_utc
from sigil.pipeline.knowledge import select_memory
from sigil.pipeline.models import FeatureIdea as FeatureIdea
from sigil.pipeline.prompts import (
    IDEATION_CONTEXT_PROMPT,
    IDEATOR_BOLDNESS,
    IDEATOR_SYSTEM_PROMPT,
)
from sigil.state.memory import load_working

logger = logging.getLogger(__name__)


IDEAS_DIR = "ideas"
MAX_LLM_ROUNDS = 10

TEMP_RANGES = {
    "balanced": (0.1, 0.5),
    "bold": (0.2, 0.7),
    "experimental": (0.3, 0.9),
}


REPORT_IDEA_PARAMS = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": "Short, specific title for the feature idea.",
        },
        "description": {
            "type": "string",
            "description": (
                "Detailed description (max 2000 chars): what it does, why it matters, "
                "and a concrete implementation approach (files to change, "
                "functions to add, data flow). This text becomes the executor's "
                "instructions — be specific enough that an engineer can implement "
                "from this alone."
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
}


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


def load_open_ideas(repo: Path, ttl_days: int = 180) -> list[FeatureIdea]:
    raw = _load_existing_ideas(repo, ttl_days=ttl_days)
    ideas = []
    for meta in raw:
        if meta.get("status") != "open":
            continue
        if meta.get("disposition") != "pr":
            continue
        idir = _ideas_dir(repo)
        filepath = idir / meta["filename"]
        content = filepath.read_text()
        parts = content.split("---", 2)
        body = parts[2].strip() if len(parts) >= 3 else ""
        desc_match = re.search(r"## Description\s*\n\n(.*?)(?:\n## |\Z)", body, re.DOTALL)
        description = desc_match.group(1).strip() if desc_match else meta.get("summary", "")
        rationale_match = re.search(r"## Rationale\s*\n\n(.*?)(?:\n## |\Z)", body, re.DOTALL)
        rationale = rationale_match.group(1).strip() if rationale_match else ""
        ideas.append(
            FeatureIdea(
                title=meta.get("title", ""),
                description=description,
                rationale=rationale,
                complexity=meta.get("complexity", "medium"),
                disposition="pr",
                priority=meta.get("priority", 99),
                boldness=meta.get("boldness", "balanced"),
            )
        )
    return ideas


def mark_idea_done(repo: Path, title: str) -> None:
    idir = _ideas_dir(repo)
    if not idir.exists():
        return
    slug = _slug(title)
    for f in idir.glob("*.md"):
        if not f.name.startswith(slug):
            continue
        content = f.read_text()
        if "status: open" in content:
            f.write_text(content.replace("status: open", "status: done", 1))


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


def _save_idea(repo: Path, idea: FeatureIdea) -> Path | None:
    idir = _ideas_dir(repo)
    idir.mkdir(parents=True, exist_ok=True)

    slug = _slug(idea.title)
    if any(f.name.startswith(slug) for f in idir.glob("*.md")):
        return None

    path = idir / f"{slug}.md"

    summary = idea.description[:120].replace("\n", " ").strip()

    meta = {
        "title": idea.title,
        "summary": summary,
        "status": "open",
        "complexity": idea.complexity,
        "disposition": idea.disposition,
        "priority": idea.priority,
        "boldness": idea.boldness,
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
    system_prompt: str,
    context_prompt: str,
    temperature: float,
    max_ideas: int,
    *,
    config: Config | None = None,
    on_status: StatusCallback | None = None,
) -> list[FeatureIdea]:
    ideas: list[FeatureIdea] = []
    next_priority = 1

    async def _report_idea_handler(args: dict) -> ToolResult:
        nonlocal next_priority

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
            description=str(args.get("description", ""))[:2000],
            rationale=str(args.get("rationale", ""))[:500],
            complexity=complexity,
            disposition=disposition,
            priority=int(args.get("priority", next_priority)),
            boldness=config.boldness if config else "balanced",
        )
        ideas.append(idea)
        next_priority = max(next_priority, idea.priority) + 1

        if len(ideas) >= max_ideas:
            return ToolResult(
                content=f"Recorded: [{idea.disposition}] {idea.title} ({idea.complexity}). Limit reached ({max_ideas} ideas).",
                stop=True,
                result=f"Generated {len(ideas)} ideas",
            )

        return ToolResult(
            content=f"Recorded: [{idea.disposition}] {idea.title} ({idea.complexity})"
        )

    report_tool = Tool(
        name="report_idea",
        description=(
            "Propose a single feature idea for the repository. "
            "Call once per idea, in priority order (1 = highest). "
            "Only propose ideas that are specific to THIS repository."
        ),
        parameters=REPORT_IDEA_PARAMS,
        handler=_report_idea_handler,
    )

    agent = Agent(
        label="ideation",
        model=model,
        tools=[report_tool],
        system_prompt=system_prompt,
        max_rounds=config.max_iterations_for("ideator") if config else 15,
        temperature=temperature,
        max_tokens=(config.max_tokens_for("ideator") if config else None) or 32_768,
    )

    await agent.run(
        messages=[{"role": "user", "content": context_prompt}],
        on_status=on_status,
    )

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
    instructions: Instructions | None = None,
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
    memory_files = await select_memory(
        repo, config.model_for("selector"), task_desc, max_tokens=config.max_tokens_for("selector")
    )
    memory_context = ""
    if memory_files:
        parts = []
        for name, content in memory_files.items():
            parts.append(f"### {name}\n{content}")
        memory_context = "\n\n".join(parts)

    repo_conventions = "(none detected)"
    if instructions and instructions.has_instructions:
        repo_conventions = instructions.format_for_prompt()

    max_ideas = config.max_ideas_per_run
    half = math.ceil(max_ideas / 2)

    low_temp, high_temp = TEMP_RANGES.get(config.boldness, TEMP_RANGES["balanced"])

    boldness_text = IDEATOR_BOLDNESS.get(config.boldness) or IDEATOR_BOLDNESS["balanced"]
    system_prompt = IDEATOR_SYSTEM_PROMPT.format(
        repo_conventions=repo_conventions,
        boldness_instructions=boldness_text,
    )
    context_prompt = IDEATION_CONTEXT_PROMPT.format(
        memory_context=memory_context or "(no knowledge files yet)",
        working_memory=working_md or "(no prior runs)",
        existing_ideas=_format_existing_ideas(existing),
        max_ideas=half,
    )

    creative_context = context_prompt.replace(
        f"Report at most {half} ideas.",
        f"Report at most {max_ideas - half} ideas.",
    )
    creative_context += (
        "\n\nThink more creatively and expansively. Go beyond obvious improvements. "
        "Propose ideas that are surprising, novel, or unconventional."
    )

    focused, creative = await asyncio.gather(
        _run_ideation_pass(
            model,
            system_prompt,
            context_prompt,
            low_temp,
            half,
            config=config,
            on_status=on_status,
        ),
        _run_ideation_pass(
            model,
            system_prompt,
            creative_context,
            high_temp,
            max_ideas - half,
            config=config,
            on_status=on_status,
        ),
    )

    combined = focused + creative
    combined.sort(key=lambda i: i.priority)
    return _deduplicate(combined)[:max_ideas]


def save_ideas(repo: Path, ideas: list[FeatureIdea]) -> list[Path]:
    return [p for idea in ideas if (p := _save_idea(repo, idea)) is not None]
