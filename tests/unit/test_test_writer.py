"""
Tests for the Test-Writer agent (Red-Green-Refactor TDD loop).
"""

from pathlib import Path

import pytest
from unittest.mock import patch

from sigil.core.agent import AgentResult
from sigil.core.config import Config
from sigil.pipeline.test_writer import run_test_writer
from sigil.pipeline.maintenance import Finding
from sigil.pipeline.ideation import FeatureIdea


def _make_finding(**kw) -> Finding:
    defaults = dict(
        category="dead_code",
        file="src/utils.py",
        line=42,
        description="Unused import",
        risk="low",
        suggested_fix="Remove it",
        disposition="pr",
        priority=1,
        rationale="Not referenced",
        implementation_spec="Remove the unused import from src/utils.py",
    )
    defaults.update(kw)
    return Finding(**defaults)


def _make_idea(**kw) -> FeatureIdea:
    defaults = dict(
        title="Add retry logic",
        description="Retry failed HTTP calls",
        rationale="Improves reliability",
        complexity="low",
        disposition="pr",
        priority=2,
        implementation_spec="Add retry decorator to http_client.py",
    )
    defaults.update(kw)
    return FeatureIdea(**defaults)


def _make_agent_result(summary="Test written: added tests/test_utils.py", stop_result=None):
    return AgentResult(
        messages=[{"role": "user", "content": "test"}],
        doom_loop=False,
        rounds=1,
        stop_result=stop_result or summary,
        last_content="",
    )


@pytest.fixture
def mock_agent_run():
    """Patch Agent.run to return a successful result."""

    async def fake_run(self, *, messages=None, context=None, on_status=None):
        return _make_agent_result()

    return fake_run


@pytest.mark.asyncio
async def test_run_test_writer_happy_path_finding(mock_agent_run):
    """Test that run_test_writer successfully writes a test for a finding."""
    config = Config()
    finding = _make_finding()

    with patch("sigil.pipeline.test_writer.Agent.run", mock_agent_run):
        summary = await run_test_writer(
            repo=Path("/fake/repo"),
            config=config,
            item=finding,
            task_description="Remove unused import",
            memory_context="",
            working_memory="",
            repo_conventions="",
            preloaded_files="",
            ignore=None,
            on_status=None,
        )

    assert summary is not None
    assert "test" in summary.lower()


@pytest.mark.asyncio
async def test_run_test_writer_happy_path_idea(mock_agent_run):
    """Test that run_test_writer successfully writes a test for a feature idea."""
    config = Config()
    idea = _make_idea()

    with patch("sigil.pipeline.test_writer.Agent.run", mock_agent_run):
        summary = await run_test_writer(
            repo=Path("/fake/repo"),
            config=config,
            item=idea,
            task_description="Add retry logic",
            memory_context="",
            working_memory="",
            repo_conventions="",
            preloaded_files="",
            ignore=None,
            on_status=None,
        )

    assert summary is not None
    assert "test" in summary.lower()


@pytest.mark.asyncio
async def test_run_test_writer_uses_correct_model():
    """Test that the test_writer model from config is used."""
    custom_model = "google/gemini-2.5-flash"
    config = Config(agents={"test_writer": {"model": custom_model}})
    finding = _make_finding()

    agent_instances = []

    from sigil.core.agent import Agent as _Agent

    original_init = _Agent.__init__

    def tracking_init(self, **kwargs):
        agent_instances.append(kwargs)
        return original_init(self, **kwargs)

    with patch("sigil.core.agent.Agent.__init__", side_effect=tracking_init, autospec=True):
        with patch("sigil.core.agent.Agent.run", return_value=_make_agent_result()):
            await run_test_writer(
                repo=Path("/fake/repo"),
                config=config,
                item=finding,
                task_description="test",
                memory_context="",
                working_memory="",
                repo_conventions="",
            )

    assert len(agent_instances) == 1
    assert agent_instances[0]["model"] == custom_model


@pytest.mark.asyncio
async def test_run_test_writer_agent_no_stop_result():
    """Test fallback to last_content when stop_result is None."""
    config = Config()
    finding = _make_finding()

    async def fake_run(self, *, messages=None, context=None, on_status=None):
        return AgentResult(
            messages=[],
            doom_loop=False,
            rounds=1,
            stop_result=None,
            last_content="I wrote a comprehensive failing test in tests/test_failing.py that covers all the edge cases and will fail until the fix is implemented.",
        )

    with patch("sigil.pipeline.test_writer.Agent.run", fake_run):
        summary = await run_test_writer(
            repo=Path("/fake/repo"),
            config=config,
            item=finding,
            task_description="test",
            memory_context="",
            working_memory="",
            repo_conventions="",
        )

    assert (
        summary
        == "I wrote a comprehensive failing test in tests/test_failing.py that covers all the edge cases and will fail until the fix is implemented."
    )


@pytest.mark.asyncio
async def test_run_test_writer_agent_no_content_returns_none():
    """Test that None is returned when agent produces no useful output."""
    config = Config()
    finding = _make_finding()

    async def fake_run(self, *, messages=None, context=None, on_status=None):
        return AgentResult(
            messages=[],
            doom_loop=False,
            rounds=1,
            stop_result=None,
            last_content="   ",  # whitespace only
        )

    with patch("sigil.pipeline.test_writer.Agent.run", fake_run):
        summary = await run_test_writer(
            repo=Path("/fake/repo"),
            config=config,
            item=finding,
            task_description="test",
            memory_context="",
            working_memory="",
            repo_conventions="",
        )

    assert summary is None


@pytest.mark.asyncio
async def test_run_test_writer_agent_exception_returns_none():
    """Test that exceptions are caught and None is returned."""
    config = Config()
    finding = _make_finding()

    async def fake_run(self, *, messages=None, context=None, on_status=None):
        raise RuntimeError("LLM API error")

    with patch("sigil.pipeline.test_writer.Agent.run", fake_run):
        summary = await run_test_writer(
            repo=Path("/fake/repo"),
            config=config,
            item=finding,
            task_description="test",
            memory_context="",
            working_memory="",
            repo_conventions="",
        )

    assert summary is None


@pytest.mark.asyncio
async def test_run_test_writer_non_pr_disposition():
    """Test that test_writer returns None for non-PR dispositions."""
    config = Config()
    finding = _make_finding(disposition="issue")

    async def fake_run(self, *, messages=None, context=None, on_status=None):
        return _make_agent_result()

    with patch("sigil.pipeline.test_writer.Agent.run", fake_run):
        summary = await run_test_writer(
            repo=Path("/fake/repo"),
            config=config,
            item=finding,
            task_description="test",
            memory_context="",
            working_memory="",
            repo_conventions="",
        )

    # Should return None because test_writer is only run for PR items
    assert summary is None


def test_run_test_writer_uses_default_model_when_not_configured():
    """Test that default model is used when test_writer agent config is not set."""
    from sigil.core.config import DEFAULT_MODEL

    config = Config()  # Uses default model
    finding = _make_finding()

    agent_instances = []

    from sigil.core.agent import Agent as _Agent

    original_init = _Agent.__init__

    def tracking_init(self, **kwargs):
        agent_instances.append(kwargs)
        return original_init(self, **kwargs)

    with patch("sigil.core.agent.Agent.__init__", side_effect=tracking_init, autospec=True):
        with patch("sigil.core.agent.Agent.run", return_value=_make_agent_result()):
            import asyncio

            asyncio.run(
                run_test_writer(
                    repo=Path("/fake/repo"),
                    config=config,
                    item=finding,
                    task_description="test",
                    memory_context="",
                    working_memory="",
                    repo_conventions="",
                )
            )

    assert len(agent_instances) == 1
    # Default model from config module
    assert agent_instances[0]["model"] == DEFAULT_MODEL
