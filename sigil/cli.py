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
from sigil.state.chronic import filter_chronic
from sigil.core.config import CONFIG_FILE, SIGIL_DIR, Config
from sigil.pipeline.discovery import discover
from sigil.pipeline.executor import execute_parallel
from sigil.pipeline.models import ExecutionResult
from sigil.integrations.github import (
    ExistingIssue,
    cleanup_after_push,
    create_client,
    dedup_items,
    ensure_labels,
    fetch_existing_issues,
    publish_results,
)
from sigil.pipeline.ideation import FeatureIdea, ideate, load_open_ideas, mark_idea_done, save_ideas
from sigil.pipeline.models import boldness_allowed
from sigil.pipeline.knowledge import (
    clear_memory_cache,
    compact_knowledge,
    is_knowledge_stale,
    load_index,
    rebuild_index,
)
from sigil.pipeline.style import extract_style
from sigil.core.llm import (
    BudgetExceededError,
    get_usage,
    get_usage_snapshot,
    reset_traces,
    reset_usage,
    set_budget,
    write_trace_file,
)
from sigil.pipeline.maintenance import Finding, analyze
from sigil.core.mcp import MCPManager, connect_mcp_servers
from sigil.core.utils import StatusCallback
from sigil.pipeline.validation import validate_all


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

# Enable parallel validation with two challengers + arbiter
# arbiter: true

# Per-agent model and iteration overrides (any litellm-supported model)
# max_iterations controls max tool calls per agent turn
# Tip: use strong models for architect/triager (plan quality matters),
#      cheaper models for auditor/compactor/selector (high volume, simple tasks)
# agents:
#   architect:
#     model: google/gemini-2.5-pro       # plans implementation approach
#     max_iterations: 10
#   engineer:
#     model: anthropic/claude-sonnet-4-6  # writes the actual code
#     max_iterations: 50
#   auditor:
#     model: google/gemini-2.5-flash      # scans for bugs and issues
#     max_iterations: 15
#   ideator:
#     model: google/gemini-2.5-flash      # proposes new features
#     max_iterations: 15
#   triager:
#     model: anthropic/claude-sonnet-4-6  # ranks and filters findings/ideas
#     max_iterations: 15
#   challenger:
#     model: google/gemini-2.5-flash      # second opinion on triager (parallel mode)
#     max_iterations: 15
#   arbiter:
#     model: google/gemini-2.5-pro        # resolves disagreements (parallel mode)
#     max_iterations: 10
#   reviewer:
#     model: google/gemini-2.5-flash      # reviews code changes
#     max_iterations: 15
#   compactor:
#     model: google/gemini-2.5-flash      # compresses knowledge files
#     max_iterations: 5
#   memory:
#     model: google/gemini-2.5-flash      # updates working memory
#     max_iterations: 5
#   selector:
#     model: google/gemini-2.5-flash      # picks which knowledge files to load
#     max_iterations: 3

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
            await extract_style(
                resolved,
                compact_model,
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

    execution_results: list[tuple[str, ExecutionResult]] = []
    parallel_results: list[tuple] = []

    all_pr_items = pr_items + idea_prs
    all_issue_items = issue_items + idea_issues

    if gh_client and not dry_run:
        grad, _ = _animated_status("Deduplicating against existing PRs/issues...")
        with _ci_status_ctx(grad):
            pr_dedup = await dedup_items(gh_client, all_pr_items)
            issue_dedup = await dedup_items(gh_client, all_issue_items)
        if pr_dedup.skipped:
            console.print(f"[dim]Dedup: skipped {len(pr_dedup.skipped)} PR item(s)[/dim]")
        if issue_dedup.skipped:
            console.print(f"[dim]Dedup: skipped {len(issue_dedup.skipped)} issue item(s)[/dim]")
        all_pr_items = pr_dedup.remaining
        all_issue_items = issue_dedup.remaining

    if not dry_run:
        pre_chronic_pr_count = len(all_pr_items)
        all_pr_items, all_issue_items, chronic_skipped = filter_chronic(
            resolved, all_pr_items, all_issue_items
        )
        chronic_downgraded = pre_chronic_pr_count - len(all_pr_items) - len(chronic_skipped)
        if chronic_skipped:
            console.print(
                f"[dim]Chronic: skipped {len(chronic_skipped)} item(s) with 3+ prior failures[/dim]"
            )
        if chronic_downgraded > 0:
            console.print(f"[dim]Chronic: downgraded {chronic_downgraded} item(s) to issues[/dim]")

        overflow = all_pr_items[config.max_prs_per_run :]
        all_pr_items = all_pr_items[: config.max_prs_per_run]
        if overflow:
            all_issue_items.extend(overflow)
            console.print(
                f"[dim]Capped PRs to {config.max_prs_per_run}, "
                f"moved {len(overflow)} item(s) to issues[/dim]"
            )

        if all_pr_items:
            stages_ran.append("execution")
            console.print(
                f"\n[bold green]Executing {len(all_pr_items)} item(s) "
                f"(max {config.max_parallel_tasks} parallel)...[/bold green]"
            )

            agent_states: dict[str, str] = {}
            finished: dict[str, bool] = {}
            _table_start = time.monotonic()

            class _AgentRow:
                def __init__(self, slug: str) -> None:
                    self.slug = slug
                    self.status = ""
                    self.spinner = Spinner("dots", style=_SPINNER_STYLE)

                def rich_slug(self) -> Text:
                    offset = int((time.monotonic() - _table_start) / 0.4)
                    t = Text()
                    for i, char in enumerate(self.slug):
                        color = _GRADIENT[(i + offset) % len(_GRADIENT)]
                        t.append(char, style=f"bold {color}")
                    return t

            class _AgentTable:
                def __rich_console__(
                    self, console: Console, options: ConsoleOptions
                ) -> RenderResult:
                    table = Table(
                        show_header=False,
                        box=None,
                        padding=(0, 1),
                        expand=False,
                    )
                    table.add_column(width=3)
                    table.add_column(no_wrap=True)
                    table.add_column(style="dim")
                    for slug in list(agent_rows):
                        row = agent_rows[slug]
                        if slug in finished:
                            ok = finished[slug]
                            marker = Text("OK " if ok else "ERR", style="green" if ok else "red")
                            table.add_row(marker, row.rich_slug(), row.status)
                        else:
                            table.add_row(row.spinner, row.rich_slug(), row.status)
                    yield table
                    ticker = _format_ticker()
                    if ticker:
                        yield Text.from_markup(ticker)

            agent_rows: dict[str, _AgentRow] = {}
            renderable = _AgentTable()

            live = Live(
                renderable,
                console=console,
                refresh_per_second=8,
                vertical_overflow="crop",
            )

            def _on_item_status(slug: str, msg: str) -> None:
                agent_states[slug] = msg
                if _CI:
                    console.print(f"[dim]{slug}: {msg}[/dim]")
                    return
                if slug not in agent_rows:
                    agent_rows[slug] = _AgentRow(slug)
                agent_rows[slug].status = msg

            def _on_item_done(slug: str, success: bool) -> None:
                finished[slug] = success
                if slug in agent_rows:
                    agent_rows[slug].status = "Done" if success else "Failed"

            if not _CI:
                live.start()
            try:
                parallel_results = await execute_parallel(
                    resolved,
                    config,
                    all_pr_items,
                    run_id=run_id,
                    instructions=instructions,
                    mcp_mgr=mcp_mgr,
                    on_item_status=_on_item_status,
                    on_item_done=_on_item_done,
                )
            finally:
                if not _CI:
                    live.stop()
            exec_lines: list[str] = []
            for item, result, branch in parallel_results:
                label = item.description[:60] if isinstance(item, Finding) else item.title[:60]
                execution_results.append((label, result))
                if result.success and isinstance(item, FeatureIdea):
                    mark_idea_done(resolved, item.title)
                if result.success:
                    exec_lines.append(
                        f"  [green]OK[/green] {label} "
                        f"[dim](retries: {result.retries}, +{len(result.diff.splitlines())} lines)[/dim]"
                    )
                else:
                    exec_lines.append(
                        f"  [red]FAIL[/red] {label} — {result.failure_reason} "
                        f"[dim](retries: {result.retries})[/dim]"
                    )
                if branch:
                    exec_lines.append(f"    [dim]branch: {branch}[/dim]")
                if result.downgraded and not result.diff:
                    all_issue_items.append(item)
                    exec_lines.append(
                        f"    [yellow]Downgraded to issue[/yellow] — {result.failure_reason}"
                    )
                elif result.downgraded and result.diff:
                    exec_lines.append(
                        f"    [yellow]Opening PR with failing hooks[/yellow] — {result.failure_reason}"
                    )
            if exec_lines:
                ok_count = sum(1 for _, r, _ in parallel_results if r.success)
                fail_count = len(parallel_results) - ok_count
                title = f"Execution Results ({ok_count} ok, {fail_count} failed)"
                console.print(
                    Panel(
                        "\n".join(exec_lines),
                        title=title,
                        border_style="green"
                        if fail_count == 0
                        else "red"
                        if ok_count == 0
                        else "#f59e0b",
                    )
                )

    pr_urls: list[str] = []
    issue_urls: list[str] = []

    if gh_client and not dry_run:
        issue_tuples: list[tuple] = []
        for item in all_issue_items:
            ctx = None
            for pi, pr, pb in parallel_results:
                if pi is item and pr.downgraded:
                    ctx = pr.downgrade_context
                    break
            issue_tuples.append((item, ctx))

        grad, _ = _animated_status("Publishing to GitHub...")
        with _ci_status_ctx(grad):
            pr_urls, issue_urls, pushed_branches = await publish_results(
                resolved,
                config,
                gh_client,
                parallel_results,
                issue_tuples,
                instructions=instructions,
            )

        if pr_urls:
            console.print(
                Panel(
                    "\n".join(f"  {url}" for url in pr_urls),
                    title=f"Opened {len(pr_urls)} PR(s)",
                    border_style="green",
                )
            )
        if issue_urls:
            console.print(
                Panel(
                    "\n".join(f"  {url}" for url in issue_urls),
                    title=f"Opened {len(issue_urls)} issue(s)",
                    border_style="yellow",
                )
            )

        await cleanup_after_push(resolved, parallel_results, pushed_branches)

    usage = get_usage()
    if usage.calls > 0:
        lines = [f"LLM calls: {usage.calls}  |  Est. cost: ~${_format_cost(usage.cost_usd)}"]
        for model_name, m in sorted(usage.by_model.items()):
            cache_info = ""
            if m.cache_read_tokens > 0 or m.cache_creation_tokens > 0:
                cache_info = (
                    f", cache: {m.cache_read_tokens:,} read / {m.cache_creation_tokens:,} write"
                )
            lines.append(
                f"  {model_name}: {m.calls} calls, "
                f"{m.prompt_tokens:,} in / {m.completion_tokens:,} out{cache_info}, "
                f"~${_format_cost(m.cost_usd)}"
            )
        console.print(Panel("\n".join(lines), title="Token Usage"))


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
