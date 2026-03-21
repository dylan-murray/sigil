import json
from dataclasses import replace
from pathlib import Path

import litellm

from sigil.config import Config
from sigil.knowledge import select_knowledge
from sigil.maintenance import Finding
from sigil.memory import load_working


MAX_LLM_ROUNDS = 10

VALIDATE_TOOL = {
    "type": "function",
    "function": {
        "name": "validate_finding",
        "description": (
            "Review a finding and either approve it as-is, adjust its disposition, "
            "or veto it entirely. Call once per finding."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "finding_index": {
                    "type": "integer",
                    "description": "Zero-based index of the finding in the list.",
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
            "required": ["finding_index", "action", "reason"],
        },
    },
}

VALIDATION_PROMPT = """\
You are a senior reviewer validating findings from Sigil's analysis agent.
Your job is to catch mistakes: hallucinated file paths, bad triage decisions,
findings that aren't worth acting on, or PRs that should be issues.

Here is the project knowledge:

{knowledge_context}

Here is Sigil's working memory:

{working_memory}

Here are the findings to validate:

{findings_list}

Use the validate_finding tool for each finding. You must review every finding.
- "approve" if the finding and its disposition are correct
- "adjust" if the finding is valid but the disposition is wrong (e.g. a risky fix marked as "pr" should be "issue")
- "veto" if the finding is hallucinated, already addressed, or not worth acting on

Be skeptical but fair. Only veto findings you are confident are wrong.
"""


def _format_findings(findings: list[Finding]) -> str:
    lines = []
    for i, f in enumerate(findings):
        loc = f.file
        if f.line:
            loc = f"{f.file}:{f.line}"
        lines.append(
            f"[{i}] #{f.priority} [{f.disposition}] {f.category} | {loc} | risk: {f.risk}\n"
            f"    {f.description}\n"
            f"    Fix: {f.suggested_fix}\n"
            f"    Rationale: {f.rationale}"
        )
    return "\n\n".join(lines)


def validate(repo: Path, config: Config, findings: list[Finding]) -> list[Finding]:
    if not findings:
        return []

    working_md = load_working(repo)

    task_desc = "Validate and review maintenance findings before execution."
    knowledge_files = select_knowledge(repo, config.model, task_desc)
    knowledge_context = ""
    if knowledge_files:
        parts = []
        for name, content in knowledge_files.items():
            parts.append(f"### {name}\n{content}")
        knowledge_context = "\n\n".join(parts)

    prompt = VALIDATION_PROMPT.format(
        knowledge_context=knowledge_context or "(no knowledge files yet)",
        working_memory=working_md or "(no prior runs)",
        findings_list=_format_findings(findings),
    )

    messages: list[dict] = [{"role": "user", "content": prompt}]
    decisions: dict[int, tuple[str, str | None, str]] = {}

    for _ in range(MAX_LLM_ROUNDS):
        response = litellm.completion(
            model=config.model,
            messages=messages,
            tools=[VALIDATE_TOOL],
            temperature=0.0,
            max_tokens=4096,
        )

        choice = response.choices[0]

        if not choice.message.tool_calls:
            break

        messages.append(choice.message)

        for tool_call in choice.message.tool_calls:
            if tool_call.function.name != "validate_finding":
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

            idx = args.get("finding_index")
            if not isinstance(idx, int) or idx < 0 or idx >= len(findings):
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": f"Invalid finding_index: {idx}",
                    }
                )
                continue

            action = str(args.get("action", "approve"))
            new_disp = args.get("new_disposition")
            reason = str(args.get("reason", ""))

            decisions[idx] = (action, new_disp, reason)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": f"Validated [{idx}]: {action}",
                }
            )

        if choice.finish_reason == "stop":
            break

    validated: list[Finding] = []
    for i, finding in enumerate(findings):
        if i not in decisions:
            validated.append(replace(finding, disposition="issue"))
            continue

        action, new_disp, reason = decisions[i]

        if action == "veto":
            continue

        if action == "adjust" and new_disp in ("pr", "issue", "skip"):
            validated.append(replace(finding, disposition=new_disp))
        else:
            validated.append(finding)

    return validated
