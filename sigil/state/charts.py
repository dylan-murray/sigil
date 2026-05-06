from sigil.state.metrics import RunMetrics

BLOCK_CHARS = "▁▂▃▄▅▆▇█"
BAR_FULL = "█"
BAR_EMPTY = "░"
BAR_HALF = "▓"


def _sparkline(values: list[float]) -> str:
    if not values:
        return ""
    max_val = max(values) if max(values) > 0 else 1
    result = []
    for v in values:
        idx = int(v / max_val * (len(BLOCK_CHARS) - 1))
        result.append(BLOCK_CHARS[idx])
    return "".join(result)


def _bar(value: float, max_val: float, width: int = 30) -> str:
    if max_val <= 0:
        max_val = 1
    filled = int(value / max_val * width)
    filled = min(filled, width)
    return BAR_FULL * filled + BAR_EMPTY * (width - filled)


def _pct_bar(pct: float, width: int = 30) -> str:
    filled = int(pct / 100 * width)
    filled = min(filled, width)
    return BAR_FULL * filled + BAR_EMPTY * (width - filled)


def _format_timestamp(ts: str) -> str:
    try:
        return ts[:19].replace("T", " ")
    except (IndexError, TypeError):
        return str(ts)


def _render_finding_count(runs: list[RunMetrics]) -> list[str]:
    lines = ["── Finding Count ──"]
    if not runs:
        lines.append("  (no data)")
        return lines
    counts = [r.total_findings for r in runs]
    spark = _sparkline(counts)
    lines.append(f"  {spark}")
    for r in runs:
        lines.append(f"  {_format_timestamp(r.timestamp)}  {r.total_findings:>4} findings")
    return lines


def _render_category_distribution(runs: list[RunMetrics]) -> list[str]:
    lines = ["── Category Distribution ──"]
    if not runs:
        lines.append("  (no data)")
        return lines
    all_categories: set[str] = set()
    for r in runs:
        all_categories.update(r.findings_by_category.keys())
    if not all_categories:
        lines.append("  (no findings)")
        return lines
    categories = sorted(all_categories)
    max_total = max(sum(r.findings_by_category.values()) for r in runs) or 1
    bar_width = 30
    for r in runs:
        parts = []
        for cat in categories:
            count = r.findings_by_category.get(cat, 0)
            if count > 0:
                filled = int(count / max_total * bar_width)
                filled = max(filled, 1)
                parts.append(BAR_FULL * filled)
        bar = "".join(parts) if parts else BAR_EMPTY * bar_width
        ts = _format_timestamp(r.timestamp)
        lines.append(f"  {ts}  {bar}")
    legend = "  ".join(f"{BAR_FULL} {cat}" for cat in categories)
    lines.append(f"  {legend}")
    return lines


def _render_execution_rate(runs: list[RunMetrics]) -> list[str]:
    lines = ["── Execution Success Rate ──"]
    if not runs:
        lines.append("  (no data)")
        return lines
    for r in runs:
        if r.execution_total_count > 0:
            pct = r.execution_success_count / r.execution_total_count * 100
        else:
            pct = 0.0
        bar = _pct_bar(pct)
        ts = _format_timestamp(r.timestamp)
        lines.append(
            f"  {ts}  {bar} {pct:.0f}% ({r.execution_success_count}/{r.execution_total_count})"
        )
    return lines


def _render_token_consumption(runs: list[RunMetrics]) -> list[str]:
    lines = ["── Token Consumption ──"]
    if not runs:
        lines.append("  (no data)")
        return lines
    max_tokens = max(r.tokens_consumed for r in runs) or 1
    for r in runs:
        bar = _bar(r.tokens_consumed, max_tokens)
        ts = _format_timestamp(r.timestamp)
        if r.tokens_consumed >= 1000:
            tok_str = f"{r.tokens_consumed / 1000:.1f}k"
        else:
            tok_str = str(r.tokens_consumed)
        cost_str = f"${r.cost_usd:.2f}" if r.cost_usd >= 0.01 else f"${r.cost_usd:.4f}"
        lines.append(f"  {ts}  {bar} {tok_str} tokens, {cost_str}")
    return lines


def render_trends(runs: list[RunMetrics], format: str = "ascii") -> str:
    sections = [
        _render_finding_count(runs),
        _render_category_distribution(runs),
        _render_execution_rate(runs),
        _render_token_consumption(runs),
    ]
    body = "\n".join("\n".join(s) for s in sections)
    if format == "markdown":
        summary_lines = [
            "| Timestamp | Findings | Ideas | Success | Tokens | Cost |",
            "|-----------|----------|-------|---------|--------|------|",
        ]
        for r in runs:
            if r.execution_total_count > 0:
                pct = f"{r.execution_success_count / r.execution_total_count * 100:.0f}%"
            else:
                pct = "N/A"
            cost_str = f"${r.cost_usd:.2f}" if r.cost_usd >= 0.01 else f"${r.cost_usd:.4f}"
            summary_lines.append(
                f"| {_format_timestamp(r.timestamp)} | {r.total_findings} | "
                f"{r.total_ideas} | {pct} | {r.tokens_consumed} | {cost_str} |"
            )
        summary = "\n".join(summary_lines)
        return f"{summary}\n\n```\n{body}\n```"
    return body
