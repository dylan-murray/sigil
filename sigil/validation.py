import json
import logging
from dataclasses import dataclass, replace
from pathlib import Path

from sigil.config import Config
from sigil.knowledge import select_knowledge
from sigil.llm import acompletion, get_max_output_tokens
from sigil.ideation import FeatureIdea
from sigil.maintenance import Finding
from sigil.memory import load_working

logger = logging.getLogger(__name__)


MAX_LLM_ROUNDS = 10

REVIEW_TOOL = {
    "type": "function",
    "function": {
        "name": "review_item",
        "description": (
            "Review a candidate item (finding or idea) and either approve it, "
            "adjust its disposition, or veto it. Call once per item."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "index": {
                    "type": "integer",
                    "description": "Zero-based index of the item in the list.",
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
                    "enum": ["pr", "issue", "skip"],
                    "description": "New disposition (only required when action is 'adjust').",
                },
                "reason": {
                    "type": "string",
                    "description": "Brief reason for the decision.",
                },
            },
            "required": ["index", "action", "reason"],
        },
    },
}

VALIDATION_PROMPT = """\
You are a senior engineer reviewing candidates from Sigil's analysis and ideation
agents. Your job is to catch mistakes and prevent wasted work.

Here is the project knowledge:

{knowledge_context}

Here is Sigil's working memory (what it has done in prior runs):

{working_memory}

Here are ALL candidates to review:

{items_list}

Use the review_item tool for EACH item. You must review every item.

Actions:
- "approve" if the item is valid and its disposition is correct
- "adjust" if the item is valid but the disposition is wrong (e.g. a risky fix
  marked as "pr" should be "issue", or a complex idea marked as "pr" should be "issue")
- "veto" if the item is:
  - Hallucinated (references files/code that doesn't exist)
  - Already addressed in working memory
  - Not valuable enough to pursue
  - A duplicate of another item in this list (veto the lower-priority one)
  - Generic advice that applies to any project (for ideas)
  - Too vague to act on

IMPORTANT: Check for duplicates across the ENTIRE list. If a finding and an idea
describe the same improvement, veto whichever is lower priority. If two findings
or two ideas overlap, veto the duplicate.

Be skeptical but fair. Only veto items you are confident are wrong or redundant.
"""


@dataclass(frozen=True)
class ValidationResult:
    findings: list[Finding]
    ideas: list[FeatureIdea]


VALID_ACTIONS = {"approve", "adjust", "veto"}


def _format_items(repo: Path, findings: list[Finding], ideas: list[FeatureIdea]) -> str:
    lines = []
    offset = 0

    if findings:
        lines.append("FINDINGS:")
        for i, f in enumerate(findings):
            loc = f.file
            if f.line:
                loc = f"{f.file}:{f.line}"
            exists = (repo / f.file).exists()
            tag = "[FILE EXISTS]" if exists else "[FILE MISSING]"
            lines.append(
                f"[{i}] #{f.priority} [{f.disposition}] {f.category} | {loc} | risk: {f.risk} {tag}\n"
                f"    {f.description}\n"
                f"    Fix: {f.suggested_fix}\n"
                f"    Rationale: {f.rationale}"
            )
        offset = len(findings)

    if ideas:
        if findings:
            lines.append("")
        lines.append("IDEAS:")
        for j, idea in enumerate(ideas):
            idx = offset + j
            lines.append(
                f"[{idx}] #{idea.priority} [{idea.disposition}] {idea.title} ({idea.complexity})\n"
                f"    {idea.description[:300]}\n"
                f"    Rationale: {idea.rationale[:200]}"
            )

    return "\n\n".join(lines)


async def validate_all(
    repo: Path,
    config: Config,
    findings: list[Finding],
    ideas: list[FeatureIdea],
) -> ValidationResult:
    if not findings and not ideas:
        return ValidationResult(findings=[], ideas=[])

    working_md = load_working(repo)

    task_desc = "Validate and review all candidates (findings + ideas) before execution."
    knowledge_files = await select_knowledge(repo, config.model, task_desc)
    knowledge_context = ""
    if knowledge_files:
        parts = []
        for name, content in knowledge_files.items():
            parts.append(f"### {name}\n{content}")
        knowledge_context = "\n\n".join(parts)

    total = len(findings) + len(ideas)

    prompt = VALIDATION_PROMPT.format(
        knowledge_context=knowledge_context or "(no knowledge files yet)",
        working_memory=working_md or "(no prior runs)",
        items_list=_format_items(repo, findings, ideas),
    )

    messages: list[dict] = [{"role": "user", "content": prompt}]
    decisions: dict[int, tuple[str, str | None, str]] = {}

    for _ in range(MAX_LLM_ROUNDS):
        response = await acompletion(
            model=config.model,
            messages=messages,
            tools=[REVIEW_TOOL],
            temperature=0.0,
            max_tokens=get_max_output_tokens(config.model),
        )

        choice = response.choices[0]

        if not choice.message.tool_calls:
            break

        messages.append(choice.message)

        for tool_call in choice.message.tool_calls:
            if tool_call.function.name != "review_item":
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

            idx = args.get("index")
            if not isinstance(idx, int) or idx < 0 or idx >= total:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": f"Invalid index: {idx}",
                    }
                )
                continue

            action = str(args.get("action", ""))
            if action not in VALID_ACTIONS:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": f"Invalid action: {action!r}. Must be one of: {', '.join(VALID_ACTIONS)}",
                    }
                )
                continue

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

    validated_findings: list[Finding] = []
    for i, finding in enumerate(findings):
        if i not in decisions:
            validated_findings.append(replace(finding, disposition="issue"))
            continue

        action, new_disp, reason = decisions[i]
        if action == "veto":
            logger.info(f"Vetoed finding [{i}] {finding.category} | {finding.file}: {reason}")
            continue
        if action == "adjust" and new_disp in ("pr", "issue", "skip"):
            validated_findings.append(replace(finding, disposition=new_disp))
        else:
            validated_findings.append(finding)

    offset = len(findings)
    validated_ideas: list[FeatureIdea] = []
    for j, idea in enumerate(ideas):
        idx = offset + j
        if idx not in decisions:
            validated_ideas.append(idea)
            continue

        action, new_disp, reason = decisions[idx]
        if action == "veto":
            logger.info(f"Vetoed idea [{idx}] {idea.title}: {reason}")
            continue
        if action == "adjust" and new_disp in ("pr", "issue"):
            validated_ideas.append(replace(idea, disposition=new_disp))
        else:
            validated_ideas.append(idea)

    return ValidationResult(findings=validated_findings, ideas=validated_ideas)
