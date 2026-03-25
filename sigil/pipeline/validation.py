import asyncio
import logging
from dataclasses import dataclass, replace
from pathlib import Path

from sigil.core.agent import Agent, Tool, ToolResult
from sigil.core.config import Config
from sigil.core.instructions import Instructions
from sigil.integrations.github import ExistingIssue
from sigil.pipeline.knowledge import select_knowledge
from sigil.pipeline.ideation import FeatureIdea
from sigil.pipeline.maintenance import Finding
from sigil.core.mcp import MCPManager, prepare_mcp_for_agent
from sigil.state.memory import load_working
from sigil.core.utils import StatusCallback, read_file

logger = logging.getLogger(__name__)


MAX_LLM_ROUNDS = 15
MAX_FILE_READS = 10
MAX_READ_LINES = 2000
MAX_READ_BYTES = 50_000

ReviewDecisions = dict[int, tuple[str, str | None, str, str]]

TRIAGER_READ_FILE_TOOL = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": (
            "Read a source file from the repository to verify a candidate item "
            "before writing an implementation spec. Use this to confirm that "
            "referenced files, functions, and patterns actually exist."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    "description": "File path relative to the repo root.",
                },
                "offset": {
                    "type": "integer",
                    "description": "Line number to start reading from (1-based, default 1).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to return (default 2000).",
                },
            },
            "required": ["file"],
        },
    },
}

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
                "spec": {
                    "type": "string",
                    "description": (
                        "Implementation spec for the executor agent. REQUIRED when action "
                        "is 'approve' or 'adjust' with disposition 'pr'. Write a concrete "
                        "spec that a engineer agent can follow:\n"
                        "- Files to modify (exact paths)\n"
                        "- What to change in each file and why\n"
                        "- Acceptance criteria: what 'done' looks like\n"
                        "- Scope boundaries: what NOT to touch\n"
                        "- Edge cases to handle\n"
                        "Example: 'Modify sigil/config.py: add validate() method that "
                        "checks ignore patterns are valid globs. Modify sigil/cli.py: "
                        "call validate() on startup. Do NOT change the Config schema. "
                        "Done when: invalid globs raise ConfigError with a clear message.'"
                    ),
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

VALIDATOR_BOLDNESS_INSTRUCTIONS = {
    "conservative": (
        "Be very strict. Only approve items that are clearly correct, low-risk, "
        "and immediately valuable. Prefer vetoing over approving when uncertain."
    ),
    "balanced": (
        "Apply moderate scrutiny. Approve items that are well-reasoned and specific. "
        "Veto only when you are confident the item is wrong, redundant, or vague."
    ),
    "bold": (
        "Be permissive. Approve items that have a reasonable chance of success, "
        "even if slightly ambitious. Veto only hallucinated, duplicate, or clearly "
        "wrong items. Prefer adjusting disposition over vetoing."
    ),
    "experimental": (
        "Be maximally permissive. The project is configured for experimental boldness, "
        "meaning the team WANTS ambitious changes. Approve anything that is specific, "
        "non-duplicate, and references real code. Only veto items that are hallucinated, "
        "already addressed, or exact duplicates. Prefer PR disposition for small/medium items."
    ),
}

TRIAGER_SYSTEM_PROMPT = """\
You are a staff-level engineering lead. Your job is to review candidates from
the auditor and ideator agents. You catch mistakes and prevent wasted work.

{repo_conventions}

## Strictness

{boldness_instructions}

## Actions

Use the review_item tool for EACH item. You must review every item.

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

IMPORTANT: For every item you approve or adjust to "pr", you MUST write a "spec"
field — a concrete implementation plan for the engineer agent. The spec should name
exact files, describe what to change, set acceptance criteria, and define scope
boundaries. Without a good spec, the engineer agent will take shortcuts or make
wrong assumptions.

You have a read_file tool to verify file contents when writing specs. Use it for
items where you need to confirm the code structure before speccing — but do not
feel obligated to read every file. Prioritize reviewing ALL items over reading files.

IMPORTANT: Check for duplicates across the ENTIRE list. If a finding and an idea
describe the same improvement, veto whichever is lower priority.
"""

VALIDATION_CONTEXT_PROMPT = """\
## Project Context

{knowledge_context}

## Working Memory

{working_memory}

## Candidates to Review

{items_list}
{mcp_tools_section}{existing_issues_section}"""

ARBITER_SYSTEM_PROMPT = """\
You are a senior engineering lead resolving disagreements between two code reviewers.
Each reviewer independently evaluated a set of candidates. They agreed on most items,
but disagreed on the ones listed below.

{repo_conventions}

## Process

For EACH disagreement, use the resolve_item tool to pick the better decision.
Consider the reasoning from both reviewers. Evaluate whether the proposed change
aligns with the repository's conventions and architecture.

## Guardrails

- When in doubt, prefer the more conservative option (veto over approve, issue over pr)
- Veto items that claim to fix code that doesn't exist — but new features proposing
  code that doesn't exist yet are valid
- Do not approve items that duplicate existing GitHub issues or working memory entries
- Prefer "issue" over "pr" when the change touches core architecture or has unclear
  scope — the existing architecture should be respected, not rearchitected by automation
"""

ARBITER_CONTEXT_PROMPT = """\
## Project Context

{knowledge_context}

## Working Memory

{working_memory}

## Disagreements

{disagreements}
"""


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


async def _run_triager(
    model: str,
    system_prompt: str,
    context_prompt: str,
    total: int,
    *,
    repo: Path | None = None,
    config: Config | None = None,
    mcp_mgr: MCPManager | None = None,
    extra_builtins: list[dict] | None = None,
    initial_mcp_tools: list[dict] | None = None,
    on_status: StatusCallback | None = None,
    findings: list[Finding] | None = None,
    ideas: list[FeatureIdea] | None = None,
) -> ReviewDecisions:
    decisions: ReviewDecisions = {}
    file_reads = 0

    async def _review_handler(args: dict) -> ToolResult:
        idx = args.get("index")
        if not isinstance(idx, int) or idx < 0 or idx >= total:
            return ToolResult(content=f"Invalid index: {idx}")

        action = str(args.get("action", ""))
        if action not in VALID_ACTIONS:
            return ToolResult(
                content=f"Invalid action: {action!r}. Must be one of: {', '.join(VALID_ACTIONS)}"
            )

        new_disp = args.get("new_disposition")
        reason = str(args.get("reason", ""))
        spec = str(args.get("spec", ""))

        decisions[idx] = (action, new_disp, reason, spec)

        if on_status:
            n_findings = len(findings) if findings else 0
            label = f"#{idx}"
            if findings and idx < n_findings:
                f = findings[idx]
                label = f"{f.category} in {f.file}"
            elif ideas and idx - n_findings < len(ideas):
                label = ideas[idx - n_findings].title[:50]
            on_status(f"Validating {label}: {action}...")

        return ToolResult(content=f"Reviewed [{idx}]: {action}")

    async def _read_file_handler(args: dict) -> ToolResult:
        nonlocal file_reads
        if repo is None:
            return ToolResult(content="read_file is not available.")
        file_path = str(args.get("file", ""))
        if file_reads >= MAX_FILE_READS:
            return ToolResult(
                content=f"Read limit reached ({MAX_FILE_READS}). Review items with what you have."
            )

        resolved = repo.resolve()
        target = (repo / file_path).resolve()
        if not target.is_relative_to(resolved):
            return ToolResult(content=f"Access denied: {file_path} is outside the repository.")
        ignore = config.ignore if config else None
        if ignore:
            from fnmatch import fnmatch

            if any(fnmatch(file_path, p) for p in ignore):
                return ToolResult(content=f"Access denied: {file_path} is ignored by config.")

        if on_status:
            on_status(f"Reading {file_path}...")
        content = read_file(target)
        if not content:
            return ToolResult(content=f"File not found or empty: {file_path}")

        file_reads += 1
        offset = max(0, int(args.get("offset", 1)) - 1)
        limit = min(int(args.get("limit", MAX_READ_LINES)), MAX_READ_LINES)
        all_lines = content.splitlines(keepends=True)
        total_lines = len(all_lines)
        selected = all_lines[offset : offset + limit]

        output_lines: list[str] = []
        byte_count = 0
        for line in selected:
            byte_count += len(line.encode())
            if byte_count > MAX_READ_BYTES:
                break
            output_lines.append(line)

        content = "".join(output_lines)
        end_line = offset + len(output_lines)

        if end_line < total_lines:
            if not content.endswith("\n"):
                content += "\n"
            content += (
                f"[truncated — {total_lines} lines total. "
                f"Use read_file with offset={end_line + 1} to continue.]"
            )

        return ToolResult(content=content)

    review_tool = Tool(
        name=REVIEW_TOOL["function"]["name"],
        description=REVIEW_TOOL["function"]["description"],
        parameters=REVIEW_TOOL["function"]["parameters"],
        handler=_review_handler,
    )

    tools = [review_tool]
    if repo is not None:
        read_tool = Tool(
            name=TRIAGER_READ_FILE_TOOL["function"]["name"],
            description=TRIAGER_READ_FILE_TOOL["function"]["description"],
            parameters=TRIAGER_READ_FILE_TOOL["function"]["parameters"],
            handler=_read_file_handler,
        )
        tools.append(read_tool)

    agent = Agent(
        label="validation:triager",
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        max_tokens=16_384,
        mcp_mgr=mcp_mgr,
        extra_tool_schemas=(extra_builtins or []) + (initial_mcp_tools or []),
    )

    await agent.run(
        messages=[{"role": "user", "content": context_prompt}],
        on_status=on_status,
    )

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

        action_a, disp_a, _, spec_a = a
        action_b, disp_b, _, spec_b = b

        if action_a == action_b and (action_a != "adjust" or disp_a == disp_b):
            if spec_b and not spec_a:
                agreed[idx] = (a[0], a[1], a[2], spec_b)
            else:
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
            action_a, disp_a, reason_a, _ = a
            disp_str = f" → {disp_a}" if disp_a else ""
            lines.append(f"  Reviewer A: {action_a}{disp_str} — {reason_a}")

        if b:
            action_b, disp_b, reason_b, _ = b
            disp_str = f" → {disp_b}" if disp_b else ""
            lines.append(f"  Reviewer B: {action_b}{disp_str} — {reason_b}")

        lines.append("")

    return "\n".join(lines)


async def _run_arbiter(
    model: str,
    system_prompt: str,
    context_prompt: str,
    disagreed_indices: set[int],
) -> ReviewDecisions:
    decisions: ReviewDecisions = {}

    async def _resolve_handler(args: dict) -> ToolResult:
        idx = args.get("index")
        if not isinstance(idx, int) or idx not in disagreed_indices:
            return ToolResult(content=f"Invalid index: {idx}")

        action = str(args.get("action", ""))
        if action not in VALID_ACTIONS:
            return ToolResult(
                content=f"Invalid action: {action!r}. Must be one of: {', '.join(VALID_ACTIONS)}"
            )

        new_disp = args.get("new_disposition")
        reason = str(args.get("reason", ""))
        decisions[idx] = (action, new_disp, reason, "")

        return ToolResult(content=f"Resolved [{idx}]: {action}")

    resolve_tool = Tool(
        name=RESOLVE_TOOL["function"]["name"],
        description=RESOLVE_TOOL["function"]["description"],
        parameters=RESOLVE_TOOL["function"]["parameters"],
        handler=_resolve_handler,
    )

    agent = Agent(
        label="validation:arbiter",
        model=model,
        tools=[resolve_tool],
        system_prompt=system_prompt,
        max_tokens=16_384,
    )

    await agent.run(
        messages=[{"role": "user", "content": context_prompt}],
    )

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

        action, new_disp, reason, spec = decisions[i]
        if action == "veto":
            logger.info(f"Vetoed finding [{i}] {finding.category} | {finding.file}: {reason}")
            continue
        updated = finding
        if spec:
            updated = replace(updated, implementation_spec=spec)
        if action == "adjust" and new_disp in ("pr", "issue", "skip"):
            validated_findings.append(replace(updated, disposition=new_disp))
        else:
            validated_findings.append(updated)

    offset = len(findings)
    validated_ideas: list[FeatureIdea] = []
    for j, idea in enumerate(ideas):
        idx = offset + j
        if idx not in decisions:
            validated_ideas.append(idea)
            continue

        action, new_disp, reason, spec = decisions[idx]
        if action == "veto":
            logger.info(f"Vetoed idea [{idx}] {idea.title}: {reason}")
            continue
        updated_idea = idea
        if spec:
            updated_idea = replace(updated_idea, implementation_spec=spec)
        if action == "adjust" and new_disp in ("pr", "issue"):
            validated_ideas.append(replace(updated_idea, disposition=new_disp))
        else:
            validated_ideas.append(updated_idea)

    return ValidationResult(findings=validated_findings, ideas=validated_ideas)


async def validate_all(
    repo: Path,
    config: Config,
    findings: list[Finding],
    ideas: list[FeatureIdea],
    *,
    existing_issues: list[ExistingIssue] | None = None,
    instructions: Instructions | None = None,
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
    model = config.model_for("challenger") if is_parallel else config.model_for("triager")
    knowledge_files = await select_knowledge(repo, config.model_for("selector"), task_desc)
    knowledge_context = ""
    if knowledge_files:
        parts = []
        for name, content in knowledge_files.items():
            parts.append(f"### {name}\n{content}")
        knowledge_context = "\n\n".join(parts)

    repo_conventions = "(none detected)"
    if instructions and instructions.has_instructions:
        repo_conventions = instructions.format_for_prompt()

    total = len(findings) + len(ideas)

    existing_section = _format_existing_issues(existing_issues or [])

    boldness_instructions = VALIDATOR_BOLDNESS_INSTRUCTIONS.get(
        config.boldness, VALIDATOR_BOLDNESS_INSTRUCTIONS["balanced"]
    )

    extra_builtins, initial_mcp_tools, mcp_prompt = prepare_mcp_for_agent(mcp_mgr, model)
    items_text = _format_items(repo, findings, ideas)
    system_prompt = TRIAGER_SYSTEM_PROMPT.format(
        repo_conventions=repo_conventions,
        boldness_instructions=boldness_instructions,
    )
    context_prompt = VALIDATION_CONTEXT_PROMPT.format(
        knowledge_context=knowledge_context or "(no knowledge files yet)",
        working_memory=working_md or "(no prior runs)",
        items_list=items_text,
        mcp_tools_section=mcp_prompt,
        existing_issues_section=existing_section,
    )

    if config.validation_mode == "single":
        decisions = await _run_triager(
            model,
            system_prompt,
            context_prompt,
            total,
            repo=repo,
            config=config,
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

    challenger_model = config.model_for("challenger")
    r_extra, r_mcp_tools, r_mcp_prompt = prepare_mcp_for_agent(mcp_mgr, challenger_model)
    challenger_system = TRIAGER_SYSTEM_PROMPT.format(
        repo_conventions=repo_conventions,
        boldness_instructions=boldness_instructions,
    )
    challenger_context = VALIDATION_CONTEXT_PROMPT.format(
        knowledge_context=knowledge_context or "(no knowledge files yet)",
        working_memory=working_md or "(no prior runs)",
        items_list=items_text,
        mcp_tools_section=r_mcp_prompt,
        existing_issues_section=existing_section,
    )

    decisions_a, decisions_b = await asyncio.gather(
        _run_triager(
            challenger_model,
            challenger_system,
            challenger_context,
            total,
            repo=repo,
            config=config,
            mcp_mgr=mcp_mgr,
            extra_builtins=r_extra,
            initial_mcp_tools=r_mcp_tools,
            findings=findings,
            ideas=ideas,
        ),
        _run_triager(
            challenger_model,
            challenger_system,
            challenger_context,
            total,
            repo=repo,
            config=config,
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
    disagreement_text = _format_disagreements(
        disagreed_indices, decisions_a, decisions_b, findings, ideas
    )
    arbiter_context = ARBITER_CONTEXT_PROMPT.format(
        knowledge_context=knowledge_context or "(no knowledge files yet)",
        working_memory=working_md or "(no prior runs)",
        disagreements=disagreement_text,
    )

    arbiter_system = ARBITER_SYSTEM_PROMPT.format(repo_conventions=repo_conventions)
    arbiter_decisions = await _run_arbiter(
        arbiter_model,
        arbiter_system,
        arbiter_context,
        disagreed_indices,
    )

    final_decisions = dict(agreed)
    for idx in disagreed_indices:
        a = decisions_a.get(idx)
        b = decisions_b.get(idx)
        if idx in arbiter_decisions:
            arb = arbiter_decisions[idx]
            arb_action = arb[0]
            donor_spec = ""
            if a and a[0] == arb_action:
                donor_spec = a[3]
            elif b and b[0] == arb_action:
                donor_spec = b[3]
            if not donor_spec:
                donor_spec = (a[3] if a and a[3] else "") or (b[3] if b and b[3] else "")
            final_decisions[idx] = (arb[0], arb[1], arb[2], donor_spec)
        else:
            conservative = a if a and a[0] == "veto" else b if b and b[0] == "veto" else a or b
            if conservative:
                final_decisions[idx] = conservative

    return _apply_decisions(final_decisions, findings, ideas)
