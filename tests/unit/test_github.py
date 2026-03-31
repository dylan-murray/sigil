from pathlib import Path
import logging
from unittest.mock import MagicMock, patch, PropertyMock

from github import GithubException

from sigil.core.config import Config
from sigil.pipeline.models import ExecutionResult
from sigil.integrations.github import (
    GitHubClient,
    SIGIL_LABEL,
    _category_label,
    _extract_finding_key,
    _format_issue_body,
    _format_pr_body,
    _is_similar,
    _item_key,
    _item_title,
    _normalize,
    _parse_remote_url,
    _title_tokens,
    create_client,
    dedup_items,
    ensure_labels,
    fetch_existing_issues,
    open_issue,
    open_pr,
    publish_results,
)
from sigil.pipeline.ideation import FeatureIdea
from sigil.pipeline.maintenance import Finding


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
    )
    defaults.update(kw)
    return Finding(**defaults)


def _make_idea(**kw) -> FeatureIdea:
    defaults = dict(
        title="Add retry logic",
        description="Retry failed HTTP calls",
        rationale="Improves reliability",
        complexity="small",
        disposition="pr",
        priority=2,
    )
    defaults.update(kw)
    return FeatureIdea(**defaults)


def _make_result(**kw) -> ExecutionResult:
    defaults = dict(
        success=True,
        diff="+added line",
        hooks_passed=True,
        failed_hook=None,
        retries=0,
        failure_reason=None,
    )
    defaults.update(kw)
    return ExecutionResult(**defaults)


def _mock_client() -> GitHubClient:
    repo = MagicMock()
    gh = MagicMock()
    return GitHubClient(gh=gh, repo=repo)


async def test_create_client_no_token(tmp_path):
    with patch.dict("os.environ", {}, clear=True):
        assert await create_client(tmp_path) is None


async def test_create_client_ssh_url(tmp_path):
    async def fake_get_remote_url(repo):
        return "git@github.com:owner/repo.git"

    with (
        patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_test"}),
        patch("sigil.integrations.github._get_remote_url", side_effect=fake_get_remote_url),
        patch("sigil.integrations.github.Github") as mock_gh_cls,
    ):
        mock_gh = MagicMock()
        mock_repo = MagicMock()
        mock_gh.get_repo.return_value = mock_repo
        mock_gh_cls.return_value = mock_gh

        client = await create_client(tmp_path)
        assert client is not None
        mock_gh.get_repo.assert_called_once_with("owner/repo")


async def test_create_client_https_url(tmp_path):
    async def fake_get_remote_url(repo):
        return "https://github.com/owner/repo.git"

    with (
        patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_test"}),
        patch("sigil.integrations.github._get_remote_url", side_effect=fake_get_remote_url),
        patch("sigil.integrations.github.Github") as mock_gh_cls,
    ):
        mock_gh = MagicMock()
        mock_repo = MagicMock()
        mock_gh.get_repo.return_value = mock_repo
        mock_gh_cls.return_value = mock_gh

        client = await create_client(tmp_path)
        assert client is not None
        mock_gh.get_repo.assert_called_once_with("owner/repo")


def test_parse_remote_url_ssh():
    assert _parse_remote_url("git@github.com:owner/repo.git") == "owner/repo"
    assert _parse_remote_url("git@github.com:owner/repo") == "owner/repo"


def test_parse_remote_url_https():
    assert _parse_remote_url("https://github.com/owner/repo.git") == "owner/repo"
    assert _parse_remote_url("https://github.com/owner/repo") == "owner/repo"


def test_parse_remote_url_invalid():
    assert _parse_remote_url("https://gitlab.com/owner/repo") == ""
    assert _parse_remote_url("") == ""


def test_item_title_finding():
    f = _make_finding(description="Unused import `os` in utils.py")
    assert _item_title(f) == "sigil: Unused import `os` in utils"


def test_item_title_finding_long_description():
    f = _make_finding(
        description="This is a very long description that exceeds the sixty character limit for PR titles and should be truncated."
    )
    title = _item_title(f)
    assert title.startswith("sigil: This is a very long description")
    assert len(title) <= 67


def test_item_title_idea():
    idea = _make_idea(title="Add retry logic")
    assert _item_title(idea) == "sigil: Add retry logic"


def test_normalize():
    assert _normalize("sigil: Fix dead_code in utils") == "fix dead_code in utils"
    assert _normalize("  Sigil:   lots   of  spaces  ") == "lots of spaces"
    assert _normalize("no prefix here") == "no prefix here"


def test_title_tokens():
    tokens = _title_tokens("sigil: fix dead_code in src/utils.py")
    assert "dead" in tokens
    assert "code" in tokens
    assert "utils" in tokens


def test_item_key_finding():
    finding = _make_finding()
    assert _item_key(finding) == "dead_code:src/utils.py"


def test_item_key_idea():
    idea = _make_idea()
    assert _item_key(idea) is None


def test_extract_finding_key():
    assert _extract_finding_key("sigil: fix dead_code in src/utils.py") == "dead_code:src/utils.py"
    assert _extract_finding_key("sigil: Add retry logic") is None


def test_is_similar():
    a = {"dead", "code", "utils"}
    b = {"dead", "code", "utils", "extra"}
    assert _is_similar(a, b)
    assert not _is_similar(a, {"completely", "different", "tokens"})


async def test_dedup_items_filters_duplicates():
    client = _mock_client()

    mock_pr = MagicMock()
    mock_pr.title = "sigil: fix dead_code in src/utils.py"
    mock_label = MagicMock()
    mock_label.name = SIGIL_LABEL
    mock_pr.labels = [mock_label]
    client.repo.get_pulls.return_value = [mock_pr]
    client.repo.get_issues.return_value = []

    finding = _make_finding()
    idea = _make_idea()

    result = await dedup_items(client, [finding, idea])

    assert finding in result.skipped
    assert idea in result.remaining


def test_format_pr_body_finding():
    f = _make_finding()
    r = _make_result()
    body = _format_pr_body(f, r, "Removed dead code from utils.py")
    assert "## Changes" in body
    assert "Removed dead code" in body
    assert "## What" not in body


def test_format_pr_body_idea():
    idea = _make_idea()
    r = _make_result()
    body = _format_pr_body(idea, r, "Added retry logic with backoff")
    assert "## Changes" in body
    assert "Added retry logic" in body
    assert "Complexity: small" in body


def test_format_pr_body_with_summary():
    idea = _make_idea()
    r = _make_result(
        summary="Added retry logic to http_client.py with exponential backoff. Added test_http_retry.py covering timeout and 5xx scenarios."
    )
    pr_summary = "Added retry logic to http_client.py with exponential backoff."
    body = _format_pr_body(idea, r, pr_summary)
    assert "## Changes\nAdded retry logic to http_client.py" in body
    assert "## Status" in body


def test_format_pr_body_finding_with_summary():
    f = _make_finding()
    r = _make_result(summary="Removed unused `parse_legacy` function from utils.py.")
    body = _format_pr_body(f, r, "Removed unused `parse_legacy` function from utils.py.")
    assert "## Changes\nRemoved unused" in body


def test_format_issue_body_finding():
    f = _make_finding()
    body = _format_issue_body(f)
    assert "## Finding" in body
    assert "dead_code" in body
    assert "src/utils.py:42" in body


def test_format_issue_body_with_downgrade():
    f = _make_finding()
    body = _format_issue_body(f, downgrade_context="Rebase failed")
    assert "Downgrade Context" in body
    assert "Rebase failed" in body


def test_format_issue_body_idea():
    idea = _make_idea()
    body = _format_issue_body(idea)
    assert "## Idea" in body
    assert "Add retry logic" in body


async def test_ensure_labels_creates_missing():
    client = _mock_client()
    client.repo.get_label.side_effect = GithubException(404, {}, {})

    await ensure_labels(client)

    client.repo.create_label.assert_called_once()
    args = client.repo.create_label.call_args
    assert args[1]["name"] == SIGIL_LABEL


async def test_ensure_labels_already_exists():
    client = _mock_client()
    client.repo.get_label.return_value = MagicMock()

    await ensure_labels(client)

    client.repo.create_label.assert_not_called()


async def test_open_pr_success():
    client = _mock_client()
    f = _make_finding()
    r = _make_result()

    mock_pr = MagicMock()
    mock_pr.html_url = "https://github.com/owner/repo/pull/1"
    client.repo.create_pull.return_value = mock_pr
    type(client.repo).default_branch = PropertyMock(return_value="main")

    async def fake_push(repo, branch):
        return True

    with patch("sigil.integrations.github.push_branch", side_effect=fake_push):
        url = await open_pr(client, f, r, "sigil/auto/test-branch", Path("/tmp"))

    assert url == "https://github.com/owner/repo/pull/1"
    client.repo.create_pull.assert_called_once()


async def test_open_pr_push_fails():
    client = _mock_client()
    f = _make_finding()
    r = _make_result()

    async def fake_push(repo, branch):
        return False

    with patch("sigil.integrations.github.push_branch", side_effect=fake_push):
        url = await open_pr(client, f, r, "sigil/auto/test-branch", Path("/tmp"))

    assert url is None
    client.repo.create_pull.assert_not_called()


async def test_open_pr_github_error():
    client = _mock_client()
    f = _make_finding()
    r = _make_result()
    client.repo.create_pull.side_effect = GithubException(422, {}, {})
    type(client.repo).default_branch = PropertyMock(return_value="main")

    async def fake_push(repo, branch):
        return True

    with patch("sigil.integrations.github.push_branch", side_effect=fake_push):
        url = await open_pr(client, f, r, "sigil/auto/test-branch", Path("/tmp"))

    assert url is None


async def test_publish_results_respects_limits():
    client = _mock_client()
    config = Config(max_prs_per_run=1, max_github_issues=1)

    f1 = _make_finding(file="a.py")
    f2 = _make_finding(file="b.py")
    r = _make_result()

    exec_results = [
        (f1, r, "sigil/auto/a"),
        (f2, r, "sigil/auto/b"),
    ]

    issue_items = [
        (_make_finding(file="c.py", disposition="issue"), None),
        (_make_finding(file="d.py", disposition="issue"), None),
    ]

    mock_pr = MagicMock()
    mock_pr.html_url = "https://github.com/owner/repo/pull/1"
    client.repo.create_pull.return_value = mock_pr
    type(client.repo).default_branch = PropertyMock(return_value="main")

    mock_issue = MagicMock()
    mock_issue.html_url = "https://github.com/owner/repo/issues/1"
    client.repo.create_issue.return_value = mock_issue

    async def fake_push(repo, branch):
        return True

    with patch("sigil.integrations.github.push_branch", side_effect=fake_push):
        pr_urls, issue_urls, pushed = await publish_results(
            Path("/tmp"), config, client, exec_results, issue_items
        )

    assert len(pr_urls) == 1
    assert len(issue_urls) == 1
    assert len(pushed) == 1


async def test_open_issue_success():
    client = _mock_client()
    f = _make_finding()

    mock_issue = MagicMock()
    mock_issue.html_url = "https://github.com/owner/repo/issues/1"
    client.repo.create_issue.return_value = mock_issue
    client.repo.get_label.return_value = MagicMock()

    url = await open_issue(client, f)

    assert url == "https://github.com/owner/repo/issues/1"
    client.repo.create_issue.assert_called_once()
    mock_issue.add_to_labels.assert_called_once_with("sigil:dead_code")


async def test_open_issue_github_error():
    client = _mock_client()
    f = _make_finding()
    client.repo.create_issue.side_effect = GithubException(500, {}, {})

    url = await open_issue(client, f)

    assert url is None


async def test_open_issue_creates_category_label():
    client = _mock_client()
    f = _make_finding(category="security")

    mock_issue = MagicMock()
    mock_issue.html_url = "https://github.com/owner/repo/issues/2"
    client.repo.create_issue.return_value = mock_issue
    client.repo.get_label.side_effect = GithubException(404, {}, {})

    await open_issue(client, f)

    client.repo.create_label.assert_called_once_with(name="sigil:security", color="CCCCCC")


def test_category_label_finding():
    f = _make_finding(category="security")
    assert _category_label(f) == "sigil:security"


def test_category_label_idea():
    idea = _make_idea()
    assert _category_label(idea) == "sigil:feature"


def _mock_gh_issue(*, number=1, title="Test", body="desc", is_pr=False, labels=None, comments=None):
    issue = MagicMock()
    issue.number = number
    issue.title = title
    issue.body = body
    issue.state = "open"
    issue.pull_request = MagicMock() if is_pr else None
    lbl = MagicMock()
    lbl.name = SIGIL_LABEL
    issue.labels = labels if labels is not None else [lbl]
    issue.get_comments.return_value = comments or []
    return issue


async def test_fetch_existing_issues_mixed():
    client = _mock_client()
    issue1 = _mock_gh_issue(number=1, title="Bug A")
    pr = _mock_gh_issue(number=2, title="PR B", is_pr=True)
    issue2 = _mock_gh_issue(number=3, title="Bug C")
    client.repo.get_issues.return_value = [issue1, pr, issue2]

    result = await fetch_existing_issues(client)

    assert len(result) == 2
    assert result[0].number == 1
    assert result[1].number == 3


async def test_fetch_existing_issues_directive_in_comment():
    client = _mock_client()
    comment = MagicMock()
    comment.body = "Please @SIGIL WORK ON THIS asap"
    issue = _mock_gh_issue(number=10, comments=[comment])
    client.repo.get_issues.return_value = [issue]

    result = await fetch_existing_issues(client)

    assert len(result) == 1
    assert result[0].has_directive is True


async def test_fetch_existing_issues_body_truncation():
    client = _mock_client()
    long_body = "x" * 500
    issue = _mock_gh_issue(number=1, body=long_body)
    client.repo.get_issues.return_value = [issue]

    result = await fetch_existing_issues(client)

    assert len(result[0].body) == 200


async def test_fetch_existing_issues_max_cap():
    client = _mock_client()
    issues = [_mock_gh_issue(number=i) for i in range(5)]
    client.repo.get_issues.return_value = issues

    result = await fetch_existing_issues(client, max_issues=2)

    assert len(result) == 2


async def test_fetch_existing_issues_comment_error_logs_warning(caplog):
    client = _mock_client()
    issue = _mock_gh_issue(number=42, title="Broken comments")
    issue.get_comments.side_effect = GithubException(500, {}, {})
    client.repo.get_issues.return_value = [issue]

    with caplog.at_level(logging.WARNING, logger="sigil.github"):
        result = await fetch_existing_issues(client)

    assert len(result) == 1
    assert result[0].has_directive is False
    assert "Failed to fetch comments for #42" in caplog.text


async def test_fetch_existing_issues_empty():
    client = _mock_client()
    client.repo.get_issues.return_value = []

    result = await fetch_existing_issues(client)

    assert result == []


async def test_fetch_existing_issues_none_body():
    client = _mock_client()
    issue = _mock_gh_issue(number=1, body=None)
    client.repo.get_issues.return_value = [issue]

    result = await fetch_existing_issues(client)

    assert result[0].body == ""
