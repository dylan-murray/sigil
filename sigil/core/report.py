from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from sigil.core.config import SIGIL_DIR, Config
from sigil.core.models import TokenUsage
from sigil.pipeline.maintenance import Finding
from sigil.pipeline.ideation import FeatureIdea

REPORTS_DIR = "reports"


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}m {secs}s"


def _format_cost(cost: float) -> str:
    return f"${cost:.2f}" if cost >= 0.01 else f"${cost:.4f}"


def _item_label(item: Finding | FeatureIdea) -> str:
    if isinstance(item, Finding):
        return f"{item.category} in {item.file}"
    return item.title


def write_run_report(
    repo: Path,
    config: Config,
    findings: list[Finding],
    ideas: list[FeatureIdea],
    parallel_results: list[tuple],
    pr_urls: list[str],
    issue_urls: list[str],
    usage: TokenUsage,
    run_id: str,
    duration_s: float,
) -> Path | None:
    has_findings = bool(findings)
    has_ideas = bool(ideas)
    has_exec = bool(parallel_results)
    has_prs = bool(pr_urls)
    has_issues = bool(issue_urls)
    has_usage = usage.calls > 0
    if not any([has_findings, has_ideas, has_exec, has_prs, has_issues, has_usage]):
        return None

    now = datetime.now(timezone.utc)
    filename = now.strftime("%Y-%m-%d-%H%M%S") + ".md"
    reports_dir = repo / SIGIL_DIR / REPORTS_DIR
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / filename

    lines: list[str] = []
    lines.append("# Sigil Run Report")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|-------|-------|")
    lines.append(f"| Date | {now.strftime('%Y-%m-%d %H:%M:%S UTC')} |")
    lines.append(f"| Model | `{config.model}` |")
    lines.append(f"| Boldness | {config.boldness} |")
    lines.append(f"| Duration | {_format_duration(duration_s)} |")
    lines.append(f"| Total cost | {_format_cost(usage.cost_usd)} |")
    lines.append(f"| Run ID | `{run_id}` |")
    lines.append(f"| Findings | {len(findings)} |")
    lines.append(f"| Ideas | {len(ideas)} |")
    lines.append(f"| PRs opened | {len(pr_urls)} |")
    lines.append(f"| Issues opened | {len(issue_urls)} |")
    lines.append("")

    lines.append("## Findings")
    lines.append("")
    if findings:
        lines.append("| # | Category | File | Risk | Disposition |")
        lines.append("|---|----------|------|------|-------------|")
        for i, f in enumerate(findings, 1):
            lines.append(f"| {i} | {f.category} | {f.file} | {f.risk} | {f.disposition} |")
    else:
        lines.append("_No findings._")
    lines.append("")

    lines.append("## Ideas")
    lines.append("")
    if ideas:
        lines.append("| # | Title | Complexity | Disposition |")
        lines.append("|---|-------|------------|-------------|")
        for i, idea in enumerate(ideas, 1):
            lines.append(f"| {i} | {idea.title} | {idea.complexity} | {idea.disposition} |")
    else:
        lines.append("_No ideas._")
    lines.append("")

    lines.append("## Execution Results")
    lines.append("")
    if parallel_results:
        lines.append("| Item | Success | Retries | Failure Reason |")
        lines.append("|------|---------|---------|----------------|")
        for item, result, branch in parallel_results:
            label = _item_label(item)
            success = "Yes" if result.success else "No"
            failure = result.failure_reason or ""
            lines.append(f"| {label} | {success} | {result.retries} | {failure} |")
    else:
        lines.append("_No items executed._")
    lines.append("")

    lines.append("## PRs Opened")
    lines.append("")
    if pr_urls:
        for url in pr_urls:
            lines.append(f"- {url}")
    else:
        lines.append("_None._")
    lines.append("")

    lines.append("## Issues Opened")
    lines.append("")
    if issue_urls:
        for url in issue_urls:
            lines.append(f"- {url}")
    else:
        lines.append("_None._")
    lines.append("")

    lines.append("## Token Usage")
    lines.append("")
    if usage.by_model:
        lines.append("| Model | Calls | Prompt Tokens | Completion Tokens | Cost |")
        lines.append("|-------|-------|---------------|-------------------|------|")
        for model_name in sorted(usage.by_model):
            m = usage.by_model[model_name]
            lines.append(
                f"| `{model_name}` | {m.calls} | {m.prompt_tokens:,} | "
                f"{m.completion_tokens:,} | {_format_cost(m.cost_usd)} |"
            )
        lines.append(
            f"| **Total** | {usage.calls} | {usage.prompt_tokens:,} | "
            f"{usage.completion_tokens:,} | {_format_cost(usage.cost_usd)} |"
        )
    else:
        lines.append("_No LLM calls recorded._")
    lines.append("")

    report_path.write_text("\n".join(lines) + "\n")
    return report_path


def _find_report(repo: Path, date_prefix: str | None) -> Path | None:
    reports_dir = repo / SIGIL_DIR / REPORTS_DIR
    if not reports_dir.is_dir():
        return None
    md_files = sorted(reports_dir.glob("*.md"))
    if not md_files:
        return None
    if date_prefix is None:
        return md_files[-1]
    for f in md_files:
        if f.name.startswith(date_prefix):
            return f
    return None


def display_report(repo: Path, date_prefix: str | None = None) -> None:
    import typer

    report_path = _find_report(repo, date_prefix)
    if report_path is None:
        desc = f" matching '{date_prefix}'" if date_prefix else ""
        console = Console()
        console.print(f"[bold red]No report found{desc}.[/bold red]")
        raise typer.Exit(1)

    content = report_path.read_text()
    console = Console()

    lines = content.splitlines()
    title = ""
    if lines and lines[0].startswith("# "):
        title = lines[0][2:]

    table = Table(show_lines=True, expand=False)
    table.add_column("Section", style="bold")
    table.add_column("Content")

    current_section = ""
    current_lines: list[str] = []

    def flush() -> None:
        if current_section and current_lines:
            table.add_row(current_section, "\n".join(current_lines).strip())

    for line in lines:
        if line.startswith("## "):
            flush()
            current_section = line[3:].strip()
            current_lines = []
        elif line.startswith("# "):
            continue
        else:
            current_lines.append(line)
    flush()

    if title:
        console.print(Panel(table, title=title, border_style="#a78bfa"))
    else:
        console.print(table)

    console.print(f"\n[dim]Source: {report_path}[/dim]")
