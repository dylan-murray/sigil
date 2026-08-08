from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sigil.pipeline.feedback import (
    PROutcome,
    _distill_lessons,
    collect_lessons,
    fetch_pr_outcomes,
)
from sigil.integrations.github import GitHubClient


def _mock_client() -> GitHubClient:
    repo = MagicMock()
    gh = MagicMock()
    return GitHubClient(gh=gh, repo=repo)


def _mock_pr(
    *,
    number: int = 1,
    title: str = "sigil: Fix dead code",
    state: str = "open",
    merged: bool = False,
    labels: list[str] | None = None,
    review_comments: list[str] | None = None,
    body: str = "## Changes\nFixed dead code.",
) -> MagicMock:
    pr = MagicMock()
    pr.number = number
    pr.title = title
    pr.state = state
    pr.merged = merged
    lbl_objs = []
    for name in labels or ["sigil"]:
        lbl = MagicMock()
        lbl.name = name
        lbl_objs.append(lbl)
    pr.labels = lbl_objs
    if review_comments is not None:
        comment_objs = []
        for text in review_comments:
            rc = MagicMock()
            rc.body = text
            comment_objs.append(rc)
        pr.get_review_comments.return_value = comment_objs
    else:
        pr.get_review_comments.return_value = []
    pr.body = body
    return pr


def _mock_llm_response(content: str) -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    return resp


@pytest.mark.asyncio
async def test_fetch_pr_outcomes_empty():
    client = _mock_client()
    client.repo.get_pulls.return_value = []

    outcomes = await fetch_pr_outcomes(client)

    assert outcomes == []


@pytest.mark.asyncio
async def test_fetch_pr_outcomes_merged_pr():
    pr = _mock_pr(number=10, title="sigil: Fix bug", state="closed", merged=True)
    client = _mock_client()
    client.repo.get_pulls.return_value = [pr]

    outcomes = await fetch_pr_outcomes(client)

    assert len(outcomes) == 1
    assert outcomes[0].number == 10
    assert outcomes[0].state == "merged"
    assert outcomes[0].title == "sigil: Fix bug"


@pytest.mark.asyncio
async def test_fetch_pr_outcomes_closed_pr():
    pr = _mock_pr(number=11, title="sigil: Bad idea", state="closed", merged=False)
    client = _mock_client()
    client.repo.get_pulls.return_value = [pr]

    outcomes = await fetch_pr_outcomes(client)

    assert len(outcomes) == 1
    assert outcomes[0].state == "closed"


@pytest.mark.asyncio
async def test_fetch_pr_outcomes_open_pr():
    pr = _mock_pr(number=12, title="sigil: WIP", state="open", merged=False)
    client = _mock_client()
    client.repo.get_pulls.return_value = [pr]

    outcomes = await fetch_pr_outcomes(client)

    assert len(outcomes) == 1
    assert outcomes[0].state == "open"


@pytest.mark.asyncio
async def test_fetch_pr_outcomes_with_review_comments():
    pr = _mock_pr(
        number=13,
        title="sigil: Refactor",
        review_comments=["Please use a different approach", "This breaks backward compat"],
    )
    client = _mock_client()
    client.repo.get_pulls.return_value = [pr]

    outcomes = await fetch_pr_outcomes(client)

    assert len(outcomes) == 1
    assert len(outcomes[0].review_comments) == 2
    assert "Please use a different approach" in outcomes[0].review_comments


@pytest.mark.asyncio
async def test_fetch_pr_outcomes_with_category_label():
    pr = _mock_pr(number=14, labels=["sigil", "sigil:security"])
    client = _mock_client()
    client.repo.get_pulls.return_value = [pr]

    outcomes = await fetch_pr_outcomes(client)

    assert outcomes[0].category == "security"


@pytest.mark.asyncio
async def test_fetch_pr_outcomes_skips_non_sigil():
    pr = _mock_pr(number=15, labels=["bug", "enhancement"])
    client = _mock_client()
    client.repo.get_pulls.return_value = [pr]

    outcomes = await fetch_pr_outcomes(client)

    assert outcomes == []


@pytest.mark.asyncio
async def test_fetch_pr_outcomes_max_prs():
    prs = [_mock_pr(number=i) for i in range(10)]
    client = _mock_client()
    client.repo.get_pulls.return_value = prs

    outcomes = await fetch_pr_outcomes(client, max_prs=3)

    assert len(outcomes) == 3


@pytest.mark.asyncio
async def test_fetch_pr_outcomes_review_comment_error():
    pr = _mock_pr(number=16)
    pr.get_review_comments.side_effect = Exception("API error")
    client = _mock_client()
    client.repo.get_pulls.return_value = [pr]

    outcomes = await fetch_pr_outcomes(client)

    assert len(outcomes) == 1
    assert outcomes[0].review_comments == []


@pytest.mark.asyncio
async def test_distill_lessons():
    outcomes = [
        PROutcome(
            number=1,
            title="sigil: Fix dead code",
            state="merged",
            category="dead_code",
            review_comments=[],
            body_snippet="Removed unused imports",
        ),
        PROutcome(
            number=2,
            title="sigil: Add retry logic",
            state="closed",
            category="",
            review_comments=["This approach is too complex"],
            body_snippet="Added retry wrapper",
        ),
    ]

    with patch(
        "sigil.pipeline.feedback.acompletion",
        new_callable=AsyncMock,
        return_value=_mock_llm_response(
            "## Lessons\n- Avoid complex retry patterns\n- Dead code removals are well-received"
        ),
    ):
        result = await _distill_lessons(outcomes, "test-model")

    assert "Avoid complex retry patterns" in result


@pytest.mark.asyncio
async def test_distill_lessons_truncates_long_output():
    outcomes = [
        PROutcome(
            number=1,
            title="sigil: Fix",
            state="merged",
            category="",
            review_comments=[],
            body_snippet="",
        ),
    ]

    long_content = "x" * 5000
    with patch(
        "sigil.pipeline.feedback.acompletion",
        new_callable=AsyncMock,
        return_value=_mock_llm_response(long_content),
    ):
        result = await _distill_lessons(outcomes, "test-model")

    assert len(result) <= 2000


@pytest.mark.asyncio
async def test_distill_lessons_llm_failure():
    outcomes = [
        PROutcome(
            number=1,
            title="sigil: Fix",
            state="merged",
            category="",
            review_comments=[],
            body_snippet="",
        ),
    ]

    with patch(
        "sigil.pipeline.feedback.acompletion",
        new_callable=AsyncMock,
        side_effect=Exception("LLM error"),
    ):
        result = await _distill_lessons(outcomes, "test-model")

    assert result == ""


@pytest.mark.asyncio
async def test_collect_lessons_no_prs():
    client = _mock_client()
    client.repo.get_pulls.return_value = []

    with patch(
        "sigil.pipeline.feedback.acompletion",
        new_callable=AsyncMock,
    ) as mock_llm:
        result = await collect_lessons(Path("/tmp/repo"), client, "test-model")

    assert result is None
    mock_llm.assert_not_called()


@pytest.mark.asyncio
async def test_collect_lessons_saves_and_returns(tmp_path):
    pr = _mock_pr(number=1, title="sigil: Fix bug", state="merged", merged=True)
    client = _mock_client()
    client.repo.get_pulls.return_value = [pr]

    with patch(
        "sigil.pipeline.feedback.acompletion",
        new_callable=AsyncMock,
        return_value=_mock_llm_response("## Lessons\n- Merged PRs are good"),
    ):
        result = await collect_lessons(tmp_path, client, "test-model")

    assert result is not None
    assert "Merged PRs are good" in result

    lessons_file = tmp_path / ".sigil" / "memory" / "lessons.md"
    assert lessons_file.exists()
    assert "Merged PRs are good" in lessons_file.read_text()


@pytest.mark.asyncio
async def test_collect_lessons_with_status_callback(tmp_path):
    pr = _mock_pr(number=1, title="sigil: Fix", state="merged", merged=True)
    client = _mock_client()
    client.repo.get_pulls.return_value = [pr]

    statuses = []

    def on_status(msg: str) -> None:
        statuses.append(msg)

    with patch(
        "sigil.pipeline.feedback.acompletion",
        new_callable=AsyncMock,
        return_value=_mock_llm_response("Lessons learned"),
    ):
        await collect_lessons(tmp_path, client, "test-model", on_status=on_status)

    assert any("Fetching PR" in s for s in statuses)
    assert any("Distilling" in s for s in statuses)


@pytest.mark.asyncio
async def test_collect_lessons_distillation_failure(tmp_path):
    pr = _mock_pr(number=1, title="sigil: Fix", state="merged", merged=True)
    client = _mock_client()
    client.repo.get_pulls.return_value = [pr]

    with patch(
        "sigil.pipeline.feedback.acompletion",
        new_callable=AsyncMock,
        side_effect=Exception("LLM down"),
    ):
        result = await collect_lessons(tmp_path, client, "test-model")

    assert result is None
