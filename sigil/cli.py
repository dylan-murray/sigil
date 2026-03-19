from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.panel import Panel

from sigil import __version__
from sigil.config import SIGIL_DIR, CONFIG_FILE, Config, DEFAULT_MODEL
from sigil.discovery import discover
from sigil.memory import is_stale, load_project, update_project, update_working

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
            schedule=config.schedule,
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
    stale = is_stale(resolved)

    if stale:
        with console.status("[bold green]Discovering repo..."):
            discovery_context = discover(resolved, config.model)

        console.print("[green]Discovery complete[/green]")

        with console.status("[bold green]Updating project memory..."):
            project_md = update_project(resolved, config.model, discovery_context)

        console.print("[dim]Project memory updated[/dim]")
    else:
        console.print("[dim]Memory is fresh — skipping discovery[/dim]")
        project_md = load_project(resolved)

    console.print(Panel.fit(project_md[:2000], title=".sigil/memory/project.md"))

    run_context = (
        f"Discovery: {'full (stale or first run)' if stale else 'skipped (memory fresh)'}\n"
        f"Model: {config.model}\n"
        f"Boldness: {config.boldness}\n"
        f"Focus: {', '.join(config.focus)}\n"
        f"Dry run: {dry_run}\n"
    )

    with console.status("[bold green]Updating working memory..."):
        update_working(resolved, config.model, run_context)

    console.print("[dim]Working memory updated[/dim]")

    console.print("\n[yellow]Analysis + codegen not yet implemented. Coming soon.[/yellow]")


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
