#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

python3 - <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from sigil.core.llm import estimate_tokens
from sigil.pipeline.prompts import (
    ENGINEER_SYSTEM_PROMPT,
    EXECUTOR_CONTEXT_PROMPT,
    EXECUTOR_TASK_PROMPT,
    EXECUTOR_TASK_PROMPT_WITH_PLAN,
    ARCHITECT_SYSTEM_PROMPT,
    ARCHITECT_CONTEXT_PROMPT,
    HOOK_SUMMARIZE_PROMPT,
    REVIEWER_SYSTEM_PROMPT,
    REVIEWER_CONTEXT_PROMPT,
    ENGINEER_FIX_PROMPT,
    HOOK_FIX_INJECT_PROMPT,
    AUDITOR_SYSTEM_PROMPT,
    ANALYSIS_CONTEXT_PROMPT,
    IDEATOR_SYSTEM_PROMPT,
    IDEATION_CONTEXT_PROMPT,
    TRIAGER_SYSTEM_PROMPT,
    VALIDATION_CONTEXT_PROMPT,
    ARBITER_SYSTEM_PROMPT,
    ARBITER_CONTEXT_PROMPT,
    REBALANCE_PROMPT,
)
from sigil.pipeline.validation import REVIEW_ITEM_PARAMS, RESOLVE_ITEM_PARAMS
from sigil.pipeline.ideation import REPORT_IDEA_PARAMS
from sigil.pipeline.maintenance import (
    REPORT_FINDING_PARAMS,
)
from sigil.core.agent import Agent
import json


def tok(text: str) -> int:
    return estimate_tokens([{"role": "user", "content": text}])


def schema_toks(schema: dict) -> int:
    return estimate_tokens([{"role": "user", "content": json.dumps(schema)}])


# System prompts
system_prompts = {
    "engineer": ENGINEER_SYSTEM_PROMPT,
    "architect": ARCHITECT_SYSTEM_PROMPT,
    "reviewer": REVIEWER_SYSTEM_PROMPT,
    "auditor": AUDITOR_SYSTEM_PROMPT,
    "ideator": IDEATOR_SYSTEM_PROMPT,
    "triager": TRIAGER_SYSTEM_PROMPT,
    "arbiter": ARBITER_SYSTEM_PROMPT,
}

system_prompt_toks = sum(tok(p) for p in system_prompts.values())

# Context prompt templates (fill with minimal realistic stubs)
repo_conventions = "Python 3.11+, typer, rich, litellm. No comments. F-strings. Type hints."
memory_context = "### index.md\nThis is a Python CLI tool.\n"
working_memory = "No prior runs."
repo_tree = "sigil/\n  cli.py\n  core/\n    agent.py\n    llm.py\n  pipeline/\n    prompts.py\n"
preloaded_files = ""
task_description = "Fix a bug in sigil.core.llm"
focus_areas = "tests, dead_code, security, docs, types, features, refactoring"
existing_ideas = "- [open] Add caching (medium)"
items_list = "[0] #1 [pr] bug | sigil/core/llm.py | risk: low\n    A problem.\n    Fix: do thing.\n    Rationale: because"
mcp_tools_section = ""
existing_issues_section = ""
disagreements = "[0] bug | sigil/core/llm.py: A problem\n  Reviewer A: approve\n  Reviewer B: veto"
raw_output = "error in file.py:12\n  NameError: foo"
plan = "Modify sigil/core/llm.py to fix the bug."
items_summary = "[0] priority=1 | approve | good idea"

context_prompts = {
    "executor": EXECUTOR_CONTEXT_PROMPT.format(
        memory_context=memory_context,
        working_memory=working_memory,
        mcp_tools_section=mcp_tools_section,
        preloaded_files_section=preloaded_files,
    ),
    "executor_task": EXECUTOR_TASK_PROMPT.format(task_description=task_description),
    "executor_task_plan": EXECUTOR_TASK_PROMPT_WITH_PLAN.format(
        task_description=task_description, plan=plan
    ),
    "architect": ARCHITECT_CONTEXT_PROMPT.format(
        memory_context=memory_context,
        working_memory=working_memory,
        repo_tree=repo_tree,
        preloaded_files_section=preloaded_files,
        task_description=task_description,
    ),
    "reviewer": REVIEWER_CONTEXT_PROMPT.format(
        task_description=task_description,
        memory_context=memory_context,
        diff="diff --git a/sigil/core/llm.py\n+foo\n-bar",
        created_files="sigil/core/llm.py",
        modified_files="sigil/core/llm.py",
    ),
    "engineer_fix": ENGINEER_FIX_PROMPT.format(
        feedback="Fix the import.",
        created_files="",
        modified_files="sigil/core/llm.py",
    ),
    "hook_fix": HOOK_FIX_INJECT_PROMPT.format(error_block="Import error"),
    "hook_summary": HOOK_SUMMARIZE_PROMPT.format(raw_output=raw_output),
    "analysis": ANALYSIS_CONTEXT_PROMPT.format(
        focus_areas=focus_areas,
        memory_context=memory_context,
        working_memory=working_memory,
        max_reads=5,
        mcp_tools_section=mcp_tools_section,
    ),
    "ideation": IDEATION_CONTEXT_PROMPT.format(
        memory_context=memory_context,
        working_memory=working_memory,
        existing_ideas=existing_ideas,
        max_ideas=7,
    ),
    "validation": VALIDATION_CONTEXT_PROMPT.format(
        memory_context=memory_context,
        working_memory=working_memory,
        items_list=items_list,
        mcp_tools_section=mcp_tools_section,
        existing_issues_section=existing_issues_section,
    ),
    "arbiter": ARBITER_CONTEXT_PROMPT.format(
        memory_context=memory_context,
        working_memory=working_memory,
        disagreements=disagreements,
    ),
    "rebalance": REBALANCE_PROMPT.format(items_summary=items_summary),
}

context_prompt_toks = sum(tok(p) for p in context_prompts.values())

# Tool schemas (these get sent with every agent call)
tool_schemas = {
    "review_item": REVIEW_ITEM_PARAMS,
    "resolve_item": RESOLVE_ITEM_PARAMS,
    "report_idea": REPORT_IDEA_PARAMS,
    "report_finding": REPORT_FINDING_PARAMS,
}

tool_schema_toks = sum(schema_toks(s) for s in tool_schemas.values())

# Simulate a representative agent's initial message history
# This captures the tool batching instruction and system message formatting
agent = Agent(
    label="engineer",
    model="anthropic/claude-sonnet-4-6",
    tools=[],
    system_prompt=ENGINEER_SYSTEM_PROMPT.format(repo_conventions=repo_conventions),
)
system_msg = agent._system_message()
agent_setup_toks = tok(system_msg.get("content", "")) if system_msg else 0

# Compaction prompt adds overhead
from sigil.core.llm import COMPACTION_PROMPT
compaction_toks = tok(COMPACTION_PROMPT.format(conversation="some conversation text here"))

# Additional fixed overhead: masking constants, tool result max chars threshold, etc.
# Count the masking strings as they appear in the prompt history
from sigil.core.llm import (
    _MASKED_READ,
    _MASKED_MCP,
    _MASKED_SEARCH,
    _MASKED_GREP,
    _MASKED_READ_STALE,
)
masking_toks = sum(tok(s) for s in [_MASKED_READ, _MASKED_MCP, _MASKED_SEARCH, _MASKED_GREP, _MASKED_READ_STALE])

total = (
    system_prompt_toks
    + context_prompt_toks
    + tool_schema_toks
    + agent_setup_toks
    + compaction_toks
    + masking_toks
)

print(f"METRIC total_prompt_toks={total}")
print(f"METRIC system_prompt_toks={system_prompt_toks}")
print(f"METRIC context_prompt_toks={context_prompt_toks}")
print(f"METRIC tool_schema_toks={tool_schema_toks}")
print(f"METRIC agent_setup_toks={agent_setup_toks}")
print(f"METRIC compaction_toks={compaction_toks}")
print(f"METRIC masking_toks={masking_toks}")
PY
