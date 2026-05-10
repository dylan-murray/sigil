import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from sigil.core.agent import Agent, Tool, ToolResult
from sigil.core.config import Config
from sigil.core.instructions import Instructions
from sigil.core.llm import acompletion
from sigil.core.mcp import MCPManager, prepare_mcp_for_agent
from sigil.core.tools import make_grep_tool, make_list_dir_tool, make_read_file_tool
from sigil.core.utils import StatusCallback
from sigil.integrations.github import (
    GitHubClient,
    fetch_pr_diff,
    fetch_pr_info,
    post_inline_comments,
    post_review_comment,
)
from sigil.pipeline.knowledge import select_memory
from sigil.pipeline.prompts import REVIEW_CONTEXT_PROMPT, REVIEW_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PRReviewFinding:
    category: str
    file: str
    line: int | None
    description: str
    severity: str
    suggested_fix: str
    disposition: str

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "file": self.file,
            "line": self.line,
            "description": self.description,
            "severity": self.severity,
            "suggested_fix": self.suggested_fix,
            "disposition": self.disposition,
        }


@dataclass
class ReviewResult:
    findings: list[PRReviewFinding] = field(default_factory=list)
    summary_comment_url: str | None = None
    inline_comment_count: int = 0
    fix_pr_url: str | None = None


REPORT_FINDING_PARAMS = {
    "type": "object",
    "properties": {
        "category": {
            "type": "string",
            "enum": [
                "bug",
                "security",
                "style",
                "performance",
                "readability",
                "type_safety",
                "error_handling",
                "documentation",
                "testing",
                "other",
            ],
            "description": "Category of the finding.",
        },
        "file": {
            "type": "string",
            "description": "File path relative to repo root.",
        },
        "line": {
            "type": "integer",
            "description": "Line number in the file where the issue is found, or null if not line-specific.",
        },
        "description": {
            "type": "string",
            "description": "Clear description of the issue found.",
        },
        "severity": {
            "type": "string",
            "enum": ["critical", "high", "medium", "low", "info"],
            "description": "Severity of the finding.",
        },
        "suggested_fix": {
            "type": "string",
            "description": "Suggested fix or improvement.",
        },
        "disposition": {
            "type": "string",
            "enum": ["comment", "fix", "skip"],
            "description": (
                "comment = post a review comment (default). "
                "fix = this is safe to auto-fix in a follow-up PR. "
                "skip = not worth acting on."
            ),
        },
    },
    "required": ["category", "file", "description", "severity", "suggested_fix", "disposition"],
}


async def review_pr(
    repo: Path,
    config: Config,
    pr_number: int,
    *,
    client: GitHubClient | None = None,
    dry_run: bool = False,
    instructions: Instructions | None = None,
    mcp_mgr: MCPManager | None = None,
    on_status: StatusCallback | None = None,
) -> ReviewResult:
    if on_status:
        on_status("Fetching PR data...")

    diff = await fetch_pr_diff(client, pr_number)
    pr_info = await fetch_pr_info(client, pr_number)

    if not diff:
        if on_status:
            on_status("No diff found for PR — nothing to review.")
        return ReviewResult()

    if on_status:
        on_status(f"Reviewing PR #{pr_number}: {pr_info.title[:60]}...")

    working_md = ""
    try:
        from sigil.state.memory import load_working

        working_md = load_working(repo) or ""
    except Exception:
        pass

    repo_conventions = "(none detected)"
    if instructions and instructions.has_instructions:
        repo_conventions = instructions.format_for_prompt()

    memory_context = ""
    try:
        memory_files = await select_memory(
            repo,
            config.model_for("selector"),
            f"Review PR #{pr_number}",
            max_tokens=config.max_tokens_for("selector"),
        )
        if memory_files:
            parts = [f"### {name}\n{content}" for name, content in memory_files.items()]
            memory_context = "\n\n".join(parts)
    except Exception:
        pass

    findings: list[PRReviewFinding] = []

    async def _report_handler(args: dict) -> ToolResult:
        category = str(args.get("category", "other"))
        file_path = str(args.get("file", ""))
        line_raw = args.get("line")
        line = (
            int(line_raw) if isinstance(line_raw, (int, float)) and line_raw is not None else None
        )
        description = str(args.get("description", ""))
        severity = str(args.get("severity", "info"))
        suggested_fix = str(args.get("suggested_fix", ""))
        disposition = str(args.get("disposition", "comment"))

        finding = PRReviewFinding(
            category=category,
            file=file_path,
            line=line,
            description=description,
            severity=severity,
            suggested_fix=suggested_fix,
            disposition=disposition,
        )
        findings.append(finding)

        if on_status:
            on_status(f"Found: {category} in {file_path} ({severity})")

        return ToolResult(content=f"Recorded finding: {category} in {file_path}")

    report_tool = Tool(
        name="report_review_finding",
        description=(
            "Report a finding from the PR review. Call once per finding, "
            "in order of severity (most critical first)."
        ),
        parameters=REPORT_FINDING_PARAMS,
        handler=_report_handler,
    )

    ignore = config.effective_ignore or None
    tools = [
        report_tool,
        make_read_file_tool(repo, on_status, ignore),
        make_grep_tool(repo, on_status, ignore),
        make_list_dir_tool(repo, ignore),
    ]

    extra_builtins, initial_mcp_tools, mcp_prompt = prepare_mcp_for_agent(
        mcp_mgr, config.model_for("triager")
    )

    changed_files_list = (
        "\n".join(f"- {f}" for f in pr_info.changed_files) if pr_info.changed_files else "(unknown)"
    )

    context_prompt = REVIEW_CONTEXT_PROMPT.format(
        pr_title=pr_info.title,
        pr_author=pr_info.author,
        pr_body=pr_info.body or "(no description)",
        base_ref=pr_info.base_ref,
        head_ref=pr_info.head_ref,
        changed_files=changed_files_list,
        diff=diff,
        memory_context=memory_context or "(no knowledge files)",
        working_memory=working_md or "(no prior runs)",
        mcp_tools_section=mcp_prompt,
    )

    agent = Agent(
        label="review",
        model=config.model_for("triager"),
        tools=tools,
        system_prompt=REVIEW_SYSTEM_PROMPT.format(repo_conventions=repo_conventions),
        max_rounds=config.max_iterations_for("triager"),
        max_tokens=config.max_tokens_for("triager") or 16_384,
        mcp_mgr=mcp_mgr,
        extra_tool_schemas=extra_builtins + initial_mcp_tools,
        reasoning_effort=config.reasoning_effort_for("triager"),
    )

    await agent.run(
        messages=[{"role": "user", "content": context_prompt}],
        on_status=on_status,
    )

    result = ReviewResult(findings=findings)

    if dry_run:
        if on_status:
            on_status(f"Dry run: {len(findings)} finding(s) found, no comments posted.")
        return result

    if not client:
        if on_status:
            on_status("No GitHub client — skipping comment posting.")
        return result

    comment_findings = [f for f in findings if f.disposition in ("comment", "fix")]
    if not comment_findings:
        if on_status:
            on_status("No actionable findings to post.")
        return result

    max_comments = config.review_max_comments
    capped = comment_findings[:max_comments]

    summary_lines = [f"## PR Review: {len(findings)} finding(s)\n"]
    for finding in findings:
        severity_icon = {
            "critical": "🔴",
            "high": "🟠",
            "medium": "🟡",
            "low": "🟢",
            "info": "ℹ️",
        }.get(finding.severity, "•")
        summary_lines.append(
            f"- {severity_icon} **{finding.severity}** {finding.category} in `{finding.file}"
            + (f":{finding.line}" if finding.line else "")
            + f"`: {finding.description}"
        )
    summary_body = "\n".join(summary_lines)
    summary_body += "\n\n---\n*Posted by [Sigil](https://github.com/dylan-murray/sigil)*"

    if on_status:
        on_status("Posting summary comment...")

    try:
        url = await post_review_comment(client, pr_number, summary_body)
        result.summary_comment_url = url
    except Exception as exc:
        logger.warning("Failed to post summary comment: %s", exc)

    inline_comments = []
    for finding in capped:
        if finding.line and finding.file:
            inline_comments.append(
                {
                    "path": finding.file,
                    "line": finding.line,
                    "body": f"**{finding.severity}** ({finding.category}): {finding.description}\n\nSuggested fix: {finding.suggested_fix}",
                }
            )

    if inline_comments:
        if on_status:
            on_status(f"Posting {len(inline_comments)} inline comment(s)...")
        try:
            await post_inline_comments(client, pr_number, inline_comments, diff)
            result.inline_comment_count = len(inline_comments)
        except Exception as exc:
            logger.warning("Failed to post inline comments: %s", exc)

    return result
