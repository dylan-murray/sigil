import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.panel import Panel
from rich.table import Table

from sigil.core.utils import read_file


@dataclass
class HealthMetrics:
    open_findings: int = 0
    type_coverage: float = 0.0
    test_coverage: float = 0.0
    dependency_health: int = 0
    pr_success_rate: float = 0.0
    knowledge_staleness: int = 0
    status: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "open_findings": self.open_findings,
            "type_coverage": f"{self.type_coverage:.1%}",
            "test_coverage": f"{self.test_coverage:.1%}",
            "dependency_health": f"{self.dependency_health}/100",
            "pr_success_rate": f"{self.pr_success_rate:.1%}",
            "knowledge_staleness": f"{self.knowledge_staleness} days",
            "status": self.status,
        }


class HealthDashboard:
    def __init__(self, metrics: HealthMetrics):
        self.metrics = metrics

    def render(self) -> str:
        table = Table(show_header=True, header_style="bold magenta", box=None)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")

        table.add_row("Open Findings", str(self.metrics.open_findings))
        table.add_row("Type Coverage", f"{self.metrics.type_coverage:.1%}")
        table.add_row("Test Coverage", f"{self.metrics.test_coverage:.1%}")
        table.add_row("Dependency Health", f"{self.metrics.dependency_health}/100")
        table.add_row("PR Success Rate", f"{self.metrics.pr_success_rate:.1%}")
        table.add_row("Knowledge Staleness", f"{self.metrics.knowledge_staleness} days")

        status_color = (
            "green"
            if self.metrics.status == "healthy"
            else "yellow"
            if self.metrics.status == "warning"
            else "red"
        )
        status_text = f"[{status_color}] {self.metrics.status.upper()} [/]"

        return Panel(
            Table.grid([table, f"\nOverall Status: {status_text}"]),
            title="[bold #a78bfa]⟡ Codebase Health Dashboard[/]",
            border_style="#a78bfa",
            expand=False,
        )

    def export_json(self) -> str:
        return json.dumps(self.metrics.to_dict(), indent=2)

    def export_csv(self) -> str:
        data = self.metrics.to_dict()
        output = []
        for k, v in data.items():
            output.append(f"{k},{v}")
        return "\n".join(output)


def compute_health(repo: Path) -> HealthMetrics:
    metrics = HealthMetrics()

    # 1. Open Findings
    # Scan .sigil/memory/ for findings marked unreviewed or issue
    memory_dir = repo / ".sigil" / "memory"
    if memory_dir.exists():
        findings_count = 0
        for f in memory_dir.glob("*.md"):
            content = read_file(f)
            # Simple heuristic: count lines that look like findings with specific dispositions
            # In a real scenario, we'd parse the structured data if available
            findings_count += len(re.findall(r"disposition:\s*(unreviewed|issue)", content, re.I))
        metrics.open_findings = findings_count

    # 2. Type Coverage
    # % of .py files containing type hints (e.g., '->' or ': int')
    py_files = list(repo.rglob("*.py"))
    if py_files:
        typed_files = 0
        for pf in py_files:
            if ".sigil" in pf.as_posix():
                continue
            content = read_file(pf)
            if "->" in content or re.search(
                r":\s*(int|str|float|bool|list|dict|set|tuple|Any|Optional|Union)", content
            ):
                typed_files += 1
        metrics.type_coverage = (
            typed_files / len([f for f in py_files if ".sigil" not in f.as_posix()])
            if py_files
            else 0.0
        )

    # 3. Test Coverage (Estimated)
    # % of source files that have a corresponding test file in tests/
    src_files = [
        f for f in py_files if "tests" not in f.as_posix() and ".sigil" not in f.as_posix()
    ]
    if src_files:
        covered_files = 0
        for sf in src_files:
            rel_path = sf.relative_to(repo).as_posix()
            test_path = Path("tests") / rel_path.replace("sigil/", "test_sigil/").replace(
                ".py", "_test.py"
            )
            if (repo / test_path).exists() or (
                repo / Path("tests") / f"test_{sf.stem}.py"
            ).exists():
                covered_files += 1
        metrics.test_coverage = covered_files / len(src_files)

    # 4. Dependency Health
    # Score 0-100 based on .sigil/dependencies/
    deps_dir = repo / ".sigil" / "dependencies"
    if deps_dir.exists():
        # Heuristic: subtract points for "outdated" or "vulnerable" keywords in snapshots
        score = 100
        for df in deps_dir.glob("*.json"):
            content = read_file(df)
            score -= content.count("outdated") * 2
            score -= content.count("vulnerable") * 10
        metrics.dependency_health = max(0, score)
    else:
        metrics.dependency_health = 0

    # 5. PR Success Rate
    # % of merged vs failed/closed in .sigil/outcomes/
    outcomes_dir = repo / ".sigil" / "outcomes"
    if outcomes_dir.exists():
        outcomes = list(outcomes_dir.glob("*.json"))
        if outcomes:
            merged = 0
            for oo in outcomes:
                if "merged" in read_file(oo).lower():
                    merged += 1
            metrics.pr_success_rate = merged / len(outcomes)

    # 6. Knowledge Staleness
    # Days since last update in .sigil/memory/
    if memory_dir.exists():
        mtimes = [f.stat().st_mtime for f in memory_dir.glob("*") if f.is_file()]
        if mtimes:
            last_update = max(mtimes)
            delta = datetime.now().timestamp() - last_update
            metrics.knowledge_staleness = int(delta / 86400)

    # Determine overall status
    if metrics.open_findings > 10 or metrics.dependency_health < 50:
        metrics.status = "warning"
    elif metrics.open_findings > 0 or metrics.test_coverage < 0.7:
        metrics.status = "warning"
    else:
        metrics.status = "healthy"

    return metrics
