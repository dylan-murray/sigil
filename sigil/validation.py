import asyncio
import json
import logging
from dataclasses import dataclass, replace
from pathlib import Path

from sigil.config import Config
from sigil.github import ExistingIssue
from sigil.knowledge import select_knowledge
from sigil.llm import acompletion, get_max_output_tokens
from sigil.ideation import FeatureIdea
from sigil.maintenance import Finding
from sigil.mcp import MCPManager, handle_search_tools_call, prepare_mcp_for_agent
from sigil.memory import load_working
from sigil.utils import StatusCallback

logger = logging.getLogger(__name__)


MAX_LLM_ROUNDS = 10

ReviewDecisions = dict[int, tuple[str, str | None, str]]

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

RESOLVE_TOOL = {
    "type": "function",
    "function": {
        "name": "resolve_item",
        "description": (
            "Resolve a disagreement between two reviewers on a candidate item. "
            "Pick the better decision. Call once per disagreement."
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
                    "description": "The final action for this item.",
                },
                "new_disposition": {
                    "type": "string",
                    "enum": ["pr", "issue", "skip"],
                    "description": "New disposition (only required when action is 'adjust').",
                },
                "reason": {
                    "type": "string",
                    "description": "Brief reason for choosing this resolution.",
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
{mcp_tools_section}{existing_issues_section}"""

ARBITER_PROMPT = """\
You are a senior engineering lead resolving disagreements between two code reviewers.
Each reviewer independently evaluated a set of candidates. They agreed on most items,
but disagreed on the ones listed below.

Here is the project knowledge:

{knowledge_context}

Here is Sigil's working memory (what it has done in prior runs):

{working_memory}

Here are the candidates where reviewers disagreed:

{disagreements}

For EACH disagreement, use the resolve_item tool to pick the better decision.
Consider the reasoning from both reviewers. When in doubt, prefer the more
conservative option (veto over approve, issue over pr).
{mcp_tools_section}"""


@dataclass(frozen=True)
class ValidationResult:
    findings: list[Finding]
    ideas: list[FeatureIdea]


VALID_ACTIONS = {"approve", "adjust", "veto"}


def _format_existing_issues(issues: list[ExistingIssue]) -> str:
    if not issues:
        return ""
    lines = [
        "\n## Existing GitHub Issues (already tracked)\n"
        "These issues already exist on the repo with the `sigil` label. "
        "Do NOT approve new items that duplicate any of these. "
        "Items tagged [DIRECTIVE] have been explicitly requested by a maintainer — "
        "boost their priority and prefer PR disposition.\n"
    ]
    for issue in issues:
        tag = "[DIRECTIVE] " if issue.has_directive else ""
        lines.append(f"- {tag}#{issue.number}: {issue.title}")
        if issue.body:
            lines.append(f"  {issue.body}")
    return "\n".join(lines)


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


async def _run_reviewer(
    model: str,
    prompt: str,
    total: int,
    *,
    mcp_mgr: MCPManager | None = None,
    extra_builtins: list[dict] | None = None,
    initial_mcp_tools: list[dict] | None = None,
    on_status: StatusCallback | None = None,
    findings: list[Finding] | None = None,
    ideas: list[FeatureIdea] | None = None,
) -> ReviewDecisions:
    messages: list[dict] = [{"role": "user", "content": prompt}]
    decisions: ReviewDecisions = {}

    builtin_tools = [REVIEW_TOOL] + (extra_builtins or [])
    all_tools = builtin_tools + (initial_mcp_tools or [])

    for _ in range(MAX_LLM_ROUNDS):
        response = await acompletion(
            model=model,
            messages=messages,
            tools=all_tools,
            temperature=0.0,
            max_tokens=get_max_output_tokens(model),
        )

        choice = response.choices[0]

        if not choice.message.tool_calls:
            break

        messages.append(choice.message)

        for tool_call in choice.message.tool_calls:
            if tool_call.function.name != "review_item":
                if tool_call.function.name == "search_tools":
                    try:
                        st_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        st_args = {}
                    if mcp_mgr:
                        st_result = handle_search_tools_call(mcp_mgr, st_args, all_tools)
                    else:
                        st_result = "search_tools is not available without MCP servers."
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": st_result,
                        }
                    )
                elif mcp_mgr and mcp_mgr.has_tool(tool_call.function.name):
                    try:
                        mcp_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        mcp_args = {}
                    mcp_result = await mcp_mgr.call_tool(tool_call.function.name, mcp_args)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": mcp_result,
                        }
                    )
                else:
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

            if on_status:
                n_findings = len(findings) if findings else 0
                label = f"#{idx}"
                if findings and idx < n_findings:
                    f = findings[idx]
                    label = f"{f.category} in {f.file}"
                elif ideas and idx - n_findings < len(ideas):
                    label = ideas[idx - n_findings].title[:50]
                on_status(f"Validating {label}: {action}...")

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": f"Reviewed [{idx}]: {action}",
                }
            )

        if choice.finish_reason == "stop":
            break

    return decisions


def _find_disagreements(
    decisions_a: ReviewDecisions,
    decisions_b: ReviewDecisions,
    total: int,
) -> tuple[ReviewDecisions, set[int]]:
    agreed: ReviewDecisions = {}
    disagreed_indices: set[int] = set()

    for idx in range(total):
        a = decisions_a.get(idx)
        b = decisions_b.get(idx)

        if a is None and b is None:
            continue

        if a is None or b is None:
            agreed[idx] = a if a is not None else b  # type: ignore[assignment]
            continue

        action_a, disp_a, _ = a
        action_b, disp_b, _ = b

        if action_a == action_b and (action_a != "adjust" or disp_a == disp_b):
            agreed[idx] = a
        else:
            disagreed_indices.add(idx)

    return agreed, disagreed_indices


def _format_disagreements(
    disagreed_indices: set[int],
    decisions_a: ReviewDecisions,
    decisions_b: ReviewDecisions,
    findings: list[Finding],
    ideas: list[FeatureIdea],
) -> str:
    lines = []
    offset = len(findings)

    for idx in sorted(disagreed_indices):
        if idx < offset:
            f = findings[idx]
            lines.append(f"[{idx}] {f.category} | {f.file}: {f.description[:200]}")
        else:
            idea = ideas[idx - offset]
            lines.append(f"[{idx}] {idea.title}: {idea.description[:200]}")

        a = decisions_a.get(idx)
        b = decisions_b.get(idx)

        if a:
            action_a, disp_a, reason_a = a
            disp_str = f" → {disp_a}" if disp_a else ""
            lines.append(f"  Reviewer A: {action_a}{disp_str} — {reason_a}")

        if b:
            action_b, disp_b, reason_b = b
            disp_str = f" → {disp_b}" if disp_b else ""
            lines.append(f"  Reviewer B: {action_b}{disp_str} — {reason_b}")

        lines.append("")

    return "\n".join(lines)


async def _run_arbiter(
    model: str,
    prompt: str,
    disagreed_indices: set[int],
    *,
    mcp_mgr: MCPManager | None = None,
    extra_builtins: list[dict] | None = None,
    initial_mcp_tools: list[dict] | None = None,
) -> ReviewDecisions:
    messages: list[dict] = [{"role": "user", "content": prompt}]
    decisions: ReviewDecisions = {}

    builtin_tools = [RESOLVE_TOOL] + (extra_builtins or [])
    all_tools = builtin_tools + (initial_mcp_tools or [])

    for _ in range(MAX_LLM_ROUNDS):
        response = await acompletion(
            model=model,
            messages=messages,
            tools=all_tools,
            temperature=0.0,
            max_tokens=get_max_output_tokens(model),
        )

        choice = response.choices[0]

        if not choice.message.tool_calls:
            break

        messages.append(choice.message)

        for tool_call in choice.message.tool_calls:
            if tool_call.function.name != "resolve_item":
                if tool_call.function.name == "search_tools":
                    try:
                        st_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        st_args = {}
                    if mcp_mgr:
                        st_result = handle_search_tools_call(mcp_mgr, st_args, all_tools)
                    else:
                        st_result = "search_tools is not available without MCP servers."
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": st_result,
                        }
                    )
                elif mcp_mgr and mcp_mgr.has_tool(tool_call.function.name):
                    try:
                        mcp_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        mcp_args = {}
                    mcp_result = await mcp_mgr.call_tool(tool_call.function.name, mcp_args)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": mcp_result,
                        }
                    )
                else:
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
            if not isinstance(idx, int) or idx not in disagreed_indices:
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
                    "content": f"Resolved [{idx}]: {action}",
                }
            )

        if choice.finish_reason == "stop":
            break

    return decisions


def _apply_decisions(
    decisions: ReviewDecisions,
    findings: list[Finding],
    ideas: list[FeatureIdea],
) -> ValidationResult:
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


async def validate_all(
    repo: Path,
    config: Config,
    findings: list[Finding],
    ideas: list[FeatureIdea],
    *,
    existing_issues: list[ExistingIssue] | None = None,
    mcp_mgr: MCPManager | None = None,
    on_status: StatusCallback | None = None,
) -> ValidationResult:
    if not findings and not ideas:
        return ValidationResult(findings=[], ideas=[])

    working_md = load_working(repo)

    task_desc = "Validate and review all candidates (findings + ideas) before execution."
    if on_status:
        on_status("Selecting relevant knowledge...")
    is_parallel = config.validation_mode == "parallel"
    model = config.model_for("reviewer") if is_parallel else config.model_for("validator")
    knowledge_files = await select_knowledge(repo, model, task_desc)
    knowledge_context = ""
    if knowledge_files:
        parts = []
        for name, content in knowledge_files.items():
            parts.append(f"### {name}\n{content}")
        knowledge_context = "\n\n".join(parts)

    total = len(findings) + len(ideas)

    existing_section = _format_existing_issues(existing_issues or [])

    extra_builtins, initial_mcp_tools, mcp_prompt = prepare_mcp_for_agent(mcp_mgr, model)
    items_text = _format_items(repo, findings, ideas)
    prompt = VALIDATION_PROMPT.format(
        knowledge_context=knowledge_context or "(no knowledge files yet)",
        working_memory=working_md or "(no prior runs)",
        items_list=items_text,
        mcp_tools_section=mcp_prompt,
        existing_issues_section=existing_section,
    )

    if config.validation_mode == "single":
        decisions = await _run_reviewer(
            model,
            prompt,
            total,
            mcp_mgr=mcp_mgr,
            extra_builtins=extra_builtins,
            initial_mcp_tools=initial_mcp_tools,
            on_status=on_status,
            findings=findings,
            ideas=ideas,
        )
        return _apply_decisions(decisions, findings, ideas)

    if on_status:
        on_status("Running parallel reviewers...")

    reviewer_model = config.model_for("reviewer")
    r_extra, r_mcp_tools, r_mcp_prompt = prepare_mcp_for_agent(mcp_mgr, reviewer_model)
    reviewer_prompt = VALIDATION_PROMPT.format(
        knowledge_context=knowledge_context or "(no knowledge files yet)",
        working_memory=working_md or "(no prior runs)",
        items_list=items_text,
        mcp_tools_section=r_mcp_prompt,
        existing_issues_section=existing_section,
    )

    decisions_a, decisions_b = await asyncio.gather(
        _run_reviewer(
            reviewer_model,
            reviewer_prompt,
            total,
            mcp_mgr=mcp_mgr,
            extra_builtins=r_extra,
            initial_mcp_tools=r_mcp_tools,
            findings=findings,
            ideas=ideas,
        ),
        _run_reviewer(
            reviewer_model,
            reviewer_prompt,
            total,
            mcp_mgr=mcp_mgr,
            extra_builtins=r_extra,
            initial_mcp_tools=r_mcp_tools,
            findings=findings,
            ideas=ideas,
        ),
    )

    agreed, disagreed_indices = _find_disagreements(decisions_a, decisions_b, total)

    if not disagreed_indices:
        logger.info("Parallel reviewers fully agreed — no arbiter needed")
        if on_status:
            on_status("Reviewers agreed on all items")
        return _apply_decisions(agreed, findings, ideas)

    logger.info(f"Reviewers disagreed on {len(disagreed_indices)} item(s) — running arbiter")
    if on_status:
        on_status(f"Resolving {len(disagreed_indices)} disagreement(s)...")

    arbiter_model = config.model_for("arbiter")
    a_extra, a_mcp_tools, a_mcp_prompt = prepare_mcp_for_agent(mcp_mgr, arbiter_model)
    disagreement_text = _format_disagreements(
        disagreed_indices, decisions_a, decisions_b, findings, ideas
    )
    arbiter_prompt = ARBITER_PROMPT.format(
        knowledge_context=knowledge_context or "(no knowledge files yet)",
        working_memory=working_md or "(no prior runs)",
        disagreements=disagreement_text,
        mcp_tools_section=a_mcp_prompt,
    )

    arbiter_decisions = await _run_arbiter(
        arbiter_model,
        arbiter_prompt,
        disagreed_indices,
        mcp_mgr=mcp_mgr,
        extra_builtins=a_extra,
        initial_mcp_tools=a_mcp_tools,
    )

    final_decisions = dict(agreed)
    for idx in disagreed_indices:
        if idx in arbiter_decisions:
            final_decisions[idx] = arbiter_decisions[idx]
        else:
            a = decisions_a.get(idx)
            b = decisions_b.get(idx)
            conservative = a if a and a[0] == "veto" else b if b and b[0] == "veto" else a or b
            if conservative:
                final_decisions[idx] = conservative

    return _apply_decisions(final_decisions, findings, ideas)
