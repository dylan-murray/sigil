"""
Test-Writer agent: writes a failing reproduction test (Red phase) before
the engineer implements the fix (Green phase).

This enforces TDD and ensures every Sigil PR has a corresponding test case.
"""

import logging
from pathlib import Path

from sigil.core.agent import Agent, Tool, ToolResult
from sigil.core.config import Config
from sigil.core.tools import (
    make_apply_edit_tool,
    make_create_file_tool,
    make_grep_tool,
    make_list_dir_tool,
    make_read_file_tool,
)
from sigil.core.utils import StatusCallback
from sigil.pipeline.models import FileTracker
from sigil.pipeline.prompts import (
    TEST_WRITER_CONTEXT_PROMPT,
    TEST_WRITER_SYSTEM_PROMPT,
)
from sigil.pipeline.ideation import FeatureIdea
from sigil.pipeline.maintenance import Finding

logger = logging.getLogger(__name__)


async def run_test_writer(
    repo: Path,
    config: Config,
    item: "Finding | FeatureIdea",
    task_description: str,
    memory_context: str,
    working_memory: str,
    repo_conventions: str,
    preloaded_files: str = "",
    ignore: list[str] | None = None,
    on_status: StatusCallback | None = None,
) -> str | None:
    """
    Run the Test-Writer agent to produce a failing reproduction test.

    Args:
        repo: Repository root path
        config: Sigil configuration
        item: The work item (finding or idea) to write a test for
        task_description: Human-readable description of the task
        memory_context: Selected knowledge files context
        working_memory: Working memory content
        repo_conventions: Repository coding conventions
        preloaded_files: Pre-loaded file content section
        ignore: Glob patterns to ignore
        on_status: Status callback

    Returns:
        A summary of the test written, or None if the agent failed to produce one
        or if the item is not bound for a PR (disposition != "pr").
    """
    # Only write tests for items that are approved for PRs
    if item.disposition != "pr":
        return None

    test_writer_model = config.model_for("test_writer")

    test_result: dict[str, str] = {"summary": ""}

    async def _task_progress_handler(args: dict) -> ToolResult:
        summary = str(args.get("summary", ""))
        test_result["summary"] = summary
        return ToolResult(
            content="Test written.",
            stop=True,
            result=summary,
        )

    tracker = FileTracker()
    tools = [
        make_read_file_tool(repo, on_status, ignore, tracker=tracker),
        make_grep_tool(repo, on_status),
        make_list_dir_tool(repo, ignore),
        make_apply_edit_tool(repo, on_status, ignore, tracker=tracker),
        make_create_file_tool(repo, on_status, ignore, tracker=tracker),
        Tool(
            name="task_progress",
            description="Signal completion and provide a summary of the test written.",
            parameters={
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": (
                            "A summary of the test you wrote: which file was modified/created, "
                            "what behavior the test verifies, and why it will fail until the fix is applied."
                        ),
                    },
                },
                "required": ["summary"],
            },
            handler=_task_progress_handler,
        ),
    ]

    context = TEST_WRITER_CONTEXT_PROMPT.format(
        memory_context=memory_context or "(no knowledge files yet)",
        working_memory=working_memory or "(no prior runs)",
        mcp_tools_section="",  # Filled in by caller if MCP is available
        preloaded_files_section=f"\n{preloaded_files}\n" if preloaded_files else "",
        task_description=task_description,
    )

    agent = Agent(
        label="test_writer",
        model=test_writer_model,
        tools=tools,
        system_prompt=TEST_WRITER_SYSTEM_PROMPT.format(repo_conventions=repo_conventions),
        max_rounds=config.max_iterations_for("test_writer"),
        max_tokens=config.max_tokens_for("test_writer") or 16_384,
        reasoning_effort=config.reasoning_effort_for("test_writer"),
    )

    try:
        result = await agent.run(
            messages=[{"role": "user", "content": context}],
            on_status=on_status,
        )
    except Exception as exc:
        logger.warning("Test-Writer agent.run failed: %s", exc)
        return None

    if result.stop_result:
        return result.stop_result

    if test_result["summary"]:
        return test_result["summary"]

    if result.last_content and len(result.last_content.strip()) > 50:
        logger.warning("Test-Writer did not call task_progress — using last text response")
        return result.last_content.strip()

    return None
