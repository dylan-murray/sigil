import asyncio
import json
import logging
from dataclasses import replace
from pathlib import Path

from pydantic import BaseModel, Field

from sigil.core.agent import Agent, Tool, ToolResult
from sigil.core.config import SIGIL_DIR, Config
from sigil.core.instructions import Instructions
from sigil.core.llm import StructuredOutputError, structured_completion
from sigil.core.mcp import MCPManager, prepare_mcp_for_agent
from sigil.core.tools import make_grep_tool, make_read_file_tool, make_veto_duplicates_tool
from sigil.core.utils import StatusCallback, now_utc
from sigil.integrations.github import ExistingIssue
from sigil.pipeline.knowledge import select_memory
from sigil.pipeline.models import (
    FeatureIdea,
    Finding,
    ReviewDecision,
    ReviewDecisions,
    ValidationResult,
)
from sigil.pipeline.prompts import (
    ARBITER_CONTEXT_PROMPT,
    ARBITER_SYSTEM_PROMPT,
    REBALANCE_PROMPT,
    TRIAGER_SYSTEM_PROMPT,
    VALIDATION_CONTEXT_PROMPT,
    VALIDATOR_BOLDNESS,
)
from sigil.state.chronic import fingerprint
from sigil.state.memory import load_working
from sigil.state.similarity import top_k_similar

logger = logging.getLogger(__name__)


MAX_LLM_ROUNDS = 15

SIMILARITY_TRACE_FILE = "similarity.jsonl"


REVIEW_ITEM_PARAMS = {
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
                "Concrete implementation spec. REQUIRED for approved PR items. "
                "Include: files to modify, what to change, acceptance criteria, "
                "scope boundaries, edge cases."
            ),
        },
        "relevant_files": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "File paths the engineer needs to read. REQUIRED for approved PR items. "
                "Include files to modify, context files (imports, callers), and existing tests."
            ),
        },
        "priority": {
            "type": "integer",
            "description": (
                "Execution priority. 1 = highest. REQUIRED for approve/adjust. "
                "Rank all approved items relative to each other."
            ),
        },
    },
    "required": ["index", "action", "reason"],
}

RESOLVE_ITEM_PARAMS = {
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
}

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


def _log_similarity_trace(
    repo: Path,
    findings: list[Finding],
    ideas: list[FeatureIdea],
    similarity_map: dict[int, list[tuple[ExistingIssue, float]]],
    decisions: ReviewDecisions,
) -> None:
    if not similarity_map:
        return
    path = repo / SIGIL_DIR / "traces" / SIMILARITY_TRACE_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        ts = now_utc()
        candidates = list(findings) + list(ideas)
        with path.open("a") as f:
            for idx, item in enumerate(candidates):
                top = similarity_map.get(idx, [])
                decision = decisions.get(idx)
                record = {
                    "ts": ts,
                    "candidate_id": fingerprint(item),
                    "top_k": [
                        {
                            "issue_number": iss.number,
                            "title": iss.title,
                            "score": round(score, 4),
                        }
                        for iss, score in top
                    ],
                    "triager_decision": decision.action if decision else None,
                }
                f.write(json.dumps(record) + "\n")
    except OSError as exc:
        logger.warning("Failed to write similarity trace: %s", exc)


def _finalize(
    decisions: ReviewDecisions,
    findings: list[Finding],
    ideas: list[FeatureIdea],
    *,
    repo: Path,
    similarity_map: dict[int, list[tuple[ExistingIssue, float]]],
) -> ValidationResult:
    _log_similarity_trace(repo, findings, ideas, similarity_map, decisions)
    return _apply_decisions(decisions, findings, ideas)


def _finding_as_pair(f: Finding) -> tuple[str, str]:
    title = f"{f.category}: {f.description[:80]}"
    body = " ".join([f.description, f.rationale, f.suggested_fix])
    return title, body


def _idea_as_pair(idea: FeatureIdea) -> tuple[str, str]:
    return idea.title, " ".join([idea.description, idea.rationale])


def _issue_as_pair(issue: ExistingIssue) -> tuple[str, str]:
    return issue.title, issue.body


def _build_similarity_map(
    findings: list[Finding],
    ideas: list[FeatureIdea],
    existing: list[ExistingIssue],
    *,
    k: int = 3,
) -> dict[int, list[tuple[ExistingIssue, float]]]:
    if not existing or (not findings and not ideas):
        return {}
    issue_pairs = [_issue_as_pair(i) for i in existing]
    result: dict[int, list[tuple[ExistingIssue, float]]] = {}
    candidates: list[tuple[str, str]] = [_finding_as_pair(f) for f in findings]
    candidates.extend(_idea_as_pair(i) for i in ideas)
    for idx, pair in enumerate(candidates):
        top = top_k_similar(pair, issue_pairs, k=k)
        result[idx] = [(existing[j], score) for j, score in top if score > 0.0]
    return result


def _format_similar(
    similar: list[tuple[ExistingIssue, float]] | None,
) -> str:
    if not similar:
        return ""
    rows = [f"    - #{iss.number} ({score:.2f}): {iss.title}" for iss, score in similar]
    return "\n    Closest existing issues:\n" + "\n".join(rows)


def _format_items(
    repo: Path,
    findings: list[Finding],
    ideas: list[FeatureIdea],
    similarity_map: dict[int, list[tuple[ExistingIssue, float]]] | None = None,
) -> str:
    sim = similarity_map or {}
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
                f"{_format_similar(sim.get(i))}"
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
                f"{_format_similar(sim.get(idx))}"
            )

    return "\n\n".join(lines)


class RebalanceOrder(BaseModel):
    order: list[int] = Field(
        description="Item indices in order from highest priority (first) to lowest (last)."
    )


async def _rebalance_priorities(
    approved: ReviewDecisions,
    model: str,
    on_status: StatusCallback | None = None,
) -> ReviewDecisions:
    lines = []
    for idx, d in sorted(approved.items()):
        lines.append(f"[{idx}] priority={d.priority} | {d.action} | {d.reason[:80]}")
    items_summary = "\n".join(lines)

    if on_status:
        on_status("Rebalancing priorities...")

    try:
        result_obj = await structured_completion(
            label="triager:rebalance",
            model=model,
            messages=[
                {"role": "user", "content": REBALANCE_PROMPT.format(items_summary=items_summary)}
            ],
            schema=RebalanceOrder,
            temperature=0.0,
            max_tokens=4096,
        )
    except StructuredOutputError as exc:
        logger.warning("Priority rebalance failed: %s", exc)
        return {}

    valid = set(approved.keys())
    seen: set[int] = set()
    order: list[int] = []
    for idx in result_obj.order:
        if idx in valid and idx not in seen:
            order.append(idx)
            seen.add(idx)

    result: ReviewDecisions = {}
    for priority, idx in enumerate(order, start=1):
        result[idx] = replace(approved[idx], priority=priority)
    return result


async def _run_triager(
    model: str,
    system_prompt: str,
    context_prompt: str,
    total: int,
    *,
    label: str = "validation:triager",
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
        raw_files = args.get("relevant_files", [])
        files = [str(f) for f in raw_files] if isinstance(raw_files, list) else []
        priority = int(args.get("priority", 99))

        decisions[idx] = ReviewDecision(
            action=action,
            new_disposition=new_disp,
            reason=reason,
            spec=spec,
            relevant_files=files or None,
            priority=priority,
        )

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

    review_tool = Tool(
        name="review_item",
        description=(
            "Review a candidate item (finding or idea) and either approve it, "
            "adjust its disposition, or veto it. Call once per item."
        ),
        parameters=REVIEW_ITEM_PARAMS,
        handler=_review_handler,
    )

    veto_dup_tool = make_veto_duplicates_tool(decisions, total, on_status)
    tools = [veto_dup_tool, review_tool]
    if repo is not None:
        ignore = config.effective_ignore if config else None
        tools.append(
            make_read_file_tool(
                repo,
                on_status,
                ignore,
                description=(
                    "Read a source file from the repository to verify a candidate item "
                    "before writing an implementation spec. Use this to confirm that "
                    "referenced files, functions, and patterns actually exist."
                ),
            )
        )
        tools.append(make_grep_tool(repo, on_status, ignore))

    agent_name = label.split(":")[-1] if ":" in label else "triager"
    agent = Agent(
        label=label,
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        max_rounds=config.max_iterations_for("triager") if config else 15,
        max_tokens=(config.max_tokens_for("triager") if config else None) or 16_384,
        mcp_mgr=mcp_mgr,
        extra_tool_schemas=(extra_builtins or []) + (initial_mcp_tools or []),
        reasoning_effort=config.reasoning_effort_for(agent_name) if config else None,
    )

    await agent.run(
        messages=[{"role": "user", "content": context_prompt}],
        on_status=on_status,
    )

    approved = {idx: d for idx, d in decisions.items() if d.action != "veto"}
    if len(approved) > 1:
        rebalanced = await _rebalance_priorities(approved, model, on_status)
        decisions.update(rebalanced)

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

        if a.action == b.action and (
            a.action != "adjust" or a.new_disposition == b.new_disposition
        ):
            spec = b.spec if b.spec and not a.spec else a.spec
            files = a.relevant_files or b.relevant_files
            priority = min(a.priority, b.priority)
            agreed[idx] = ReviewDecision(
                action=a.action,
                new_disposition=a.new_disposition,
                reason=a.reason,
                spec=spec,
                relevant_files=files,
                priority=priority,
            )
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
            disp_str = f" → {a.new_disposition}" if a.new_disposition else ""
            lines.append(f"  Reviewer A: {a.action}{disp_str} — {a.reason}")

        if b:
            disp_str = f" → {b.new_disposition}" if b.new_disposition else ""
            lines.append(f"  Reviewer B: {b.action}{disp_str} — {b.reason}")

        lines.append("")

    return "\n".join(lines)


async def _run_arbiter(
    model: str,
    system_prompt: str,
    context_prompt: str,
    disagreed_indices: set[int],
    *,
    config: Config | None = None,
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
        decisions[idx] = ReviewDecision(
            action=action,
            new_disposition=new_disp,
            reason=reason,
        )

        return ToolResult(content=f"Resolved [{idx}]: {action}")

    resolve_tool = Tool(
        name="resolve_item",
        description=(
            "Resolve a disagreement between two reviewers on a candidate item. "
            "Pick the better decision. Call once per disagreement."
        ),
        parameters=RESOLVE_ITEM_PARAMS,
        handler=_resolve_handler,
    )

    agent = Agent(
        label="validation:arbiter",
        model=model,
        tools=[resolve_tool],
        system_prompt=system_prompt,
        max_rounds=config.max_iterations_for("arbiter") if config else 10,
        max_tokens=(config.max_tokens_for("arbiter") if config else None) or 16_384,
        reasoning_effort=config.reasoning_effort_for("arbiter") if config else None,
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

        d = decisions[i]
        if d.action == "veto":
            logger.info(f"Vetoed finding [{i}] {finding.category} | {finding.file}: {d.reason}")
            continue
        updated = finding
        if d.priority != 99:
            updated = replace(updated, priority=d.priority)
        if d.spec:
            updated = replace(updated, implementation_spec=d.spec)
        if d.relevant_files:
            updated = replace(updated, relevant_files=tuple(d.relevant_files))
        if d.action == "adjust" and d.new_disposition in ("pr", "issue", "skip"):
            validated_findings.append(replace(updated, disposition=d.new_disposition))
        else:
            validated_findings.append(updated)

    offset = len(findings)
    validated_ideas: list[FeatureIdea] = []
    for j, idea in enumerate(ideas):
        idx = offset + j
        if idx not in decisions:
            validated_ideas.append(idea)
            continue

        d = decisions[idx]
        if d.action == "veto":
            logger.info(f"Vetoed idea [{idx}] {idea.title}: {d.reason}")
            continue
        updated_idea = idea
        if d.priority != 99:
            updated_idea = replace(updated_idea, priority=d.priority)
        if d.spec:
            updated_idea = replace(updated_idea, implementation_spec=d.spec)
        if d.relevant_files:
            updated_idea = replace(updated_idea, relevant_files=tuple(d.relevant_files))
        if d.action == "adjust" and d.new_disposition in ("pr", "issue"):
            validated_ideas.append(replace(updated_idea, disposition=d.new_disposition))
        else:
            validated_ideas.append(updated_idea)

    validated_findings.sort(key=lambda f: f.priority)
    validated_ideas.sort(key=lambda i: i.priority)

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
    is_parallel = config.arbiter
    model = config.model_for("challenger") if is_parallel else config.model_for("triager")
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

    total = len(findings) + len(ideas)

    existing_section = _format_existing_issues(existing_issues or [])
    similarity_map = _build_similarity_map(findings, ideas, existing_issues or [])

    boldness_instructions = VALIDATOR_BOLDNESS.get(config.boldness, VALIDATOR_BOLDNESS["balanced"])

    extra_builtins, initial_mcp_tools, mcp_prompt = prepare_mcp_for_agent(mcp_mgr, model)
    items_text = _format_items(repo, findings, ideas, similarity_map)
    system_prompt = TRIAGER_SYSTEM_PROMPT.format(
        repo_conventions=repo_conventions,
        boldness_instructions=boldness_instructions,
    )
    context_prompt = VALIDATION_CONTEXT_PROMPT.format(
        memory_context=memory_context or "(no knowledge files yet)",
        working_memory=working_md or "(no prior runs)",
        items_list=items_text,
        mcp_tools_section=mcp_prompt,
        existing_issues_section=existing_section,
    )

    if not config.arbiter:
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
        return _finalize(decisions, findings, ideas, repo=repo, similarity_map=similarity_map)

    if on_status:
        on_status("Running parallel reviewers...")

    challenger_model = config.model_for("challenger")
    r_extra, r_mcp_tools, r_mcp_prompt = prepare_mcp_for_agent(mcp_mgr, challenger_model)
    challenger_system = TRIAGER_SYSTEM_PROMPT.format(
        repo_conventions=repo_conventions,
        boldness_instructions=boldness_instructions,
    )
    challenger_context = VALIDATION_CONTEXT_PROMPT.format(
        memory_context=memory_context or "(no knowledge files yet)",
        working_memory=working_md or "(no prior runs)",
        items_list=items_text,
        mcp_tools_section=r_mcp_prompt,
        existing_issues_section=existing_section,
    )

    decisions_a, decisions_b = await asyncio.gather(
        _run_triager(
            model,
            system_prompt,
            context_prompt,
            total,
            label="validation:triager",
            repo=repo,
            config=config,
            mcp_mgr=mcp_mgr,
            extra_builtins=extra_builtins,
            initial_mcp_tools=initial_mcp_tools,
            findings=findings,
            ideas=ideas,
        ),
        _run_triager(
            challenger_model,
            challenger_system,
            challenger_context,
            total,
            label="validation:challenger",
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
        approved = {idx: d for idx, d in agreed.items() if d.action != "veto"}
        if len(approved) > 1:
            rebalanced = await _rebalance_priorities(
                approved, config.model_for("arbiter"), on_status
            )
            agreed.update(rebalanced)
        return _finalize(agreed, findings, ideas, repo=repo, similarity_map=similarity_map)

    logger.info(f"Reviewers disagreed on {len(disagreed_indices)} item(s) — running arbiter")
    if on_status:
        on_status(f"Resolving {len(disagreed_indices)} disagreement(s)...")

    arbiter_model = config.model_for("arbiter")
    disagreement_text = _format_disagreements(
        disagreed_indices, decisions_a, decisions_b, findings, ideas
    )
    arbiter_context = ARBITER_CONTEXT_PROMPT.format(
        memory_context=memory_context or "(no knowledge files yet)",
        working_memory=working_md or "(no prior runs)",
        disagreements=disagreement_text,
    )

    arbiter_system = ARBITER_SYSTEM_PROMPT.format(repo_conventions=repo_conventions)
    arbiter_decisions = await _run_arbiter(
        arbiter_model,
        arbiter_system,
        arbiter_context,
        disagreed_indices,
        config=config,
    )

    final_decisions = dict(agreed)
    for idx in disagreed_indices:
        a = decisions_a.get(idx)
        b = decisions_b.get(idx)
        if idx in arbiter_decisions:
            arb = arbiter_decisions[idx]
            donor_spec = ""
            donor_files: list[str] | None = None
            if a and a.action == arb.action:
                donor_spec = a.spec
                donor_files = a.relevant_files
            elif b and b.action == arb.action:
                donor_spec = b.spec
                donor_files = b.relevant_files
            if not donor_spec:
                donor_spec = (a.spec if a and a.spec else "") or (b.spec if b and b.spec else "")
            if not donor_files:
                donor_files = (a.relevant_files if a and a.relevant_files else None) or (
                    b.relevant_files if b and b.relevant_files else None
                )
            donor_priority = 99
            if a and a.action == arb.action:
                donor_priority = a.priority
            elif b and b.action == arb.action:
                donor_priority = b.priority
            final_decisions[idx] = ReviewDecision(
                action=arb.action,
                new_disposition=arb.new_disposition,
                reason=arb.reason,
                spec=donor_spec,
                relevant_files=donor_files,
                priority=donor_priority,
            )
        else:
            conservative = (
                a if a and a.action == "veto" else b if b and b.action == "veto" else a or b
            )
            if conservative:
                final_decisions[idx] = conservative

    approved_final = {idx: d for idx, d in final_decisions.items() if d.action != "veto"}
    if len(approved_final) > 1:
        rebalanced = await _rebalance_priorities(approved_final, arbiter_model, on_status)
        final_decisions.update(rebalanced)

    return _finalize(final_decisions, findings, ideas, repo=repo, similarity_map=similarity_map)
