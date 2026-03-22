import asyncio
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel

from sigil import __version__
from sigil.agent_config import detect_agent_config
from sigil.config import CONFIG_FILE, SIGIL_DIR, Config
from sigil.discovery import discover
from sigil.executor import ExecutionResult, execute_parallel
from sigil.github import (
    cleanup_after_push,
    create_client,
    dedup_items,
    ensure_labels,
    publish_results,
)
from sigil.ideation import FeatureIdea, ideate, save_ideas
from sigil.knowledge import compact_knowledge, is_knowledge_stale, load_index
from sigil.maintenance import Finding, analyze
from sigil.memory import update_working
from sigil.validation import validate_all

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
        bool | None,
        typer.Option("--version", "-v", callback=version_callback, is_eager=True),
    ] = None,
) -> None:
    pass


@app.command()
def run(
    repo: Annotated[Path, typer.Option("--repo", "-r", help="Path to repository")] = Path("."),
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Analyze only, don't open PRs or issues")
    ] = False,
    model: Annotated[
        str | None, typer.Option("--model", "-m", help="Override model from config")
    ] = None,
) -> None:
    """Run Sigil: analyze the repo, find improvements, and open PRs."""
    asyncio.run(_run(repo, dry_run, model))


async def _run(repo: Path, dry_run: bool, model: str | None) -> None:
    config_path = repo / SIGIL_DIR / CONFIG_FILE
    first_run = not config_path.exists()
    if first_run:
        sigil_dir = repo / SIGIL_DIR
        sigil_dir.mkdir(parents=True, exist_ok=True)
        config_path.write_text(Config().to_yaml())

    config = Config.load(repo)
    if model:
        config = config.with_model(model)

    if first_run:
        console.print(
            Panel.fit(
                f"[green]Sigil initialized![/green]\n\n"
                f"Config:   {config_path}\n"
                f"Model:    {config.model}\n"
                f"Boldness: {config.boldness}\n"
                f"Focus:    {', '.join(config.focus)}",
                title="sigil",
            )
        )
    else:
        console.print(
            Panel.fit(
                f"Model:    {config.model}\n"
                f"Boldness: {config.boldness}\n"
                f"Focus:    {', '.join(config.focus)}\n"
                f"Dry run:  {dry_run}",
                title="sigil run",
            )
        )

    resolved = repo.resolve()

    gh_client = None
    if not dry_run:
        gh_client = await create_client(resolved)
        if gh_client:
            await ensure_labels(gh_client)
            console.print("[dim]GitHub client connected[/dim]")
        else:
            console.print(
                "[bold red]Error: GitHub credentials required for live runs. Set GITHUB_TOKEN or use --dry-run.[/bold red]"
            )
            raise typer.Exit(1)

    if await is_knowledge_stale(resolved):
        with console.status("[bold green]Discovering repo..."):
            discovery_context = await discover(resolved, config.model)

        console.print("[green]Discovery complete[/green]")

        with console.status("[bold green]Compacting knowledge..."):
            compact_model = config.knowledge_model or config.model
            await compact_knowledge(resolved, compact_model, discovery_context)

        console.print("[dim]Knowledge updated[/dim]")
    else:
        console.print("[dim]Knowledge is fresh — skipping discovery[/dim]")

    index_md = load_index(resolved)
    if index_md:
        console.print(Panel.fit(index_md[:2000], title=".sigil/memory/INDEX.md"))

    agent_config = detect_agent_config(resolved)
    if agent_config.has_config:
        console.print(
            f"[dim]Agent config: {', '.join(agent_config.detected_files)} ({agent_config.source})[/dim]"
        )

    with console.status("[bold green]Analyzing + ideating in parallel..."):
        findings, ideas = await asyncio.gather(
            analyze(resolved, config, agent_config=agent_config),
            ideate(resolved, config, agent_config=agent_config),
        )

    if not findings and not ideas:
        console.print("[green]No findings or ideas.[/green]")
        return

    if findings:
        console.print(f"[dim]Found {len(findings)} finding(s)[/dim]")
    if ideas:
        console.print(f"[dim]Proposed {len(ideas)} idea(s)[/dim]")

    console.print(f"[dim]Validating {len(findings) + len(ideas)} candidate(s)...[/dim]")
    with console.status("[bold green]Validating all candidates..."):
        result = await validate_all(resolved, config, findings, ideas)
    validated = result.findings
    validated_ideas = result.ideas

    pr_items = [f for f in validated if f.disposition == "pr"]
    issue_items = [f for f in validated if f.disposition == "issue"]
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

    vetoed_findings = len(findings) - len(validated)
    if vetoed_findings:
        console.print(f"[dim]Vetoed: {vetoed_findings} finding(s)[/dim]")

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

    if len(validated_ideas) < len(ideas):
        console.print(f"[dim]Ideas vetoed: {len(ideas) - len(validated_ideas)}[/dim]")

    execution_results: list[tuple[str, ExecutionResult]] = []
    parallel_results: list[tuple] = []

    all_pr_items = pr_items + idea_prs
    all_issue_items = issue_items + idea_issues

    if gh_client and not dry_run:
        pr_dedup = await dedup_items(gh_client, all_pr_items)
        issue_dedup = await dedup_items(gh_client, all_issue_items)
        if pr_dedup.skipped:
            console.print(f"[dim]Dedup: skipped {len(pr_dedup.skipped)} PR item(s)[/dim]")
        if issue_dedup.skipped:
            console.print(f"[dim]Dedup: skipped {len(issue_dedup.skipped)} issue item(s)[/dim]")
        all_pr_items = pr_dedup.remaining
        all_issue_items = issue_dedup.remaining

    if not dry_run:
        overflow = all_pr_items[config.max_prs_per_run :]
        all_pr_items = all_pr_items[: config.max_prs_per_run]
        if overflow:
            all_issue_items.extend(overflow)
            console.print(
                f"[dim]Capped PRs to {config.max_prs_per_run}, "
                f"moved {len(overflow)} item(s) to issues[/dim]"
            )

        if all_pr_items:
            console.print(
                f"\n[bold green]Executing {len(all_pr_items)} item(s) "
                f"(max {config.max_parallel_agents} parallel)...[/bold green]"
            )
            with console.status("[bold green]Executing in worktrees..."):
                parallel_results = await execute_parallel(
                    resolved, config, all_pr_items, agent_config=agent_config
                )
            for item, result, branch in parallel_results:
                label = item.description[:60] if isinstance(item, Finding) else item.title[:60]
                execution_results.append((label, result))
                _print_execution_result(label, result)
                if branch:
                    console.print(f"    [dim]branch: {branch}[/dim]")
                if result.downgraded:
                    all_issue_items.append(item)
                    console.print(
                        f"    [yellow]Downgraded to issue[/yellow] — {result.failure_reason}"
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

        with console.status("[bold green]Publishing to GitHub..."):
            pr_urls, issue_urls, pushed_branches = await publish_results(
                resolved,
                config,
                gh_client,
                parallel_results,
                issue_tuples,
                agent_config=agent_config,
            )

        if pr_urls:
            console.print(f"\n[bold green]Opened {len(pr_urls)} PR(s):[/bold green]")
            for url in pr_urls:
                console.print(f"  {url}")
        if issue_urls:
            console.print(f"\n[bold yellow]Opened {len(issue_urls)} issue(s):[/bold yellow]")
            for url in issue_urls:
                console.print(f"  {url}")

        await cleanup_after_push(resolved, parallel_results, pushed_branches)

    run_context = _format_run_context(
        validated, validated_ideas, dry_run, execution_results, pr_urls, issue_urls
    )
    with console.status("[bold green]Updating working memory..."):
        await update_working(resolved, config.model, run_context)
    console.print("[dim]Working memory updated[/dim]")


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
    pr_urls: list[str] | None = None,
    issue_urls: list[str] | None = None,
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
        downgraded = sum(1 for _, r in execution_results if r.downgraded)
        failed = len(execution_results) - succeeded
        lines.append(
            f"\nExecution: {succeeded} succeeded, {failed} failed, {downgraded} downgraded to issues."
        )
        for label, r in execution_results:
            if r.downgraded:
                lines.append(f"- [DOWNGRADED] {label}: {r.downgrade_context.splitlines()[0]}")
            elif r.success:
                lines.append(f"- [OK] {label} (retries: {r.retries})")
            else:
                lines.append(f"- [FAIL] {label} ({r.failure_reason})")

    if pr_urls:
        lines.append(f"\nPRs opened ({len(pr_urls)}):")
        for url in pr_urls:
            lines.append(f"- {url}")

    if issue_urls:
        lines.append(f"\nIssues opened ({len(issue_urls)}):")
        for url in issue_urls:
            lines.append(f"- {url}")

    return "\n".join(lines)
