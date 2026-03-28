import logging
from dataclasses import dataclass
from pathlib import Path

from sigil.core.agent import Agent, Tool, ToolResult
from sigil.core.instructions import Instructions
from sigil.core.config import Config
from sigil.core.tools import MAX_FILE_READS, make_grep_tool, make_read_file_tool
from sigil.pipeline.knowledge import select_memory
from sigil.core.mcp import MCPManager, prepare_mcp_for_agent
from sigil.state.memory import load_working
from sigil.core.utils import StatusCallback

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Finding:
    category: str
    file: str
    line: int | None
    description: str
    risk: str
    suggested_fix: str
    disposition: str
    priority: int
    rationale: str
    implementation_spec: str = ""
    relevant_files: tuple[str, ...] = ()


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
                "pr = safe to auto-fix via PR. "
                "issue = too risky for auto-fix, open as issue for human review. "
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

BOLDNESS_INSTRUCTIONS = {
    "conservative": "Only report issues you are nearly certain about. Stick to clear-cut problems like unused imports, obvious bugs, and missing tests for critical paths. Do not suggest style changes or speculative improvements.",
    "balanced": "Report issues you are confident about. Include clear problems and well-justified improvements. Avoid speculative or subjective findings.",
    "bold": "Report a wider range of issues including potential improvements, refactoring opportunities, and pattern violations. Include findings you are fairly confident about even if not certain.",
    "experimental": "Report anything that could be improved. Include speculative ideas, architectural suggestions, and aggressive refactoring opportunities. Cast a wide net.",
}

AUDITOR_SYSTEM_PROMPT = """\
You are a staff-level code auditor. Your job is to analyze a repository and
find concrete, fixable problems.

{repo_conventions}

## Strictness

{boldness_instructions}

## Workflow

1. Review the project knowledge to identify potential issues.
2. Use read_file to verify findings against actual source code before reporting.
3. Use report_finding for each verified issue, in priority order (1 = most important).

## Triage

Report at most 50 findings. For each finding, triage it:
- disposition "pr": safe for an AI agent to auto-fix via pull request
- disposition "issue": too risky or complex for auto-fix, open as a GitHub issue
- disposition "skip": not worth acting on

Consider impact, feasibility, and risk when triaging. Be aggressive with "skip" —
only surface findings worth acting on.

## Rules

- Verify findings by reading the actual file before reporting — do not guess
- Do NOT hallucinate file paths or line numbers
- Prefer low-risk findings over speculative ones
- Do not re-report findings already addressed in working memory
- If nothing is clearly wrong, do not call any tools
- Report findings via report_finding tool calls — do not write a prose summary of your findings
"""

ANALYSIS_CONTEXT_PROMPT = """\
Focus areas: {focus_areas}

## Project Context

{memory_context}

## Working Memory

{working_memory}

## Tools

- read_file: Read a source file to verify a potential finding. Use sparingly (max {max_reads} reads).
- report_finding: Report a verified finding with your triage decision.
{mcp_tools_section}
"""


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
        boldness_instructions=BOLDNESS_INSTRUCTIONS.get(
            config.boldness, BOLDNESS_INSTRUCTIONS["balanced"]
        ),
    )
    context_prompt = ANALYSIS_CONTEXT_PROMPT.format(
        focus_areas=", ".join(focus),
        memory_context=memory_context or "(no knowledge files yet)",
        working_memory=working_md or "(no prior runs)",
        max_reads=MAX_FILE_READS,
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
            config.ignore,
            description=(
                "Read a source file from the repository to verify a potential finding. "
                "Use sparingly — only read files you need to confirm a problem exists. "
                "Large files are truncated — use offset to read further."
            ),
        ),
        make_grep_tool(repo, on_status),
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
        max_tokens=config.max_tokens_for("auditor") or 65_536,
        mcp_mgr=mcp_mgr,
        extra_tool_schemas=extra_builtins + initial_mcp_tools,
    )

    await agent.run(
        messages=[{"role": "user", "content": context_prompt}],
        on_status=on_status,
    )

    findings.sort(key=lambda f: f.priority)
    return findings[:50]
