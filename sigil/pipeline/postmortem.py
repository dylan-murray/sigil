from pathlib import Path

from sigil.pipeline.ideation import FeatureIdea
from sigil.pipeline.maintenance import Finding
from sigil.pipeline.models import ExecutionResult

INSIGHTS_FILE = "last_run_insights.md"
_MAX_INSIGHTS_CHARS = 2000


def _item_category(item: object) -> str:
    if isinstance(item, Finding):
        return item.category
    if isinstance(item, FeatureIdea):
        return "feature"
    return "unknown"


def _item_file(item: object) -> str:
    if isinstance(item, Finding):
        return item.file
    return ""


def _is_test_file(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    return any(p.startswith("test_") or p.endswith("_test.py") or p == "tests" for p in parts)


def analyze_run(results: list[tuple[object, ExecutionResult, str]]) -> str:
    if not results:
        return ""

    total = len(results)
    successes = sum(1 for _, r, _ in results if r.success)
    _failures = total - successes
    first_attempt = sum(1 for _, r, _ in results if r.success and r.retries == 0)
    needed_retries = sum(1 for _, r, _ in results if r.retries > 0)
    downgraded = sum(1 for _, r, _ in results if r.downgraded)
    doom_loops = sum(1 for _, r, _ in results if r.doom_loop_detected)

    lines: list[str] = []

    if total == successes:
        lines.append(f"All {total} item(s) succeeded.")
        if first_attempt == total:
            lines.append("Every item passed on first attempt — no retries needed.")
        else:
            lines.append(
                f"{first_attempt}/{total} passed on first attempt; {needed_retries} needed retries."
            )
        if doom_loops:
            lines.append(f"Warning: {doom_loops} doom loop(s) detected despite success.")
        return _truncate("\n".join(lines))

    success_rate = successes / total * 100
    lines.append(f"Success rate: {success_rate:.0f}% ({successes}/{total}).")
    if first_attempt:
        lines.append(f"First-attempt successes: {first_attempt}.")
    if needed_retries:
        lines.append(f"Items needing retries: {needed_retries}.")
    if downgraded:
        lines.append(f"Downgraded to issues: {downgraded}.")

    if doom_loops:
        lines.append(
            f"Doom loops detected: {doom_loops} — consider increasing max_rounds or simplifying tasks."
        )

    fail_by_category: dict[str, int] = {}
    fail_by_type: dict[str, int] = {}
    fail_files: list[str] = []
    for item, result, _ in results:
        if result.success:
            continue
        cat = _item_category(item)
        fail_by_category[cat] = fail_by_category.get(cat, 0) + 1
        ft = result.failure_type.value if result.failure_type else "unknown"
        fail_by_type[ft] = fail_by_type.get(ft, 0) + 1
        f = _item_file(item)
        if f:
            fail_files.append(f)

    if fail_by_category:
        parts = [f"{cat}={n}" for cat, n in sorted(fail_by_category.items())]
        lines.append(f"Failures by category: {', '.join(parts)}.")

    if fail_by_type:
        parts = [f"{ft}={n}" for ft, n in sorted(fail_by_type.items())]
        lines.append(f"Failures by type: {', '.join(parts)}.")

    test_failures = sum(1 for f in fail_files if _is_test_file(f))
    if test_failures and test_failures >= len(fail_files) // 2 and len(fail_files) >= 2:
        lines.append(
            "Failures concentrated in test files — consider reading existing tests before editing."
        )

    hook_failures = fail_by_type.get("post_hook", 0) + fail_by_type.get("pre_hook", 0)
    if hook_failures >= 2:
        lines.append(
            "Multiple hook failures — review hook config and consider relaxing checks for automated runs."
        )

    rebase_failures = fail_by_type.get("rebase", 0)
    if rebase_failures >= 2:
        lines.append(
            "Multiple rebase conflicts — main branch may be changing rapidly during execution."
        )

    return _truncate("\n".join(lines))


def _truncate(text: str) -> str:
    if len(text) <= _MAX_INSIGHTS_CHARS:
        return text
    lines = text.splitlines()
    result: list[str] = []
    total = 0
    for line in lines:
        if total + len(line) + 1 > _MAX_INSIGHTS_CHARS:
            break
        result.append(line)
        total += len(line) + 1
    return "\n".join(result)


def load_run_insights(repo: Path) -> str:
    path = repo / ".sigil" / INSIGHTS_FILE
    if not path.exists():
        return ""
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def save_run_insights(repo: Path, insights: str) -> None:
    sigil_dir = repo / ".sigil"
    sigil_dir.mkdir(parents=True, exist_ok=True)
    path = sigil_dir / INSIGHTS_FILE
    try:
        path.write_text(insights)
    except OSError:
        pass
