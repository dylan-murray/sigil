import logging
from dataclasses import dataclass
from pathlib import Path

from sigil.agent import Agent, Tool, ToolResult
from sigil.agent_config import AgentConfigResult
from sigil.config import Config
from sigil.knowledge import select_knowledge
from sigil.mcp import MCPManager, prepare_mcp_for_agent
from sigil.memory import load_working
from sigil.utils import StatusCallback, read_file

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


MAX_LLM_ROUNDS = 10
MAX_FILE_READS = 10
MAX_READ_LINES = 2000
MAX_READ_BYTES = 50_000

READ_FILE_TOOL = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": (
            "Read a source file from the repository to verify a potential finding. "
            "Use sparingly — only read files you need to confirm a problem exists. "
            "Large files are truncated — use offset to read further."
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

REPORT_TOOL = {
    "type": "function",
    "function": {
        "name": "report_finding",
        "description": (
            "Report a single maintenance finding with your triage decision. "
            "Call once per issue found, in priority order (1 = highest). "
            "Only report problems you are confident exist."
        ),
        "parameters": {
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
        },
    },
}

BOLDNESS_INSTRUCTIONS = {
    "conservative": "Only report issues you are nearly certain about. Stick to clear-cut problems like unused imports, obvious bugs, and missing tests for critical paths. Do not suggest style changes or speculative improvements.",
    "balanced": "Report issues you are confident about. Include clear problems and well-justified improvements. Avoid speculative or subjective findings.",
    "bold": "Report a wider range of issues including potential improvements, refactoring opportunities, and pattern violations. Include findings you are fairly confident about even if not certain.",
    "experimental": "Report anything that could be improved. Include speculative ideas, architectural suggestions, and aggressive refactoring opportunities. Cast a wide net.",
}

ANALYSIS_PROMPT = """\
You are Sigil, an autonomous repo improvement agent. Analyze this repository
and find concrete, fixable problems.

Focus areas: {focus_areas}
Boldness: {boldness}
{boldness_instructions}

Here is the project knowledge (selected based on relevance to this task):

{knowledge_context}

Here are the repo's coding conventions from its agent config files (respect these):

{repo_conventions}

Here is what Sigil has already done in prior runs (avoid re-surfacing addressed findings):

{working_memory}

You have these built-in tools:
- read_file: Read a source file to verify a potential finding. Use sparingly (max {max_reads} reads).
- report_finding: Report a verified finding with your triage decision.
{mcp_tools_section}

Workflow:
1. Review the knowledge to identify potential issues
2. Use read_file to verify findings against actual source code before reporting
3. Use report_finding for each verified issue, in priority order (1 = most important)

Report at most 50 findings. For each finding, triage it:
- disposition "pr": safe for an AI agent to auto-fix via pull request
- disposition "issue": too risky or complex for auto-fix, open as a GitHub issue
- disposition "skip": not worth acting on

Consider impact, feasibility, and risk when triaging. Be aggressive with "skip" —
only surface findings worth acting on.

Rules:
- Verify findings by reading the actual file before reporting — do not guess
- Do NOT hallucinate file paths or line numbers
- Prefer low-risk findings over speculative ones
- Do not re-report findings already addressed in working memory
- If nothing is clearly wrong, do not call any tools
"""


async def analyze(
    repo: Path,
    config: Config,
    *,
    agent_config: AgentConfigResult | None = None,
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
    model = config.model_for("analyzer")
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

    extra_builtins, initial_mcp_tools, mcp_prompt = prepare_mcp_for_agent(mcp_mgr, model)
    prompt = ANALYSIS_PROMPT.format(
        focus_areas=", ".join(focus),
        boldness=config.boldness,
        boldness_instructions=BOLDNESS_INSTRUCTIONS.get(
            config.boldness, BOLDNESS_INSTRUCTIONS["balanced"]
        ),
        knowledge_context=knowledge_context or "(no knowledge files yet)",
        repo_conventions=repo_conventions,
        working_memory=working_md or "(no prior runs)",
        max_reads=MAX_FILE_READS,
        mcp_tools_section=mcp_prompt,
    )

    findings: list[Finding] = []
    next_priority = 1
    file_reads = 0
    resolved = repo.resolve()

    async def _read_file_handler(args: dict) -> ToolResult:
        nonlocal file_reads
        file_path = str(args.get("file", ""))
        if file_reads >= MAX_FILE_READS:
            return ToolResult(
                content=f"Read limit reached ({MAX_FILE_READS}). Report findings with what you have."
            )

        target = (repo / file_path).resolve()
        if not target.is_relative_to(resolved):
            return ToolResult(content=f"Access denied: {file_path} is outside the repository.")

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
        Tool(
            name=READ_FILE_TOOL["function"]["name"],
            description=READ_FILE_TOOL["function"]["description"],
            parameters=READ_FILE_TOOL["function"]["parameters"],
            handler=_read_file_handler,
        ),
        Tool(
            name=REPORT_TOOL["function"]["name"],
            description=REPORT_TOOL["function"]["description"],
            parameters=REPORT_TOOL["function"]["parameters"],
            handler=_report_finding_handler,
        ),
    ]

    agent = Agent(
        label="analysis",
        model=model,
        tools=tools,
        system_prompt=prompt,
        agent_key="analyzer",
        mcp_mgr=mcp_mgr,
        extra_tool_schemas=extra_builtins + initial_mcp_tools,
    )

    await agent.run(on_status=on_status)

    findings.sort(key=lambda f: f.priority)
    return findings[:50]
