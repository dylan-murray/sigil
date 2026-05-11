from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from sigil.core.config import Config
from sigil.integrations.github import GitHubClient, PullRequestInfo
from sigil.pipeline.mcs import (
    MCSCandidate,
    MCSResult,
    MCSRanking,
    _build_mcs_prompt,
    run_mcs,
)


def _make_pr_info(**kw) -> PullRequestInfo:
    defaults = dict(
        number=1,
        title="Fix bug in utils",
        body="This PR fixes a bug.",
        additions=10,
        deletions=5,
        changed_files=2,
        url="https://github.com/owner/repo/pull/1",
    )
    defaults.update(kw)
    return PullRequestInfo(**defaults)


def _make_client() -> GitHubClient:
    repo = MagicMock()
    gh = MagicMock()
    return GitHubClient(gh=gh, repo=repo)


class TestMCSResult:
    def test_default(self):
        result = MCSResult(approved=[], reasons={})
        assert result.approved == []
        assert result.reasons == {}

    def test_with_data(self):
        result = MCSResult(approved=[1, 2], reasons={1: "Good", 2: "OK"})
        assert result.approved == [1, 2]
        assert result.reasons[1] == "Good"


class TestMCSCandidate:
    def test_creation(self):
        c = MCSCandidate(pr_number=1, reasoning="Solid fix", score=8)
        assert c.pr_number == 1
        assert c.score == 8


class TestMCSRanking:
    def test_creation(self):
        ranking = MCSRanking(
            candidates=[
                MCSCandidate(pr_number=1, reasoning="Good", score=9),
                MCSCandidate(pr_number=2, reasoning="OK", score=6),
            ]
        )
        assert len(ranking.candidates) == 2

    def test_empty(self):
        ranking = MCSRanking(candidates=[])
        assert ranking.candidates == []


class TestBuildMCSPrompt:
    def test_single_pr(self):
        prs = [_make_pr_info()]
        prompt = _build_mcs_prompt(prs)
        assert "#1" in prompt
        assert "Fix bug in utils" in prompt
        assert "+10/-5" in prompt
        assert "2 file(s)" in prompt

    def test_multiple_prs(self):
        prs = [
            _make_pr_info(number=1, title="Fix A"),
            _make_pr_info(number=2, title="Fix B"),
        ]
        prompt = _build_mcs_prompt(prs)
        assert "#1" in prompt
        assert "#2" in prompt
        assert "Fix A" in prompt
        assert "Fix B" in prompt

    def test_body_truncation(self):
        long_body = "a" * 1000
        prs = [_make_pr_info(body=long_body)]
        prompt = _build_mcs_prompt(prs)
        assert "a" * 501 not in prompt

    def test_empty_prs(self):
        prompt = _build_mcs_prompt([])
        assert prompt.strip() == ""


class TestRunMCS:
    @pytest.mark.asyncio
    async def test_mcs_disabled(self):
        config = Config(mcs_enabled=False)
        result = await run_mcs(Path("/tmp"), config, _make_client())
        assert result is None

    @pytest.mark.asyncio
    async def test_no_open_prs(self):
        config = Config(mcs_enabled=True)
        client = _make_client()
        with patch("sigil.pipeline.mcs.fetch_open_sigil_prs", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = []
            result = await run_mcs(Path("/tmp"), config, client)
        assert result is None

    @pytest.mark.asyncio
    async def test_happy_path(self):
        config = Config(mcs_enabled=True, mcs_top_n=2)
        client = _make_client()
        prs = [
            _make_pr_info(number=1, title="Fix A"),
            _make_pr_info(number=2, title="Fix B"),
            _make_pr_info(number=3, title="Fix C"),
        ]
        ranking = MCSRanking(
            candidates=[
                MCSCandidate(pr_number=1, reasoning="Critical fix", score=9),
                MCSCandidate(pr_number=2, reasoning="Good improvement", score=7),
                MCSCandidate(pr_number=3, reasoning="Minor cleanup", score=4),
            ]
        )
        with (
            patch("sigil.pipeline.mcs.fetch_open_sigil_prs", new_callable=AsyncMock) as mock_fetch,
            patch("sigil.pipeline.mcs.structured_completion", new_callable=AsyncMock) as mock_llm,
            patch("sigil.pipeline.mcs.add_label_to_pr", new_callable=AsyncMock) as _mock_label,
        ):
            mock_fetch.return_value = prs
            mock_llm.return_value = ranking
            result = await run_mcs(Path("/tmp"), config, client)

        assert result is not None
        assert result.approved == [1, 2]
        assert result.reasons[1] == "Critical fix"
        assert result.reasons[2] == "Good improvement"
        assert _mock_label.call_count == 2

    @pytest.mark.asyncio
    async def test_fewer_prs_than_top_n(self):
        config = Config(mcs_enabled=True, mcs_top_n=5)
        client = _make_client()
        prs = [_make_pr_info(number=1, title="Fix A")]
        ranking = MCSRanking(candidates=[MCSCandidate(pr_number=1, reasoning="Good", score=8)])
        with (
            patch("sigil.pipeline.mcs.fetch_open_sigil_prs", new_callable=AsyncMock) as mock_fetch,
            patch("sigil.pipeline.mcs.structured_completion", new_callable=AsyncMock) as mock_llm,
            patch("sigil.pipeline.mcs.add_label_to_pr", new_callable=AsyncMock) as _mock_label,
        ):
            mock_fetch.return_value = prs
            mock_llm.return_value = ranking
            result = await run_mcs(Path("/tmp"), config, client)

        assert result is not None
        assert result.approved == [1]
        assert _mock_label.call_count == 1

    @pytest.mark.asyncio
    async def test_llm_failure_returns_none(self):
        config = Config(mcs_enabled=True)
        client = _make_client()
        prs = [_make_pr_info(number=1, title="Fix A")]
        with (
            patch("sigil.pipeline.mcs.fetch_open_sigil_prs", new_callable=AsyncMock) as mock_fetch,
            patch("sigil.pipeline.mcs.structured_completion", new_callable=AsyncMock) as mock_llm,
        ):
            mock_fetch.return_value = prs
            mock_llm.side_effect = Exception("LLM error")
            result = await run_mcs(Path("/tmp"), config, client)

        assert result is None

    @pytest.mark.asyncio
    async def test_label_failure_does_not_fail(self):
        config = Config(mcs_enabled=True, mcs_top_n=1)
        client = _make_client()
        prs = [_make_pr_info(number=1, title="Fix A")]
        ranking = MCSRanking(candidates=[MCSCandidate(pr_number=1, reasoning="Good", score=8)])
        with (
            patch("sigil.pipeline.mcs.fetch_open_sigil_prs", new_callable=AsyncMock) as mock_fetch,
            patch("sigil.pipeline.mcs.structured_completion", new_callable=AsyncMock) as mock_llm,
            patch("sigil.pipeline.mcs.add_label_to_pr", new_callable=AsyncMock) as _mock_label,
        ):
            mock_fetch.return_value = prs
            mock_llm.return_value = ranking
            _mock_label.side_effect = Exception("Label error")
            result = await run_mcs(Path("/tmp"), config, client)

        assert result is not None
        assert result.approved == [1]

    @pytest.mark.asyncio
    async def test_uses_mcs_agent_model(self):
        config = Config(
            mcs_enabled=True,
            agents={"mcs": [{"model": "google/gemini-2.5-pro"}]},
        )
        client = _make_client()
        prs = [_make_pr_info(number=1, title="Fix A")]
        ranking = MCSRanking(candidates=[MCSCandidate(pr_number=1, reasoning="Good", score=8)])
        with (
            patch("sigil.pipeline.mcs.fetch_open_sigil_prs", new_callable=AsyncMock) as mock_fetch,
            patch("sigil.pipeline.mcs.structured_completion", new_callable=AsyncMock) as mock_llm,
            patch("sigil.pipeline.mcs.add_label_to_pr", new_callable=AsyncMock) as _mock_label,
        ):
            mock_fetch.return_value = prs
            mock_llm.return_value = ranking
            await run_mcs(Path("/tmp"), config, client)

        call_kwargs = mock_llm.call_args
        assert call_kwargs.kwargs.get("model") == "google/gemini-2.5-pro"

    @pytest.mark.asyncio
    async def test_on_status_callback(self):
        config = Config(mcs_enabled=True)
        client = _make_client()
        prs = [_make_pr_info(number=1, title="Fix A")]
        ranking = MCSRanking(candidates=[MCSCandidate(pr_number=1, reasoning="Good", score=8)])
        status_messages = []

        def on_status(msg: str) -> None:
            status_messages.append(msg)

        with (
            patch("sigil.pipeline.mcs.fetch_open_sigil_prs", new_callable=AsyncMock) as mock_fetch,
            patch("sigil.pipeline.mcs.structured_completion", new_callable=AsyncMock) as mock_llm,
            patch("sigil.pipeline.mcs.add_label_to_pr", new_callable=AsyncMock) as _mock_label,
        ):
            mock_fetch.return_value = prs
            mock_llm.return_value = ranking
            await run_mcs(Path("/tmp"), config, client, on_status=on_status)

        assert any("1 PR" in msg for msg in status_messages)
