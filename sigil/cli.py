from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.panel import Panel

from sigil import __version__
from sigil.config import SIGIL_DIR, CONFIG_FILE, Config, DEFAULT_MODEL
from sigil.discovery import discover
from sigil.executor import ExecutionResult, execute_parallel
from sigil.ideation import FeatureIdea, ideate, save_ideas, validate_ideas
from sigil.knowledge import compact_knowledge, is_knowledge_stale, load_index
from sigil.maintenance import Finding, analyze
from sigil.memory import update_working
from sigil.validation import validate

app = typer.Typer(
    name="sigil",
    help="Autonomous repo improvement agent — finds improvements and ships PRs while you sleep.",
    no_args_is_help=True,
)
console = Console()


def version_callback(value: bool) -> None:
    if value:
        console.print(f"sigil {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        Optional[bool],
        typer.Option("--version", "-v", callback=version_callback, is_eager=True),
    ] = None,
) -> None:
    pass


@app.command()
def init(
    repo: Annotated[Path, typer.Option("--repo", "-r", help="Path to repository")] = Path("."),
    model: Annotated[str, typer.Option("--model", "-m", help="LLM model to use")] = DEFAULT_MODEL,
) -> None:
    """Initialize Sigil in a repository. Analyzes the repo and generates .sigil/config.yml."""
    sigil_dir = repo / SIGIL_DIR
    config_path = sigil_dir / CONFIG_FILE

    if config_path.exists():
        console.print(f"[yellow]Config already exists at {config_path}[/yellow]")
        raise typer.Exit(1)

    sigil_dir.mkdir(parents=True, exist_ok=True)

    config = Config(model=model)
    config_path.write_text(config.to_yaml())

    console.print(
        Panel.fit(
            f"[green]Sigil initialized![/green]\n\n"
            f"Config: {config_path}\n"
            f"Model:  {config.model}\n"
            f"Bold:   {config.boldness}\n"
            f"Focus:  {', '.join(config.focus)}",
            title="sigil",
        )
    )
    console.print("\nNext: run [bold]sigil run --repo .[/bold] to analyze and open PRs.")


@app.command()
def run(
    repo: Annotated[Path, typer.Option("--repo", "-r", help="Path to repository")] = Path("."),
    ci: Annotated[
        bool, typer.Option("--ci", help="CI mode: no prompts, stricter conservatism")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Analyze only, don't open PRs or issues")
    ] = False,
    model: Annotated[
        Optional[str], typer.Option("--model", "-m", help="Override model from config")
    ] = None,
) -> None:
    """Run Sigil: analyze the repo, find improvements, and open PRs."""
    config = Config.load(repo)
    if model:
        config = Config(
            model=model,
            boldness=config.boldness,
            focus=config.focus,
            ignore=config.ignore,
            max_prs_per_run=config.max_prs_per_run,
            max_issues_per_run=config.max_issues_per_run,
            max_ideas_per_run=config.max_ideas_per_run,
            idea_ttl_days=config.idea_ttl_days,
            schedule=config.schedule,
            lint_cmd=config.lint_cmd,
            test_cmd=config.test_cmd,
            max_retries=config.max_retries,
        )

    console.print(
        Panel.fit(
            f"Model:    {config.model}\n"
            f"Boldness: {config.boldness}\n"
            f"Focus:    {', '.join(config.focus)}\n"
            f"CI mode:  {ci}\n"
            f"Dry run:  {dry_run}",
            title="sigil run",
        )
    )

    resolved = repo.resolve()

    if is_knowledge_stale(resolved):
        with console.status("[bold green]Discovering repo..."):
            discovery_context = discover(resolved, config.model)

        console.print("[green]Discovery complete[/green]")

        with console.status("[bold green]Compacting knowledge..."):
            compact_knowledge(resolved, config.model, discovery_context)

        console.print("[dim]Knowledge updated[/dim]")
    else:
        console.print("[dim]Knowledge is fresh — skipping discovery[/dim]")

    index_md = load_index(resolved)
    if index_md:
        console.print(Panel.fit(index_md[:2000], title=".sigil/memory/INDEX.md"))

    with console.status("[bold green]Analyzing + ideating in parallel..."):
        with ThreadPoolExecutor(max_workers=2) as pool:
            findings_future = pool.submit(analyze, resolved, config)
            ideas_future = pool.submit(ideate, resolved, config)
            findings = findings_future.result()
            ideas = ideas_future.result()

    if not findings and not ideas:
        console.print("[green]No findings or ideas.[/green]")
        return

    if findings:
        console.print(f"[dim]Found {len(findings)} finding(s), validating...[/dim]")
        with console.status("[bold green]Validating findings..."):
            validated = validate(resolved, config, findings)
    else:
        validated = []

    if ideas:
        console.print(f"[dim]Proposed {len(ideas)} idea(s), reviewing...[/dim]")
        with console.status("[bold green]Reviewing ideas..."):
            validated_ideas = validate_ideas(resolved, config, ideas)
    else:
        validated_ideas = []

    pr_items = [f for f in validated if f.disposition == "pr"][: config.max_prs_per_run]
    issue_items = [f for f in validated if f.disposition == "issue"][: config.max_issues_per_run]
    skipped = [f for f in validated if f.disposition == "skip"]

    idea_prs = [i for i in validated_ideas if i.disposition == "pr"]
    idea_issues = [i for i in validated_ideas if i.disposition == "issue"]

    if pr_items:
        console.print(f"\n[bold green]PR candidates ({len(pr_items)}):[/bold green]")
        for f in pr_items:
            _print_finding(f)

    if issue_items:
        console.print(f"\n[bold yellow]Issue candidates ({len(issue_items)}):[/bold yellow]")
        for f in issue_items:
            _print_finding(f)

    if skipped:
        console.print(f"\n[dim]Skipped: {len(skipped)} finding(s)[/dim]")

    vetoed = len(findings) - len(validated)
    if vetoed:
        console.print(f"[dim]Vetoed: {vetoed} finding(s)[/dim]")

    if idea_prs:
        console.print(f"\n[bold green]Idea PR candidates ({len(idea_prs)}):[/bold green]")
        for idea in idea_prs:
            _print_idea(idea)

    if idea_issues:
        console.print(f"\n[bold yellow]Idea issue candidates ({len(idea_issues)}):[/bold yellow]")
        for idea in idea_issues:
            _print_idea(idea)

    if validated_ideas:
        save_ideas(resolved, validated_ideas)

    ideas_vetoed = len(ideas) - len(validated_ideas)
    if ideas_vetoed:
        console.print(f"[dim]Ideas vetoed: {ideas_vetoed}[/dim]")

    execution_results: list[tuple[str, ExecutionResult]] = []

    if not dry_run:
        all_pr_items = pr_items + idea_prs
        if all_pr_items:
            console.print(
                f"\n[bold green]Executing {len(all_pr_items)} item(s) "
                f"(max {config.max_parallel_agents} parallel)...[/bold green]"
            )
            with console.status("[bold green]Executing in worktrees..."):
                parallel_results = execute_parallel(resolved, config, all_pr_items)
            for item, result, branch in parallel_results:
                label = item.description[:60] if isinstance(item, Finding) else item.title[:60]
                execution_results.append((label, result))
                _print_execution_result(label, result)
                if branch:
                    status = "[green]OK[/green]" if result.success else "[red]FAIL[/red]"
                    console.print(f"    [dim]branch: {branch}[/dim]")

    run_context = _format_run_context(validated, validated_ideas, dry_run, execution_results)
    with console.status("[bold green]Updating working memory..."):
        update_working(resolved, config.model, run_context)
    console.print("[dim]Working memory updated[/dim]")


@app.command()
def watch(
    repo: Annotated[Path, typer.Option("--repo", "-r", help="Path to repository")] = Path("."),
    interval: Annotated[
        str, typer.Option("--interval", "-i", help="Cron expression or interval")
    ] = "0 2 * * *",
) -> None:
    """Run Sigil on a schedule (for local use; use GitHub Action for CI)."""
    console.print(
        f"[yellow]Watch mode not yet implemented. Use GitHub Action for scheduled runs.[/yellow]"
    )
    console.print(f"Interval: {interval}")


def _print_finding(f: Finding) -> None:
    loc = f.file
    if f.line:
        loc = f"{f.file}:{f.line}"
    console.print(
        f"  #{f.priority} [{f.disposition}] {f.category} | {loc} | risk: {f.risk}\n"
        f"    {f.description}\n"
        f"    Fix: {f.suggested_fix}\n"
        f"    [dim]{f.rationale}[/dim]"
    )


def _print_idea(idea: FeatureIdea) -> None:
    console.print(
        f"  #{idea.priority} [{idea.disposition}] {idea.title} ({idea.complexity})\n"
        f"    {idea.description[:200]}\n"
        f"    [dim]{idea.rationale[:200]}[/dim]"
    )


def _print_execution_result(label: str, result: ExecutionResult) -> None:
    if result.success:
        console.print(
            f"  [green]OK[/green] {label} "
            f"[dim](retries: {result.retries}, +{len(result.diff.splitlines())} lines)[/dim]"
        )
    else:
        console.print(
            f"  [red]FAIL[/red] {label} — {result.failure_reason} "
            f"[dim](retries: {result.retries})[/dim]"
        )


def _format_run_context(
    findings: list[Finding],
    ideas: list[FeatureIdea],
    dry_run: bool,
    execution_results: list[tuple[str, ExecutionResult]] | None = None,
) -> str:
    lines = []

    if findings:
        lines.append(f"Sigil found {len(findings)} validated finding(s):")
        for f in findings:
            lines.append(
                f"- #{f.priority} [{f.disposition}] {f.category}: {f.description} ({f.file})"
            )

    if ideas:
        lines.append(f"\nSigil proposed {len(ideas)} validated idea(s):")
        for idea in ideas:
            lines.append(
                f"- #{idea.priority} [{idea.disposition}] {idea.title} ({idea.complexity})"
            )

    if not findings and not ideas:
        return "Sigil analyzed the repo and found no findings or ideas."

    if dry_run:
        lines.append("\nDry run — no PRs or issues were created.")
    elif execution_results:
        succeeded = sum(1 for _, r in execution_results if r.success)
        failed = len(execution_results) - succeeded
        lines.append(f"\nExecution: {succeeded} succeeded, {failed} failed.")
        for label, r in execution_results:
            status = "OK" if r.success else f"FAIL ({r.failure_reason})"
            lines.append(f"- [{status}] {label} (retries: {r.retries})")

    return "\n".join(lines)
