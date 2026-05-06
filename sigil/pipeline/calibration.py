import re
from dataclasses import replace
from pathlib import Path

from sigil.pipeline.models import Finding

_RISK_LEVELS = ("low", "medium", "high")

_DEF_PATTERN = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)")
_CLASS_PATTERN = re.compile(r"^\s*class\s+(\w+)")


def _extract_symbol_at_line(source_lines: list[str], line_number: int) -> str | None:
    if line_number < 1 or line_number > len(source_lines):
        return None
    for i in range(line_number - 1, -1, -1):
        m = _CLASS_PATTERN.match(source_lines[i])
        if m:
            return m.group(1)
        m = _DEF_PATTERN.match(source_lines[i])
        if m:
            return m.group(1)
    return None


def _extract_symbols_from_file(repo: Path, file_path: str) -> list[str]:
    full = repo / file_path
    if not full.exists() or not full.is_file():
        return []
    try:
        text = full.read_text()
    except OSError:
        return []
    symbols: list[str] = []
    for line in text.splitlines():
        m = _CLASS_PATTERN.match(line)
        if m:
            symbols.append(m.group(1))
            continue
        m = _DEF_PATTERN.match(line)
        if m:
            symbols.append(m.group(1))
    return symbols


def _find_test_files(repo: Path, test_dir: str) -> list[Path]:
    td = repo / test_dir
    if not td.is_dir():
        return []
    return sorted(p for p in td.rglob("test_*.py") if p.is_file())


def _has_test_coverage(
    repo: Path,
    symbols: list[str],
    file_path: str,
    test_files: list[Path],
) -> bool:
    file_stem = Path(file_path).stem
    for tf in test_files:
        tf_stem = tf.stem
        if tf_stem == f"test_{file_stem}" or tf_stem == f"{file_stem}_test":
            return True
        try:
            content = tf.read_text()
        except OSError:
            continue
        for sym in symbols:
            if sym in content:
                return True
    return False


def _adjust_risk(risk: str, covered: bool) -> str:
    idx = _RISK_LEVELS.index(risk) if risk in _RISK_LEVELS else 1
    if covered:
        new_idx = min(idx + 1, len(_RISK_LEVELS) - 1)
    else:
        new_idx = max(idx - 1, 0)
    return _RISK_LEVELS[new_idx]


def calibrate_findings(
    findings: list[Finding],
    repo: Path,
    test_dir: str = "tests",
) -> list[Finding]:
    if not findings:
        return []
    test_files = _find_test_files(repo, test_dir)
    calibrated: list[Finding] = []
    for finding in findings:
        full = repo / finding.file
        if not full.exists() or not full.is_file():
            calibrated.append(finding)
            continue
        symbols: list[str] = []
        if finding.line is not None:
            try:
                lines = full.read_text().splitlines()
            except OSError:
                calibrated.append(finding)
                continue
            sym = _extract_symbol_at_line(lines, finding.line)
            if sym:
                symbols = [sym]
            else:
                symbols = _extract_symbols_from_file(repo, finding.file)
        else:
            symbols = _extract_symbols_from_file(repo, finding.file)
        covered = _has_test_coverage(repo, symbols, finding.file, test_files)
        new_risk = _adjust_risk(finding.risk, covered)
        if covered and symbols:
            note = f" [coverage: {', '.join(symbols)} tested]"
        elif covered:
            note = " [coverage: file has test file]"
        else:
            note = (
                f" [coverage: no tests found for {', '.join(symbols)}]"
                if symbols
                else " [coverage: no tests found]"
            )
        calibrated.append(replace(finding, risk=new_risk, rationale=finding.rationale + note))
    return calibrated
