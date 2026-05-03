import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

SIGIL_DIR = ".sigil"
ANALYTICS_FILE = "tool-analytics.json"

_SUCCESS_OUTCOMES = frozenset({"success", "stopped"})
_FAILURE_OUTCOMES = frozenset({"doom_loop", "timeout"})


@dataclass(frozen=True)
class ToolStats:
    total_calls: int = 0
    runs_used: int = 0
    success_runs: int = 0
    failure_runs: int = 0


@dataclass(frozen=True)
class AgentRunRecord:
    agent_label: str
    tool_calls: dict[str, int] = field(default_factory=dict)
    outcome: str = ""
    defined_tools: frozenset[str] = frozenset()


@dataclass(frozen=True)
class RunAnalytics:
    records: list[AgentRunRecord] = field(default_factory=list)


@dataclass(frozen=True)
class AggregatedAnalytics:
    total_runs: int = 0
    all_defined_tools: frozenset[str] = frozenset()
    by_tool: dict[str, ToolStats] = field(default_factory=dict)


_analytics_enabled: bool = True
_current_agent_label: str | None = None
_current_tool_calls: dict[str, int] = {}
_current_defined_tools: frozenset[str] = frozenset()
_current_run: list[AgentRunRecord] = []


def set_analytics_enabled(enabled: bool) -> None:
    global _analytics_enabled
    _analytics_enabled = enabled


def reset_tool_analytics() -> None:
    global _current_run, _current_agent_label, _current_tool_calls, _current_defined_tools
    _current_run = []
    _current_agent_label = None
    _current_tool_calls = {}
    _current_defined_tools = frozenset()


def begin_agent_run(agent_label: str, defined_tools: frozenset[str]) -> None:
    global _current_agent_label, _current_tool_calls, _current_defined_tools
    if not _analytics_enabled:
        return
    _current_agent_label = agent_label
    _current_tool_calls = {}
    _current_defined_tools = defined_tools


def record_tool_call_analytics(tool_name: str) -> None:
    if not _analytics_enabled:
        return
    _current_tool_calls[tool_name] = _current_tool_calls.get(tool_name, 0) + 1


def record_agent_outcome(agent_label: str, outcome: str, defined_tools: frozenset[str]) -> None:
    global _current_agent_label, _current_tool_calls, _current_defined_tools
    if not _analytics_enabled:
        return
    record = AgentRunRecord(
        agent_label=agent_label,
        tool_calls=dict(_current_tool_calls),
        outcome=outcome,
        defined_tools=defined_tools,
    )
    _current_run.append(record)
    _current_agent_label = None
    _current_tool_calls = {}
    _current_defined_tools = frozenset()


def get_run_analytics() -> RunAnalytics | None:
    if not _analytics_enabled:
        return None
    return RunAnalytics(records=list(_current_run))


def _aggregate(
    records: list[AgentRunRecord], existing: AggregatedAnalytics | None
) -> AggregatedAnalytics:
    if existing is None:
        existing = AggregatedAnalytics()
    all_tools = set(existing.all_defined_tools)
    by_tool: dict[str, ToolStats] = dict(existing.by_tool)
    total_runs = existing.total_runs

    for record in records:
        total_runs += 1
        all_tools.update(record.defined_tools)
        is_success = record.outcome in _SUCCESS_OUTCOMES
        is_failure = record.outcome in _FAILURE_OUTCOMES

        for tool_name, count in record.tool_calls.items():
            existing_stats = by_tool.get(tool_name, ToolStats())
            by_tool[tool_name] = ToolStats(
                total_calls=existing_stats.total_calls + count,
                runs_used=existing_stats.runs_used + 1,
                success_runs=existing_stats.success_runs + (1 if is_success else 0),
                failure_runs=existing_stats.failure_runs + (1 if is_failure else 0),
            )

        for tool_name in record.defined_tools:
            if tool_name not in by_tool:
                by_tool[tool_name] = ToolStats()

    return AggregatedAnalytics(
        total_runs=total_runs,
        all_defined_tools=frozenset(all_tools),
        by_tool=by_tool,
    )


def persist_analytics(repo: Path) -> None:
    if not _analytics_enabled:
        return
    run_data = get_run_analytics()
    if run_data is None or not run_data.records:
        return
    existing = load_analytics(repo)
    aggregated = _aggregate(run_data.records, existing)
    _write_analytics(repo, aggregated)


def _write_analytics(repo: Path, data: AggregatedAnalytics) -> None:
    analytics_path = repo / SIGIL_DIR / "memory" / ANALYTICS_FILE
    try:
        analytics_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.warning("Failed to create analytics directory")
        return
    payload = {
        "total_runs": data.total_runs,
        "all_defined_tools": sorted(data.all_defined_tools),
        "by_tool": {
            name: {
                "total_calls": stats.total_calls,
                "runs_used": stats.runs_used,
                "success_runs": stats.success_runs,
                "failure_runs": stats.failure_runs,
            }
            for name, stats in data.by_tool.items()
        },
    }
    try:
        analytics_path.write_text(json.dumps(payload, indent=2) + "\n")
    except OSError:
        logger.warning("Failed to write analytics file")


def load_analytics(repo: Path) -> AggregatedAnalytics | None:
    analytics_path = repo / SIGIL_DIR / "memory" / ANALYTICS_FILE
    if not analytics_path.exists():
        return None
    try:
        raw = json.loads(analytics_path.read_text())
    except (json.JSONDecodeError, OSError):
        logger.warning("Failed to read analytics file")
        return None
    if not isinstance(raw, dict):
        return None
    total_runs = raw.get("total_runs", 0)
    all_defined = frozenset(raw.get("all_defined_tools", []))
    by_tool_raw = raw.get("by_tool", {})
    by_tool: dict[str, ToolStats] = {}
    if isinstance(by_tool_raw, dict):
        for name, stats in by_tool_raw.items():
            if isinstance(stats, dict):
                by_tool[name] = ToolStats(
                    total_calls=stats.get("total_calls", 0),
                    runs_used=stats.get("runs_used", 0),
                    success_runs=stats.get("success_runs", 0),
                    failure_runs=stats.get("failure_runs", 0),
                )
    return AggregatedAnalytics(
        total_runs=total_runs,
        all_defined_tools=all_defined,
        by_tool=by_tool,
    )


def format_analytics_report(data: AggregatedAnalytics) -> str:
    if not data.by_tool and not data.all_defined_tools:
        return "No tool usage data available."

    lines: list[str] = []

    sorted_by_calls = sorted(
        data.by_tool.items(), key=lambda x: x[1].total_calls, reverse=True
    )
    used_tools = {name for name, stats in data.by_tool.items() if stats.runs_used > 0}
    never_used = data.all_defined_tools - used_tools

    if sorted_by_calls:
        lines.append("Most used tools:")
        for name, stats in sorted_by_calls[:5]:
            lines.append(f"  {name}: {stats.total_calls} calls across {stats.runs_used} runs")

    if sorted_by_calls:
        least = list(reversed(sorted_by_calls[-5:])) if len(sorted_by_calls) >= 5 else list(reversed(sorted_by_calls))
        lines.append("")
        lines.append("Least used tools:")
        for name, stats in least:
            lines.append(f"  {name}: {stats.total_calls} calls across {stats.runs_used} runs")

    success_correlated: list[tuple[str, ToolStats]] = []
    failure_correlated: list[tuple[str, ToolStats]] = []
    for name, stats in data.by_tool.items():
        if stats.runs_used == 0:
            continue
        if stats.success_runs > stats.failure_runs:
            success_correlated.append((name, stats))
        elif stats.failure_runs > stats.success_runs:
            failure_correlated.append((name, stats))

    if success_correlated:
        success_correlated.sort(key=lambda x: x[1].success_runs, reverse=True)
        lines.append("")
        lines.append("Success-correlated tools:")
        for name, stats in success_correlated[:5]:
            lines.append(
                f"  {name}: {stats.success_runs} success / {stats.failure_runs} failure runs"
            )

    if failure_correlated:
        failure_correlated.sort(key=lambda x: x[1].failure_runs, reverse=True)
        lines.append("")
        lines.append("Failure-correlated tools:")
        for name, stats in failure_correlated[:5]:
            lines.append(
                f"  {name}: {stats.success_runs} success / {stats.failure_runs} failure runs"
            )

    if never_used:
        lines.append("")
        lines.append("Defined but never used:")
        for name in sorted(never_used):
            lines.append(f"  {name}")

    lines.append("")
    lines.append(f"Total runs: {data.total_runs}")

    return "\n".join(lines)