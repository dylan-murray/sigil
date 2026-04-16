import datetime
import logging
from pathlib import Path

from sigil.core.config import Config
from sigil.core.utils import StatusCallback, arun
from sigil.pipeline.models import Finding

logger = logging.getLogger(__name__)

STAGNATION_THRESHOLD_DAYS = 180
MIN_COMPLEXITY = 10
STAGNATION_SCORE_THRESHOLD = 1800  # 180 days * 10 complexity


def _stagnation_score(days: int, complexity: float) -> float:
    return float(days * complexity)


def _compute_complexity(file_path: Path) -> float:
    try:
        import radon.complexity as cc

        content = file_path.read_text(errors="replace")
        blocks = cc.cc_visit(content)
        # Sum complexity of all functions/classes in the file
        return float(sum(b.complexity for b in blocks))
    except ImportError:
        logger.warning("radon not installed, falling back to line-count heuristic")
        try:
            lines = len(file_path.read_text(errors="replace").splitlines())
            return float(lines / 10)
        except OSError:
            return 0.0
    except Exception as e:
        logger.debug("Radon parse error for %s: %s", file_path, e)
        return 0.0


async def _get_file_ages(repo: Path) -> dict[str, int]:
    # Get last modification date for all tracked files
    # %ai is author date ISO 8601
    rc, stdout, _ = await arun(
        ["git", "log", "--format=%ai", "--name-only", "--diff-filter=M"],
        cwd=repo,
        timeout=30,
    )
    if rc != 0:
        return {}

    file_ages: dict[str, int] = {}
    lines = stdout.strip().splitlines()

    # The output of git log --format=%ai --name-only is:
    # Date
    # File1
    # File2
    # ...
    # Date
    # File3

    current_date_str = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Simple check if line is a date (starts with YYYY-MM-DD)
        if len(line) >= 10 and line[4] == "-" and line[7] == "-" and line[0].isdigit():
            current_date_str = line
        else:
            if current_date_str:
                try:
                    last_mod = datetime.datetime.fromisoformat(current_date_str)
                    now = datetime.datetime.now(last_mod.tzinfo)
                    days = (now - last_mod).days
                    # We only care about the oldest modification for the "stagnation" check
                    # but git log gives us the most recent first.
                    if line not in file_ages:
                        file_ages[line] = days
                except ValueError:
                    pass

    return file_ages


async def detect_stagnation(
    repo: Path,
    config: Config,
    *,
    on_status: StatusCallback | None = None,
) -> list[Finding]:
    if on_status:
        on_status("Detecting code stagnation...")

    ages = await _get_file_ages(repo)
    findings: list[Finding] = []

    for filepath, days in ages.items():
        if not filepath.endswith(".py"):
            continue

        full_path = repo / filepath
        if not full_path.exists():
            continue

        complexity = _compute_complexity(full_path)
        score = _stagnation_score(days, complexity)

        if (
            days >= STAGNATION_THRESHOLD_DAYS
            and complexity >= MIN_COMPLEXITY
            and score >= STAGNATION_SCORE_THRESHOLD
        ):
            findings.append(
                Finding(
                    category="stagnation",
                    file=filepath,
                    line=None,
                    description=f"File hasn't been modified in {days} days but has high complexity ({complexity:.1f}).",
                    risk="medium",
                    suggested_fix="Review the file for potential refactoring to reduce complexity and improve maintainability.",
                    disposition="issue",
                    priority=10,  # Default low priority for stagnation
                    rationale="Old, complex code is a maintenance risk and a prime candidate for refactoring.",
                    boldness=config.boldness,
                )
            )

    return findings


def write_stagnation_report(repo: Path, findings: list[Finding]) -> None:
    report_path = repo / ".sigil/memory/stagnation_report.md"

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "# Stagnation Report",
        f"Generated: {timestamp}",
        "",
        "## Stale and Complex Files",
        "Files that haven't been modified for a long time but have high cyclomatic complexity.",
        "",
        "| File | Age (Days) | Complexity | Score |",
        "| :--- | :--- | :--- | :--- |",
    ]

    if not findings:
        lines.append("| No stagnant files detected | - | - | - |")
    else:
        for f in findings:
            # Extract days and complexity from description
            # "File hasn't been modified in 200 days but has high complexity (15.0)."
            import re

            days_match = re.search(r"modified in (\d+) days", f.description)
            comp_match = re.search(r"complexity \(([\d.]+)\)", f.description)

            days = days_match.group(1) if days_match else "Unknown"
            comp = comp_match.group(1) if comp_match else "Unknown"
            score = _stagnation_score(
                int(days) if days.isdigit() else 0, float(comp) if comp != "Unknown" else 0
            )

            lines.append(f"| {f.file} | {days} | {comp} | {score:.0f} |")

    content = "\n".join(lines)

    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(content)
    except OSError as e:
        logger.error("Failed to write stagnation report: %s", e)
