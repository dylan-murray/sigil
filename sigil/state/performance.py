import hashlib
import json
import logging
import statistics
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from rich.table import Table

from sigil.core.config import SIGIL_DIR
from sigil.core.llm import get_usage_snapshot

logger = logging.getLogger(__name__)

PERF_FILE = "performance.jsonl"
BASELINE_FILE = "performance-baseline.md"
MAX_PERF_RUNS = 500


@dataclass(frozen=True)
class StagePerf:
    stage: str
    duration_s: float
    tokens: int
    llm_calls: int


@dataclass(frozen=True)
class RunPerf:
    run_id: str
    timestamp: str
    config_hash: str
    stages: list[StagePerf] = field(default_factory=list)


@dataclass(frozen=True)
class PerfBaseline:
    stage: str
    median_duration_s: float
    median_tokens: float
    median_calls: float


@dataclass(frozen=True)
class Deviation:
    stage: str
    metric: str
    current: float
    baseline: float
    ratio: float
    severity: str


def config_hash(config: object) -> str:
    cfg: dict = {}
    for attr in ("model", "boldness", "focus", "agents"):
        val = getattr(config, attr, None)
        if val is None:
            continue
        if attr == "focus":
            val = sorted(val)
        elif attr == "agents":
            val = dict(sorted(val.items())) if isinstance(val, dict) else val
        cfg[attr] = val
    payload = json.dumps(cfg, sort_keys=True, default=str)
    return hashlib.md5(payload.encode()).hexdigest()


def _perf_path(repo: Path) -> Path:
    return repo / SIGIL_DIR / PERF_FILE


def log_perf_run(repo: Path, run_perf: RunPerf) -> None:
    path = _perf_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(asdict(run_perf)) + "\n")


def read_perf_runs(repo: Path, cfg_hash: str, limit: int = 5) -> list[RunPerf]:
    path = _perf_path(repo)
    if not path.exists():
        return []
    runs: list[RunPerf] = []
    for line in reversed(path.read_text().splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            if data.get("config_hash") != cfg_hash:
                continue
            stages = [StagePerf(**s) for s in data.get("stages", [])]
            runs.append(RunPerf(**{k: v for k, v in data.items() if k != "stages"}, stages=stages))
            if len(runs) >= limit:
                break
        except (json.JSONDecodeError, TypeError):
            continue
    runs.reverse()
    return runs


def prune_perf_runs(repo: Path) -> int:
    path = _perf_path(repo)
    if not path.exists():
        return 0
    lines = path.read_text().splitlines()
    if len(lines) <= MAX_PERF_RUNS:
        return 0
    pruned = len(lines) - MAX_PERF_RUNS
    path.write_text("\n".join(lines[pruned:]) + "\n")
    return pruned


def compute_baselines(runs: list[RunPerf]) -> dict[str, PerfBaseline]:
    if not runs:
        return {}
    stage_data: dict[str, dict[str, list[float]]] = {}
    for run in runs:
        for sp in run.stages:
            entry = stage_data.setdefault(sp.stage, {"duration_s": [], "tokens": [], "calls": []})
            entry["duration_s"].append(sp.duration_s)
            entry["tokens"].append(sp.tokens)
            entry["calls"].append(sp.llm_calls)
    baselines: dict[str, PerfBaseline] = {}
    for stage, data in stage_data.items():
        baselines[stage] = PerfBaseline(
            stage=stage,
            median_duration_s=statistics.median(data["duration_s"]) if data["duration_s"] else 0.0,
            median_tokens=statistics.median(data["tokens"]) if data["tokens"] else 0.0,
            median_calls=statistics.median(data["calls"]) if data["calls"] else 0.0,
        )
    return baselines


def check_deviations(run_perf: RunPerf, baselines: dict[str, PerfBaseline]) -> list[Deviation]:
    deviations: list[Deviation] = []
    for sp in run_perf.stages:
        bl = baselines.get(sp.stage)
        if not bl:
            continue
        if bl.median_duration_s > 0 and sp.duration_s / bl.median_duration_s >= 5.0:
            deviations.append(
                Deviation(
                    stage=sp.stage,
                    metric="duration_s",
                    current=sp.duration_s,
                    baseline=bl.median_duration_s,
                    ratio=sp.duration_s / bl.median_duration_s,
                    severity="issue",
                )
            )
        elif bl.median_duration_s > 0 and sp.duration_s / bl.median_duration_s >= 2.0:
            deviations.append(
                Deviation(
                    stage=sp.stage,
                    metric="duration_s",
                    current=sp.duration_s,
                    baseline=bl.median_duration_s,
                    ratio=sp.duration_s / bl.median_duration_s,
                    severity="warning",
                )
            )
        if bl.median_tokens > 0 and sp.tokens / bl.median_tokens >= 1.5:
            deviations.append(
                Deviation(
                    stage=sp.stage,
                    metric="tokens",
                    current=float(sp.tokens),
                    baseline=bl.median_tokens,
                    ratio=sp.tokens / bl.median_tokens,
                    severity="warning",
                )
            )
        if bl.median_calls > 0 and sp.llm_calls / bl.median_calls >= 2.0:
            deviations.append(
                Deviation(
                    stage=sp.stage,
                    metric="llm_calls",
                    current=float(sp.llm_calls),
                    baseline=bl.median_calls,
                    ratio=sp.llm_calls / bl.median_calls,
                    severity="warning",
                )
            )
    return deviations


def format_perf_table(
    run_perf: RunPerf,
    baselines: dict[str, PerfBaseline],
    deviations: list[Deviation],
) -> Table:
    dev_map: dict[str, list[Deviation]] = {}
    for d in deviations:
        dev_map.setdefault(d.stage, []).append(d)

    table = Table(title="Performance Summary", show_header=True, header_style="bold")
    table.add_column("Stage", style="cyan")
    table.add_column("Time", justify="right")
    table.add_column("vs Baseline", justify="right")
    table.add_column("Tokens", justify="right")
    table.add_column("vs Baseline", justify="right")
    table.add_column("LLM Calls", justify="right")
    table.add_column("vs Baseline", justify="right")

    for sp in run_perf.stages:
        bl = baselines.get(sp.stage)
        time_str = f"{sp.duration_s:.1f}s"
        tok_str = f"{sp.tokens:,}"
        calls_str = str(sp.llm_calls)

        if bl:
            time_ratio = sp.duration_s / bl.median_duration_s if bl.median_duration_s > 0 else 0
            tok_ratio = sp.tokens / bl.median_tokens if bl.median_tokens > 0 else 0
            calls_ratio = sp.llm_calls / bl.median_calls if bl.median_calls > 0 else 0

            time_vs = f"{time_ratio:.1f}x"
            tok_vs = f"{tok_ratio:.1f}x"
            calls_vs = f"{calls_ratio:.1f}x"

            stage_devs = dev_map.get(sp.stage, [])
            if any(d.severity == "issue" for d in stage_devs):
                time_vs = f"[bold red]{time_vs}[/bold red]"
            elif any(d.severity == "warning" for d in stage_devs):
                time_vs = f"[yellow]{time_vs}[/yellow]"
        else:
            time_vs = "—"
            tok_vs = "—"
            calls_vs = "—"

        table.add_row(sp.stage, time_str, time_vs, tok_str, tok_vs, calls_str, calls_vs)

    return table


def write_baseline_markdown(repo: Path, baselines: dict[str, PerfBaseline]) -> None:
    from sigil.state.memory import _write_frontmatter

    lines = ["# Performance Baselines", ""]
    if not baselines:
        lines.append("No baseline data available yet.")
    else:
        lines.append("| Stage | Median Time | Median Tokens | Median Calls |")
        lines.append("|-------|-------------|---------------|---------------|")
        for stage in sorted(baselines):
            bl = baselines[stage]
            lines.append(
                f"| {stage} | {bl.median_duration_s:.1f}s | {int(bl.median_tokens):,} | {int(bl.median_calls)} |"
            )
    lines.append("")
    body = "\n".join(lines)
    meta = {"type": "performance-baseline"}
    content = _write_frontmatter(meta, body)
    mem_dir = repo / SIGIL_DIR / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    (mem_dir / BASELINE_FILE).write_text(content)


class PerfTracker:
    def __init__(self) -> None:
        self._stages: dict[str, dict] = {}
        self._completed: list[StagePerf] = []

    def start_stage(self, name: str) -> None:
        calls, total_tokens, _ = get_usage_snapshot()
        self._stages[name] = {
            "start_time": time.monotonic(),
            "start_calls": calls,
            "start_tokens": total_tokens,
        }

    def finish_stage(self, name: str) -> None:
        info = self._stages.pop(name, None)
        if info is None:
            return
        calls, total_tokens, _ = get_usage_snapshot()
        duration = time.monotonic() - info["start_time"]
        token_delta = max(0, total_tokens - info["start_tokens"])
        call_delta = max(0, calls - info["start_calls"])
        self._completed.append(
            StagePerf(
                stage=name, duration_s=round(duration, 2), tokens=token_delta, llm_calls=call_delta
            )
        )

    def build_run_perf(self, run_id: str, cfg_hash: str, timestamp: str) -> RunPerf:
        return RunPerf(
            run_id=run_id, timestamp=timestamp, config_hash=cfg_hash, stages=list(self._completed)
        )
