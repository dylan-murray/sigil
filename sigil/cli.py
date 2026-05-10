import asyncio
import contextlib
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Annotated

import typer
from rich.align import Align
from rich.console import Console, ConsoleOptions, Group, RenderResult
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from sigil import __version__
from sigil.core.instructions import detect_instructions
from sigil.state.attempts import prune_attempts
from sigil.state.chronic import WorkItem, filter_chronic
from sigil.core.config import CONFIG_FILE, SIGIL_DIR, Config
from sigil.pipeline.discovery import discover
from sigil.pipeline.executor import execute_parallel
from sigil.pipeline.models import ExecutionResult
from sigil.integrations.github import (
    ExistingIssue,
    create_client,
    dedup_items,
    ensure_labels,
    fetch_existing_issues,
    format_models_used,
    publish_issues,
)
from sigil.pipeline.review import ReviewResult, review_pr
from sigil.pipeline.ideation import FeatureIdea, ideate, load_open_ideas, mark_idea_done, save_ideas
from sigil.pipeline.models import boldness_allowed
from sigil.pipeline.knowledge import (
    clear_memory_cache,
    compact_knowledge,
    is_knowledge_stale,
    load_index,
    rebuild_index,
)
from sigil.core.llm import (
    BudgetExceededError,
    get_usage,
    get_usage_snapshot,
    reset_traces,
    reset_usage,
    set_budget,
    set_llm_timeout,
    set_model_overrides,
    write_trace_file,
)
from sigil.pipeline.maintenance import Finding, analyze
from sigil.core.mcp import MCPManager, connect_mcp_servers
from sigil.core.utils import StatusCallback
from sigil.pipeline.validation import validate_all
from sigil.pipeline.review import PRReviewFinding, ReviewResult, review_pr


_GRADIENT = ["#f0abfc", "#c084fc", "#a78bfa", "#818cf8", "#6366f1"]
_SPINNER_STYLE = "#a78bfa"

INIT_CONFIG_TEMPLATE = """\
# Sigil configuration — https://github.com/dylan-murray/sigil
version: 1

# LLM model for all agents (any litellm-supported model)
model: anthropic/claude-sonnet-4-6

# Risk appetite: conservative | balanced | bold | experimental
boldness: bold

# What to look for during analysis
focus:
  - tests
  - dead_code
  - security
  - docs
  - types
  - features
  - refactoring

# Glob patterns to ignore (applied to discovery, analysis, and execution)
# ignore:
#   - "vendor/**"
#   - "*.generated.*"

# Commands to run before code generation (failure aborts the task)
# pre_hooks:
#   - uv run ruff check .

# Commands to run after code generation (failure triggers retry)
# post_hooks:
#   - uv run ruff format .
#   - uv run pytest tests/ -x -q

# Max PRs and issues sigil will open per run
max_prs_per_run: 3
max_github_issues: 5

# Max feature ideas generated per run
max_ideas_per_run: 15

# Days before unimplemented ideas expire
# idea_ttl_days: 180

# Max retries when post-hooks fail
# max_retries: 2

# Max work items executed in parallel (each gets its own worktree)
# max_parallel_tasks: 3

# Hard budget cap per run (USD)
# max_spend_usd: 20.0

# Per-call LLM timeout in seconds (default: 300)
# llm_timeout: 300

# Per-agent configuration. Each value is a list of one or more instance configs.
# Multiple entries = multiple parallel instances (currently used by `ideator`
# to get diverse perspectives across models). Singletons are still lists of one.
# max_iterations controls max tool calls per agent turn.
# reasoning_effort (low | medium | high) applies to reasoning models only (e.g. o3).
# Tip: use strong models for architect/triager (plan quality matters),
#      cheaper models for auditor/compactor/selector (high volume, simple tasks).
# agents:
#   ideator:                              # multi-instance for diverse ideas
#     - model: anthropic/claude-opus-4-7
#     - model: openai/gpt-5
#       reasoning_effort: medium
#     - model: google/gemini-2.5-pro
#   architect:
#     - model: google/gemini-2.5-pro
#       max_iterations: 10
#   engineer:
#     - model: anthropic/claude-sonnet-4-6
#       max_iterations: 50
#   auditor:
#     - model: google/gemini-2.5-flash
#   triager:
#     - model: anthropic/claude-sonnet-4-6
#   compactor:
#     - model: google/gemini-2.5-flash
#       max_iterations: 5
#   memory:
#     - model: google/gemini-2.5-flash
#       max_iterations: 5
#   selector:
#     - model: google/gemini-2.5-flash
#       max_iterations: 3

# Override context/output token limits when litellm's model metadata is
# wrong or missing (e.g. newly released or self-hosted models).
# model_overrides:
#   "ollama_chat/gemma4:31b-cloud":
#     max_input_tokens: 262144
#     max_output_tokens: 262144

# Phrase in GitHub issue comments that triggers sigil to work on an issue
# directive_phrase: "@sigil work on this"

# MCP tool servers for external integrations
# mcp_servers:
#   - name: my-server
#     command: npx
#     args: ["-y", "@my-org/mcp-server"]
#     purpose: "description of what this server provides"

# Sandbox mode for code execution: none | docker
# sandbox: none
"""


def _grad(text: str, offset: int = 0) -> str:
    return "".join(
        f"[bold {_GRADIENT[(i + offset) % len(_GRADIENT)]}]{c}[/]" for i, c in enumerate(text)
    )


def _field(label: str, value: object, offset: int = 0, width: int = 15) -> str:
    padding = " " * (width - len(label))
    return f"{_grad(label, offset)}{padding} {value}"


def _prefixed(callback: StatusCallback, prefix: str) -> StatusCallback:
    return lambda msg, _cb=callback, _pfx=prefix: _cb(f"({_pfx}) {msg}")


class AnimatedGradient:
    def __init__(self, text: str = "", speed: float = 0.4):
        self._text = text
        self._ticker = ""
        self._speed = speed
        self._start = time.monotonic()

    def update(self, text: str, ticker: str = "") -> None:
        self._text = text
        self._ticker = ticker

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        offset = int((time.monotonic() - self._start) / self._speed)
        result = Text()
        for i, char in enumerate(self._text):
            color = _GRADIENT[(i + offset) % len(_GRADIENT)]
            result.append(char, style=f"bold {color}")
        if self._ticker:
            result.append_text(Text.from_markup(self._ticker))
        yield result


def _animated_status(initial: str) -> tuple[AnimatedGradient, StatusCallback]:
    gradient = AnimatedGradient(initial)

    def callback(msg: str) -> None:
        gradient.update(msg, _format_ticker())

    return gradient, callback


def _ci_status_ctx(grad):
    if _CI:
        label = grad._text if isinstance(grad, AnimatedGradient) else str(grad)
        console.print(f"[dim]{label}[/dim]")
        return contextlib.nullcontext()
    return console.status(grad, spinner_style=_SPINNER_STYLE)


def _format_cost(cost: float) -> str:
    return f"{cost:.4f}" if cost < 0.01 else f"{cost:.2f}"


def _format_ticker(snapshot: tuple[int, int, float] | None = None) -> str:
    calls, total_tok, cost = snapshot if snapshot is not None else get_usage_snapshot()
    if calls == 0:
        return ""
    if total_tok >= 10_000:
        tok_str = f"{total_tok / 1000:.0f}k"
    elif total_tok >= 1000:
        tok_str = f"{total_tok / 1000:.1f}k"
    else:
        tok_str = str(total_tok)
    return f" [dim]({tok_str} tokens, ~${_format_cost(cost)})[/dim]"


app = typer.Typer(
    name="sigil",
    help="Autonomous repo improvement agent — finds improvements and ships PRs while you sleep.",
    no_args_is_help=True,
)
_CI = os.environ.get("CI") == "true"
console = Console(force_terminal=True if _CI else None)


def version_callback(value: bool) -> None:
    if value:
        console.print(f"sigil {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option("--version", "-v", callback=version_callback, is_eager=True),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", help="Enable debug logging (includes LiteLLM)"),
    ] = False,
) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")
    if verbose:
        from sigil.core.llm import enable_verbose_logging

        enable_verbose_logging()


@app.command()
def init(
    repo: Annotated[Path, typer.Option("--repo", "-r", help="Path to repository")] = Path("."),
) -> None:
    """Initialize a Sigil project in the target repository."""
    resolved = repo.resolve()
    if not (resolved / ".git").is_dir():
        console.print(
            "[bold red]Not a git repository.[/bold red] Run sigil init from the repo root."
        )
        raise typer.Exit(1)
    config_path = resolved / SIGIL_DIR / CONFIG_FILE
    if config_path.exists():
        console.print(f"[yellow]Already initialized:[/yellow] {config_path}")
        raise typer.Exit()

    sigil_dir = resolved / SIGIL_DIR
    sigil_dir.mkdir(parents=True, exist_ok=True)
    config_path.write_text(INIT_CONFIG_TEMPLATE)

    config = Config()

    sigil_logo = (
        "[bold #f0abfc]s[/] "
        "[bold #c084fc]i[/] "
        "[bold #a78bfa]g[/] "
        "[bold #818cf8]i[/] "
        "[bold #6366f1]l[/]"
    )

    init_text = "".join(
        f"[bold {c}]{ch}[/]"
        for ch, c in zip(
            "Initialized!",
            [
                "#86efac",
                "#6ee7b7",
                "#5eead4",
                "#4ade80",
                "#34d399",
                "#2dd4bf",
                "#22c55e",
                "#10b981",
                "#14b8a6",
                "#059669",
                "#0d9488",
                "#047857",
                "#047857",
            ],
        )
    )

    fields = (
        f"{_field('Config:', config_path, 0)}\n"
        f"{_field('Default model:', config.model, 2)}\n"
        f"{_field('Boldness:', config.boldness, 4)}\n"
        f"{_field('Focus:', ', '.join(config.focus), 1)}"
    )
    console.print(
        Panel.fit(
            Group(
                Align.center(f"[bold #a78bfa]⟡[/]  {sigil_logo}"),
                "",
                Align.center(init_text),
                "",
                fields,
            ),
            border_style="#a78bfa",
        )
    )
    console.print("\n[dim]Edit .sigil/config.yml to customize, then run:[/dim]  sigil run")


@app.command()
def run(
    repo: Annotated[Path, typer.Option("--repo", "-r", help="Path to repository")] = Path("."),
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Analyze only, don't open PRs or issues")
    ] = False,
    trace: Annotated[
        bool,
        typer.Option("--trace", help="Write per-call LLM trace to .sigil/traces/last-run.json"),
    ] = False,
    refresh: Annotated[
        bool,
        typer.Option("--refresh", help="Force full knowledge rebuild, ignoring cache"),
    ] = False,
) -> None:
    """Run Sigil: analyze the repo, find improvements, and open PRs."""
    asyncio.run(_run(repo, dry_run, trace, refresh=refresh))


async def _run(repo: Path, dry_run: bool, trace: bool, *, refresh: bool = False) -> None:
    config_path = repo / SIGIL_DIR / CONFIG_FILE
    if not config_path.exists():
        console.print("[bold red]Not initialized.[/bold red] Run [bold]sigil init[/bold] first.")
        raise typer.Exit(1)

    config = Config.load(repo)

    sigil_logo = (
        "[bold #f0abfc]s[/] "
        "[bold #c084fc]i[/] "
        "[bold #a78bfa]g[/] "
        "[bold #818cf8]i[/] "
        "[bold #6366f1]l[/]"
    )

    info = (
        f"{_field('Default model:', config.model, 0)}\n"
        f"{_field('Boldness:', config.boldness, 2)}\n"
        f"{_field('Focus:', ', '.join(config.focus), 4)}\n"
        f"{_field('Dry run:', dry_run, 1)}"
    )
    console.print(
        Panel.fit(
            Group(
                Align.center(f"[bold #a78bfa]⟡[/]  {sigil_logo}"),
                "",
                info,
            ),
            border_style="#a78bfa",
        )
    )

    resolved = repo.resolve()

    async with connect_mcp_servers(config) as mcp_mgr:
        try:
            await _run_pipeline(resolved, config, dry_run, mcp_mgr, refresh=refresh, trace=trace)
        except BudgetExceededError as exc:
            console.print(f"\n[bold red]Budget exceeded:[/bold red] {exc}")
            usage = get_usage()
            console.print(
                f"[dim]Total cost: ${usage.cost_usd:.2f} | Limit: ${config.max_spend_usd:.2f}[/dim]"
            )
            if trace:
                write_trace_file(resolved)
            raise typer.Exit(1)

    if trace:
        trace_path = write_trace_file(resolved)
        if trace_path:
            console.print(f"[dim]Trace written to {trace_path}[/dim]")


async def _run_pipeline(
    resolved: Path,
    config: Config,
    dry_run: bool,
    mcp_mgr: MCPManager,
    *,
    refresh: bool = False,
    trace: bool = False,
) -> None:
    if mcp_mgr.server_count > 0:
        console.print(
            f"[dim]MCP: {mcp_mgr.server_count} server(s), {mcp_mgr.tool_count} tool(s)[/dim]"
        )

    gh_client = None
    existing_issues: list[ExistingIssue] = []
    if not dry_run:
        gh_client = await create_client(resolved)
        if gh_client:
            await ensure_labels(gh_client)
            console.print("[dim]GitHub client connected[/dim]")

            existing_issues = await fetch_existing_issues(
                gh_client,
                directive_phrase=config.directive_phrase,
            )
            directive_count = sum(1 for i in existing_issues if i.has_directive)
            console.print(
                f"[dim]Fetched {len(existing_issues)} existing issue(s)"
                f"{f', {directive_count} directive(s)' if directive_count else ''}[/dim]"
            )
        else:
            console.print(
                "[bold red]Error: GitHub credentials required for live runs. Set GITHUB_TOKEN or use --dry-run.[/bold red]"
            )
            raise typer.Exit(1)

    clear_memory_cache()
    reset_usage()
    reset_traces(resolved if trace else None)
    set_budget(config.max_spend_usd)
    set_llm_timeout(config.llm_timeout)
    set_model_overrides(config.model_overrides)
    run_id = uuid.uuid4().hex[:12]
    pruned = prune_attempts(resolved)
    if pruned:
        console.print(f"[dim]Pruned {pruned} old attempt(s) from log[/dim]")
    stages_ran: list[str] = []

    if refresh or await is_knowledge_stale(resolved):
        discovery_model = config.model_for("discovery")
        compact_model = config.model_for("compactor")

        grad, on_update = _animated_status("Discovering repo...")
        with _ci_status_ctx(grad):
            discovery = await discover(
                resolved,
                discovery_model,
                ignore=config.effective_ignore or None,
                on_status=on_update,
            )

        console.print("[green]Discovery complete[/green]")

        grad, on_update = _animated_status("Compacting knowledge...")
        with _ci_status_ctx(grad):
            await compact_knowledge(
                resolved,
                compact_model,
                discovery,
                force_full=refresh,
                compactor_max_tokens=config.max_tokens_for("compactor"),
                discovery_max_tokens=config.max_tokens_for("discovery"),
                on_status=on_update,
            )

        console.print("[dim]Knowledge updated[/dim]")
        stages_ran.append("discovery")
    else:
        console.print("[dim]Knowledge is fresh — skipping discovery[/dim]")
        rebuild_index(resolved)
    index_md = load_index(resolved)
    if index_md:
        entry_count = sum(1 for line in index_md.splitlines() if line.strip().startswith("##"))
        console.print(f"[dim]Knowledge index loaded ({entry_count} sections)[/dim]")

    instructions = detect_instructions(resolved)
    if instructions.has_instructions:
        console.print(
            f"[dim]Agent config: {', '.join(instructions.detected_files)} ({instructions.source})[/dim]"
        )

    grad, on_update = _animated_status("Analyzing + ideating in parallel...")
    with _ci_status_ctx(grad):
        findings, ideas = await asyncio.gather(
            analyze(
                resolved,
                config,
                instructions=instructions,
                mcp_mgr=mcp_mgr,
                on_status=_prefixed(on_update, "audit"),
            ),
            ideate(
                resolved,
                config,
                instructions=instructions,
                on_status=_prefixed(on_update, "ideate"),
            ),
        )
    stages_ran.extend(["analysis", "ideation"])

    backlog = load_open_ideas(resolved, ttl_days=config.idea_ttl_days)
    if backlog:
        eligible = [i for i in backlog if boldness_allowed(i.boldness, config.boldness)]
        skipped = len(backlog) - len(eligible)
        if skipped:
            console.print(f"[dim]Filtered {skipped} idea(s) above {config.boldness} boldness[/dim]")
        if eligible:
            console.print(f"[dim]Loaded {len(eligible)} open idea(s) from backlog[/dim]")
            existing_titles = {i.title for i in ideas}
            for idea in eligible:
                if idea.title not in existing_titles:
                    ideas.append(idea)

    if not findings and not ideas:
        console.print("[green]No findings or ideas.[/green]")
        return

    if findings:
        console.print(f"[dim]Found {len(findings)} finding(s)[/dim]")
    if ideas:
        console.print(f"[dim]Proposed {len(ideas)} idea(s)[/dim]")

    stages_ran.append("validation")
    console.print(f"[dim]Validating {len(findings) + len(ideas)} candidate(s)...[/dim]")
    grad, on_update = _animated_status("Validating all candidates...")
    with _ci_status_ctx(grad):
        result = await validate_all(
            resolved,
            config,
            findings,
            ideas,
            existing_issues=existing_issues,
            instructions=instructions,
            mcp_mgr=mcp_mgr,
            on_status=on_update,
        )
    validated = result.findings
    validated_ideas = result.ideas

    pr_items = [f for f in validated if f.disposition == "pr" and not config.is_ignored(f.file)]
    issue_items = [f for f in validated if f.disposition == "issue"]
    skipped = [
        f
        for f in validated
        if f.disposition == "skip" or (f.disposition == "pr" and config.is_ignored(f.file))
    ]

    idea_prs = [i for i in validated_ideas if i.disposition == "pr"]
    idea_issues = [i for i in validated_ideas if i.disposition == "issue"]

    if pr_items:
        lines = [_format_finding_line(f) for f in pr_items]
        console.print(
            Panel(
                "\n".join(lines),
                title=f"Finding PRs ({len(pr_items)})",
                border_style="green",
            )
        )

    if issue_items:
        lines = [_format_finding_line(f) for f in issue_items]
        console.print(
            Panel(
                "\n".join(lines),
                title=f"Finding Issues ({len(issue_items)})",
                border_style="yellow",
            )
        )

    vetoed_findings = len(findings) - len(validated)
    skipped_count = len(skipped)
    if vetoed_findings or skipped_count:
        parts = []
        if vetoed_findings:
            parts.append(f"Vetoed: {vetoed_findings}")
        if skipped_count:
            parts.append(f"Skipped: {skipped_count}")
        console.print(f"[dim]{', '.join(parts)}[/dim]")

    if idea_prs:
        lines = [_format_idea_line(i) for i in idea_prs]
        console.print(
            Panel(
                "\n".join(lines),
                title=f"Idea PRs ({len(idea_prs)})",
                border_style="#6366f1",
            )
        )

    if idea_issues:
        lines = [_format_idea_line(i) for i in idea_issues]
        console.print(
            Panel(
                "\n".join(lines),
                title=f"Idea Issues ({len(idea_issues)})",
                border_style="#f59e0b",
            )
        )

    if validated_ideas:
        save_ideas(resolved, validated_ideas)

    if len(validated_ideas) < len(ideas):
        console.print(f"[dim]Ideas vetoed: {len(ideas) - len(validated_ideas)}[/dim]")


@app.command()
def review(
    repo: Annotated[Path, typer.Option("--repo", "-r", help="Path to repository")] = Path("."),
    pr: Annotated[int, typer.Option("--pr", help="PR number to review")] = ...,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show findings without posting comments")
    ] = False,
    trace: Annotated[
        bool,
        typer.Option("--trace", help="Write per-call LLM trace to .sigil/traces/last-run.json"),
    ] = False,
) -> None:
    """Review a pull request and post comments."""
    asyncio.run(_review(repo, pr, dry_run, trace))


async def _review(repo: Path, pr_number: int, dry_run: bool, trace: bool) -> None:
    config_path = repo / SIGIL_DIR / CONFIG_FILE
    if not config_path.exists():
        console.print("[bold red]Not initialized.[/bold red] Run [bold]sigil init[/bold] first.")
        raise typer.Exit(1)

    config = Config.load(repo)
    resolved = repo.resolve()

    sigil_logo = (
        "[bold #f0abfc]s[/] "
        "[bold #c084fc]i[/] "
        "[bold #a78bfa]g[/] "
        "[bold #818cf8]i[/] "
        "[bold #6366f1]l[/]"
    )

    info = (
        f"{_field('PR:', f'#{pr_number}', 0)}\n"
        f"{_field('Model:', config.model, 2)}\n"
        f"{_field('Dry run:', dry_run, 4)}"
    )
    console.print(
        Panel.fit(
            Group(
                Align.center(f"[bold #a78bfa]⟡[/]  {sigil_logo}"),
                "",
                Align.center("[bold #86efac]Review Mode[/]"),
                "",
                info,
            ),
            border_style="#a78bfa",
        )
    )

    gh_client = None
    if not dry_run:
        gh_client = await create_client(resolved)
        if not gh_client:
            console.print(
                "[bold red]Error: GitHub credentials required for review. "
                "Set GITHUB_TOKEN or use --dry-run.[/bold red]"
            )
            raise typer.Exit(1)

    clear_memory_cache()
    reset_usage()
    reset_traces(resolved if trace else None)
    set_budget(config.max_spend_usd)
    set_llm_timeout(config.llm_timeout)
    set_model_overrides(config.model_overrides)

    grad, on_update = _animated_status(f"Reviewing PR #{pr_number}...")
    with _ci_status_ctx(grad):
        result = await review_pr(
            resolved,
            config,
            gh_client,
            pr_number,
            dry_run=dry_run,
            on_status=on_update,
        )

    if trace:
        trace_path = write_trace_file(resolved)
        if trace_path:
            console.print(f"[dim]Trace written to {trace_path}[/dim]")

    _print_review_result(result, dry_run)


def _print_review_result(result: ReviewResult, dry_run: bool) -> None:
    mode_label = "[dim](dry run)[/dim] " if dry_run else ""

    if not result.findings:
        console.print(f"{mode_label}[green]No issues found in PR.[/green]")
        return

    lines = []
    for f in result.findings:
        loc = f"{f.file}:{f.line}" if f.line else f.file
        disp = "[green]fix[/green]" if f.disposition == "fix" else "[yellow]comment[/yellow]"
        lines.append(f"  {disp} [{f.severity}] {loc}: {f.description}")

    title = f"Review Findings ({len(result.findings)})"
    console.print(Panel("\n".join(lines), title=title, border_style="yellow"))

    if result.summary_comment_url:
        console.print(f"{mode_label}Summary comment: {result.summary_comment_url}")
    if result.inline_comment_count:
        console.print(f"{mode_label}Posted {result.inline_comment_count} inline comment(s)")
    if result.fix_pr_url:
        console.print(f"{mode_label}Fix PR: {result.fix_pr_url}")


def _format_finding_line(f: Finding) -> str:
    loc = f.file
    if f.line:
        loc = f"{f.file}:{f.line}"
    return (
        f"  [bold]#{f.priority}[/bold]  {f.category} | {loc} | risk: {f.risk}\n"
        f"    {f.description}\n"
        f"    [dim]{f.suggested_fix}[/dim]"
    )


def _format_idea_line(idea: FeatureIdea) -> str:
    return (
        f"  [bold]#{idea.priority}[/bold]  {idea.title} ({idea.complexity})\n"
        f"    {idea.description[:200]}\n"
        f"    [dim]{idea.rationale[:200]}[/dim]"
    )
