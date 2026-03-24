from pathlib import Path

import pytest

from sigil.pipeline.executor import execute_parallel
from sigil.pipeline.ideation import FeatureIdea, ideate
from sigil.pipeline.maintenance import Finding, analyze
from sigil.pipeline.validation import validate_all
from tests.integration.conftest import PROVIDER_IDS, make_config, skip_if_no_key

FINDING_CATEGORIES = {"dead_code", "tests", "security", "docs", "types", "todo", "style"}
FINDING_RISKS = {"low", "medium", "high"}
FINDING_DISPOSITIONS = {"pr", "issue", "skip"}
IDEA_COMPLEXITIES = {"small", "medium", "large"}
IDEA_DISPOSITIONS = {"pr", "issue"}

TIMEOUT = 300


@pytest.mark.integration
@pytest.mark.timeout(TIMEOUT)
@pytest.mark.parametrize("provider", PROVIDER_IDS, ids=PROVIDER_IDS)
async def test_analyze_returns_valid_findings(provider: str, sample_repo: Path):
    skip_if_no_key(provider)
    config = make_config(provider)
    findings = await analyze(repo=sample_repo, config=config)

    assert isinstance(findings, list)
    assert len(findings) >= 1, f"Expected at least 1 finding from {provider}"

    for f in findings:
        assert isinstance(f, Finding)
        assert f.category in FINDING_CATEGORIES, f"Bad category: {f.category}"
        assert f.risk in FINDING_RISKS, f"Bad risk: {f.risk}"
        assert f.disposition in FINDING_DISPOSITIONS, f"Bad disposition: {f.disposition}"
        assert f.priority >= 1
        assert f.description
        assert f.file
        assert (sample_repo / f.file).exists(), f"Hallucinated path: {f.file}"


@pytest.mark.integration
@pytest.mark.timeout(TIMEOUT)
@pytest.mark.parametrize("provider", PROVIDER_IDS, ids=PROVIDER_IDS)
async def test_ideate_returns_valid_ideas(provider: str, sample_repo: Path):
    skip_if_no_key(provider)
    config = make_config(provider, boldness="bold")
    ideas = await ideate(repo=sample_repo, config=config)

    assert isinstance(ideas, list)
    assert len(ideas) >= 1, f"Expected at least 1 idea from {provider}"

    for idea in ideas:
        assert isinstance(idea, FeatureIdea)
        assert idea.complexity in IDEA_COMPLEXITIES, f"Bad complexity: {idea.complexity}"
        assert idea.disposition in IDEA_DISPOSITIONS, f"Bad disposition: {idea.disposition}"
        assert idea.priority >= 1
        assert idea.title
        assert idea.description
        assert idea.rationale


@pytest.mark.integration
@pytest.mark.timeout(TIMEOUT)
@pytest.mark.parametrize("provider", PROVIDER_IDS, ids=PROVIDER_IDS)
async def test_validate_vetoes_hallucination(provider: str, sample_repo: Path):
    skip_if_no_key(provider)
    config = make_config(provider)

    hallucinated = Finding(
        category="security",
        file="nonexistent/phantom_file.py",
        line=10,
        description="Hardcoded password in phantom file",
        risk="high",
        suggested_fix="Remove hardcoded password",
        disposition="pr",
        priority=1,
        rationale="Security risk from hardcoded credentials",
    )
    real = Finding(
        category="docs",
        file="README.md",
        line=None,
        description="README could benefit from additional examples",
        risk="low",
        suggested_fix="Add usage examples to README",
        disposition="pr",
        priority=2,
        rationale="Improves developer onboarding",
    )

    result = await validate_all(
        repo=sample_repo,
        config=config,
        findings=[hallucinated, real],
        ideas=[],
    )

    result_files = {f.file for f in result.findings}
    assert "nonexistent/phantom_file.py" not in result_files, (
        "Hallucinated finding should be vetoed"
    )
    assert "README.md" in result_files, "Real finding should survive validation"


@pytest.mark.integration
@pytest.mark.timeout(TIMEOUT)
@pytest.mark.parametrize("provider", PROVIDER_IDS, ids=PROVIDER_IDS)
async def test_execute_fixes_planted_bug(provider: str, tiny_repo: Path):
    skip_if_no_key(provider)
    config = make_config(provider)

    bug_finding = Finding(
        category="tests",
        file="app.py",
        line=2,
        description="add() subtracts instead of adding: returns a - b instead of a + b",
        risk="low",
        suggested_fix="Change 'return a - b' to 'return a + b'",
        disposition="pr",
        priority=1,
        rationale="Obvious bug — function does the opposite of what it claims",
    )

    results = await execute_parallel(
        repo=tiny_repo,
        config=config,
        items=[bug_finding],
    )

    assert len(results) == 1
    _item, exec_result, branch = results[0]
    assert exec_result.success is True, f"Execution failed: {exec_result.failure_reason}"
    assert exec_result.diff, "Expected non-empty diff"
    assert branch, "Expected non-empty branch name"
