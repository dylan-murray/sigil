import logging
from dataclasses import replace
from pathlib import Path

from sigil.core.agent import Agent, Tool, ToolResult
from sigil.core.config import Config
from sigil.core.instructions import Instructions
from sigil.core.mcp import MCPManager, prepare_mcp_for_agent
from sigil.core.tools import (
    make_grep_tool,
    make_list_dir_tool,
    make_read_file_tool,
)
from sigil.core.utils import StatusCallback, arun
from sigil.pipeline.knowledge import get_last_head, select_memory
from sigil.pipeline.models import Finding as Finding
from sigil.pipeline.prompts import (
    ANALYSIS_CONTEXT_PROMPT,
    AUDITOR_BOLDNESS,
    AUDITOR_SYSTEM_PROMPT,
)
from sigil.state.memory import load_working

logger = logging.getLogger(__name__)

MAX_LLM_ROUNDS = 10

REPORT_FINDING_PARAMS = {
    "type": "object",
    "properties": {
        "category": {
            "type": "string",
            "enum": ["dead_code", "tests", "security", "docs", "types", "todo", "style"],
            "description": "Category of the finding.",
        },
        "file": {
            "type": "string",
            "description": "Exact file path from the project knowledge.",
        },
        "line": {
            "type": ["integer", "null"],
            "description": "Line number if known, null otherwise.",
        },
        "description": {
            "type": "string",
            "description": "Clear, specific description of the problem.",
        },
        "risk": {
            "type": "string",
            "enum": ["low", "medium", "high"],
            "description": "Risk of the fix breaking something.",
        },
        "suggested_fix": {
            "type": "string",
            "description": "Concrete description of how to fix it.",
        },
        "disposition": {
            "type": "string",
            "enum": ["pr", "issue", "skip"],
            "description": (
                "pr = safe to auto-fix via PR (DEFAULT for low-risk findings: "
                "typos, dead code, missing tests, doc rot, type hints, lint, "
                "small refactors). "
                "issue = carries real risk (data loss, security, public API break, "
                "or cross-cutting refactor) and needs human review before code. "
                "skip = not worth acting on."
            ),
        },
        "priority": {
            "type": "integer",
            "description": "Priority rank, 1 = highest. No duplicates.",
        },
        "rationale": {
            "type": "string",
            "description": "One sentence explaining the disposition and priority.",
        },
    },
    "required": [
        "category",
        "file",
        "description",
        "risk",
        "suggested_fix",
        "disposition",
        "priority",
        "rationale",
    ],
}


async def analyze(
    repo: Path,
    config: Config,
    *,
    instructions: Instructions | None = None,
    mcp_mgr: MCPManager | None = None,
    on_status: StatusCallback | None = None,
) -> list[Finding]:
    focus = config.focus
    working_md = load_working(repo)

    task_desc = (
        f"Analyze repository for maintenance issues. "
        f"Focus areas: {', '.join(focus)}. Boldness: {config.boldness}."
    )
    if on_status:
        on_status("Selecting relevant knowledge...")
    model = config.model_for("auditor")
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

    extra_builtins, initial_mcp_tools, mcp_prompt = prepare_mcp_for_agent(mcp_mgr, model)
    system_prompt = AUDITOR_SYSTEM_PROMPT.format(
        repo_conventions=repo_conventions,
        boldness_instructions=AUDITOR_BOLDNESS.get(config.boldness, AUDITOR_BOLDNESS["balanced"]),
    )
    context_prompt = ANALYSIS_CONTEXT_PROMPT.format(
        focus_areas=", ".join(focus),
        memory_context=memory_context or "(no knowledge files yet)",
        working_memory=working_md or "(no prior runs)",
        mcp_tools_section=mcp_prompt,
    )

    findings: list[Finding] = []
    next_priority = 1

    async def _report_finding_handler(args: dict) -> ToolResult:
        nonlocal next_priority
        disposition = str(args.get("disposition", "issue"))
        if disposition not in ("pr", "issue", "skip"):
            disposition = "issue"

        risk = str(args.get("risk", "medium"))
        if risk not in ("low", "medium", "high"):
            risk = "medium"

        if on_status:
            on_status(f"Analyzing {args.get('category', '')} in {args.get('file', '')}...")

        finding = Finding(
            category=str(args.get("category", "")),
            file=str(args.get("file", "")),
            line=args.get("line"),
            description=str(args.get("description", "")),
            risk=risk,
            suggested_fix=str(args.get("suggested_fix", "")),
            disposition=disposition,
            priority=int(args.get("priority", next_priority)),
            rationale=str(args.get("rationale", "")),
            boldness=config.boldness,
        )
        findings.append(finding)
        next_priority = max(next_priority, finding.priority) + 1

        return ToolResult(
            content=f"Recorded: [{finding.disposition}] {finding.category} in {finding.file}"
        )

    tools = [
        make_read_file_tool(
            repo,
            on_status,
            config.effective_ignore,
            description=(
                "Read a source file from the repository to verify a potential finding. "
                "Use sparingly — only read files you need to confirm a problem exists. "
                "Large files are truncated — use offset to read further."
            ),
        ),
        make_list_dir_tool(repo, config.effective_ignore),
        make_grep_tool(repo, on_status, config.effective_ignore),
        Tool(
            name="report_finding",
            description=(
                "Report a single maintenance finding with your triage decision. "
                "Call once per issue found, in priority order (1 = highest). "
                "Only report problems you are confident exist."
            ),
            parameters=REPORT_FINDING_PARAMS,
            handler=_report_finding_handler,
        ),
    ]

    agent = Agent(
        label="audit",
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        max_rounds=config.max_iterations_for("auditor"),
        max_tokens=config.max_tokens_for("auditor") or 65_536,
        mcp_mgr=mcp_mgr,
        extra_tool_schemas=extra_builtins + initial_mcp_tools,
        reasoning_effort=config.reasoning_effort_for("auditor"),
    )

    await agent.run(
        messages=[{"role": "user", "content": context_prompt}],
        on_status=on_status,
    )

    findings.sort(key=lambda f: f.priority)
    return findings[:50]


async def is_finding_stale(
    finding: Finding,
    repo: Path,
    last_head: str | None = None,
    context_range: int = 5,
) -> tuple[bool, str]:
    file_path = repo / finding.file
    if not file_path.exists():
        return True, "file_deleted"
    if finding.line is not None:
        try:
            line_count = len(file_path.read_text().splitlines())
        except OSError:
            line_count = 0
        if finding.line > line_count:
            return True, "line_out_of_range"
    if last_head and finding.line is not None:
        rc, diff_output, _ = await arun(
            ["git", "diff", last_head, "HEAD", "--", finding.file],
            cwd=repo,
            timeout=10,
        )
        if rc == 0 and diff_output.strip():
            for hunk_line in _parse_diff_lines(diff_output):
                if finding.line <= hunk_line <= finding.line + context_range:
                    return True, "lines_changed"
    return False, ""


def _parse_diff_lines(diff_output: str) -> list[int]:
    lines: list[int] = []
    for line in diff_output.splitlines():
        if line.startswith("@@"):
            parts = line.split(" ")
            new_range = None
            for part in parts:
                if part.startswith("+"):
                    new_range = part[1:]
                    break
            if not new_range:
                continue
            if "," in new_range:
                start_str, count_str = new_range.split(",", 1)
            else:
                start_str = new_range
                count_str = "1"
            try:
                start = int(start_str)
                count = int(count_str)
                lines.extend(range(start, start + count))
            except ValueError:
                continue
    return lines


async def filter_stale_findings(
    findings: list[Finding],
    repo: Path,
    context_range: int = 5,
) -> tuple[list[Finding], list[Finding]]:
    last_head = get_last_head(repo)
    fresh: list[Finding] = []
    stale: list[Finding] = []
    for finding in findings:
        is_stale, reason = await is_finding_stale(
            finding, repo, last_head=last_head, context_range=context_range
        )
        if is_stale:
            stale.append(replace(finding, staleness_reason=reason))
            logger.info(
                "Stale finding filtered: %s in %s (reason: %s)",
                finding.category,
                finding.file,
                reason,
            )
        else:
            fresh.append(finding)
    return fresh, stale
