import json
from dataclasses import dataclass
from pathlib import Path

import litellm

from sigil.config import Config
from sigil.llm import get_max_output_tokens
from sigil.knowledge import select_knowledge
from sigil.memory import load_working
from sigil.utils import read_file


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


MAX_LLM_ROUNDS = 10
MAX_FILE_READS = 10
MAX_FILE_CHARS = 8000

READ_FILE_TOOL = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": (
            "Read a source file from the repository to verify a potential finding. "
            "Use sparingly — only read files you need to confirm a problem exists."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    "description": "File path relative to the repo root.",
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

Here is what Sigil has already done in prior runs (avoid re-surfacing addressed findings):

{working_memory}

You have two tools:
- read_file: Read a source file to verify a potential finding. Use sparingly (max {max_reads} reads).
- report_finding: Report a verified finding with your triage decision.

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


async def analyze(repo: Path, config: Config) -> list[Finding]:
    focus = config.focus
    working_md = load_working(repo)

    task_desc = (
        f"Analyze repository for maintenance issues. "
        f"Focus areas: {', '.join(focus)}. Boldness: {config.boldness}."
    )
    knowledge_files = await select_knowledge(repo, config.model, task_desc)
    knowledge_context = ""
    if knowledge_files:
        parts = []
        for name, content in knowledge_files.items():
            parts.append(f"### {name}\n{content}")
        knowledge_context = "\n\n".join(parts)

    prompt = ANALYSIS_PROMPT.format(
        focus_areas=", ".join(focus),
        boldness=config.boldness,
        boldness_instructions=BOLDNESS_INSTRUCTIONS.get(
            config.boldness, BOLDNESS_INSTRUCTIONS["balanced"]
        ),
        knowledge_context=knowledge_context or "(no knowledge files yet)",
        working_memory=working_md or "(no prior runs)",
        max_reads=MAX_FILE_READS,
    )

    messages: list[dict] = [{"role": "user", "content": prompt}]
    findings: list[Finding] = []
    next_priority = 1
    file_reads = 0
    resolved = repo.resolve()

    for _ in range(MAX_LLM_ROUNDS):
        response = await litellm.acompletion(
            model=config.model,
            messages=messages,
            tools=[READ_FILE_TOOL, REPORT_TOOL],
            temperature=0.0,
            max_tokens=get_max_output_tokens(config.model),
        )

        choice = response.choices[0]

        if not choice.message.tool_calls:
            break

        messages.append(choice.message)

        for tool_call in choice.message.tool_calls:
            name = tool_call.function.name

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

            if name == "read_file":
                if file_reads >= MAX_FILE_READS:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": f"Read limit reached ({MAX_FILE_READS}). Report findings with what you have.",
                        }
                    )
                    continue

                file_path = str(args.get("file", ""))
                target = (repo / file_path).resolve()
                if not target.is_relative_to(resolved):
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": f"Access denied: {file_path} is outside the repository.",
                        }
                    )
                    continue

                content = read_file(target)
                if not content:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": f"File not found or empty: {file_path}",
                        }
                    )
                    continue

                file_reads += 1
                if len(content) > MAX_FILE_CHARS:
                    content = (
                        content[:MAX_FILE_CHARS] + f"\n\n... truncated ({len(content)} chars total)"
                    )

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": content,
                    }
                )
                continue

            if name != "report_finding":
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": "Unknown tool.",
                    }
                )
                continue

            disposition = str(args.get("disposition", "issue"))
            if disposition not in ("pr", "issue", "skip"):
                disposition = "issue"

            risk = str(args.get("risk", "medium"))
            if risk not in ("low", "medium", "high"):
                risk = "medium"

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

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": f"Recorded: [{finding.disposition}] {finding.category} in {finding.file}",
                }
            )

        if choice.finish_reason == "stop":
            break

    findings.sort(key=lambda f: f.priority)
    return findings[:50]
