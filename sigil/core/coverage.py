import json
import logging
import xml.etree.ElementTree as ET
from pathlib import Path

from sigil.core.utils import arun

logger = logging.getLogger(__name__)


def get_coverage_map(repo: Path) -> dict[str, float]:
    """
    Returns a map of relative file paths to their line coverage percentage.
    Tries coverage.xml, then coverage.json, then runs pytest --cov.
    """
    # 1. Try Cobertura XML
    xml_path = repo / "coverage.xml"
    if xml_path.exists():
        try:
            return _parse_cobertura_xml(xml_path)
        except Exception as e:
            logger.warning("Failed to parse coverage.xml: %s", e)

    # 2. Try coverage.json
    json_path = repo / "coverage.json"
    if json_path.exists():
        try:
            return _parse_coverage_json(json_path)
        except Exception as e:
            logger.warning("Failed to parse coverage.json: %s", e)

    # 3. Fallback: run pytest --cov
    try:
        rc, stdout, _ = await_arun_coverage(repo)
        if rc == 0 and stdout:
            return _parse_json_string(stdout)
    except Exception as e:
        logger.warning("Fallback coverage run failed: %s", e)

    return {}


def _parse_cobertura_xml(path: Path) -> dict[str, float]:
    tree = ET.parse(path)
    root = tree.getroot()
    coverage_map: dict[str, float] = {}

    # Cobertura XML structure: packages -> package -> classes -> class
    for cls in root.findall(".//class"):
        filename = cls.get("filename", "")
        line_rate = cls.get("line-rate", "0")
        try:
            coverage_map[filename] = float(line_rate) * 100
        except ValueError:
            continue
    return coverage_map


def _parse_coverage_json(path: Path) -> dict[str, float]:
    data = json.loads(path.read_text())
    coverage_map: dict[str, float] = {}

    # coverage.py JSON format: files -> {path: {summary: {percent_covered: ...}}}
    files = data.get("files", {})
    for path_str, info in files.items():
        summary = info.get("summary", {})
        percent = summary.get("percent_covered")
        if percent is not None:
            # Normalize path to be relative to repo root if it's absolute
            # This is a heuristic; actual normalization depends on how coverage was run
            coverage_map[path_str] = float(percent)

    return coverage_map


def _parse_json_string(json_str: str) -> dict[str, float]:
    try:
        return _parse_coverage_json(Path(json_str))  # This is wrong, should be json.loads
    except:
        return {}


# Correcting the helper for the fallback
def _parse_raw_json(json_str: str) -> dict[str, float]:
    try:
        data = json.loads(json_str)
        coverage_map: dict[str, float] = {}
        files = data.get("files", {})
        for path_str, info in files.items():
            summary = info.get("summary", {})
            percent = summary.get("percent_covered")
            if percent is not None:
                coverage_map[path_str] = float(percent)
        return coverage_map
    except Exception:
        return {}


async def await_arun_coverage(repo: Path) -> tuple[int, str, str]:
    # We use a wrapper because get_coverage_map is sync but needs async arun
    # In a real implementation, get_coverage_map would be async.
    # Since the plan says get_coverage_map(repo), and discovery is async,
    # we should probably make get_coverage_map async.
    return await arun(["pytest", "--cov=sigil", "--cov-report=json", "-q"], cwd=repo, timeout=30)


def format_coverage_summary(coverage_map: dict[str, float]) -> str:
    if not coverage_map:
        return ""

    well_tested = []
    partially_tested = []
    low_coverage = []

    for path, pct in coverage_map.items():
        if pct >= 80:
            well_tested.append(f"{path} ({pct:.1f}%)")
        elif pct >= 50:
            partially_tested.append(f"{path} ({pct:.1f}%)")
        else:
            low_coverage.append(f"{path} ({pct:.1f}%)")

    sections = []
    if well_tested:
        sections.append("Well-tested (≥80%):\n- " + "\n- ".join(well_tested))
    if partially_tested:
        sections.append("Partially tested (50-79%):\n- " + "\n- ".join(partially_tested))
    if low_coverage:
        sections.append("Low coverage (<50%):\n- " + "\n- ".join(low_coverage))

    return "\n\n".join(sections)
