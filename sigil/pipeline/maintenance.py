import logging
from pathlib import Path

from sigil.core.agent import Agent, Tool, ToolResult
from sigil.core.config import Config
from sigil.core.instructions import Instructions
from sigil.core.mcp import MCPManager, prepare_mcp_for_agent
from sigil.core.tools import MAX_READS_HARD_STOP, make_grep_tool, make_read_file_tool
from sigil.core.utils import StatusCallback
from sigil.pipeline.knowledge import select_memory
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
        max_reads=MAX_READS_HARD_STOP,
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

    agent = Agent[None](
        label="audit",
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        max_rounds=config.max_iterations_for("auditor"),
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
