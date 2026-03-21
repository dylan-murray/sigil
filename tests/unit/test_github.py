from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

from github import GithubException

from sigil.config import Config
from sigil.executor import ExecutionResult
from sigil.github import (
    GitHubClient,
    SIGIL_LABEL,
    _category_label,
    _format_issue_body,
    _format_pr_body,
    _item_title,
    _matches_existing,
    _normalize,
    _parse_remote_url,
    create_client,
    dedup_items,
    ensure_labels,
    open_issue,
    open_pr,
    publish_results,
)
from sigil.ideation import FeatureIdea
from sigil.maintenance import Finding


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
        lint_passed=True,
        tests_passed=True,
        retries=0,
        failure_reason=None,
    )
    defaults.update(kw)
    return ExecutionResult(**defaults)


def _mock_client() -> GitHubClient:
    repo = MagicMock()
    gh = MagicMock()
    return GitHubClient(gh=gh, repo=repo)


def test_create_client_no_token(tmp_path):
    with patch.dict("os.environ", {}, clear=True):
        assert create_client(tmp_path) is None


def test_create_client_ssh_url(tmp_path):
    with (
        patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_test"}),
        patch("sigil.github._get_remote_url", return_value="git@github.com:owner/repo.git"),
        patch("sigil.github.Github") as mock_gh_cls,
    ):
        mock_gh = MagicMock()
        mock_repo = MagicMock()
        mock_gh.get_repo.return_value = mock_repo
        mock_gh_cls.return_value = mock_gh

        client = create_client(tmp_path)
        assert client is not None
        mock_gh.get_repo.assert_called_once_with("owner/repo")


def test_create_client_https_url(tmp_path):
    with (
        patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_test"}),
        patch("sigil.github._get_remote_url", return_value="https://github.com/owner/repo.git"),
        patch("sigil.github.Github") as mock_gh_cls,
    ):
        mock_gh = MagicMock()
        mock_repo = MagicMock()
        mock_gh.get_repo.return_value = mock_repo
        mock_gh_cls.return_value = mock_gh

        client = create_client(tmp_path)
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
    f = _make_finding(category="dead_code", file="src/utils.py")
    assert _item_title(f) == "sigil: fix dead_code in src/utils.py"


def test_item_title_idea():
    idea = _make_idea(title="Add retry logic")
    assert _item_title(idea) == "sigil: Add retry logic"


def test_normalize():
    assert _normalize("sigil: Fix dead_code in utils") == "fix dead_code in utils"
    assert _normalize("  Sigil:   lots   of  spaces  ") == "lots of spaces"
    assert _normalize("no prefix here") == "no prefix here"


def test_matches_existing():
    existing = {"fix dead_code in src/utils.py", "add retry logic"}
    assert _matches_existing("sigil: fix dead_code in src/utils.py", existing)
    assert _matches_existing("sigil: Add retry logic", existing)
    assert not _matches_existing("sigil: something new", existing)


def test_dedup_items_filters_duplicates():
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

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        result = dedup_items(client, [finding, idea])

    assert finding in result.skipped
    assert idea in result.remaining


def test_format_pr_body_finding():
    f = _make_finding()
    r = _make_result()
    body = _format_pr_body(f, r)
    assert "## What" in body
    assert "## Why" in body
    assert "dead_code" in body
    assert "src/utils.py" in body


def test_format_pr_body_idea():
    idea = _make_idea()
    r = _make_result()
    body = _format_pr_body(idea, r)
    assert "Add retry logic" in body
    assert "Complexity: small" in body


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


def test_ensure_labels_creates_missing():
    client = _mock_client()
    client.repo.get_label.side_effect = GithubException(404, {}, {})

    ensure_labels(client)

    client.repo.create_label.assert_called_once()
    args = client.repo.create_label.call_args
    assert args[1]["name"] == SIGIL_LABEL


def test_ensure_labels_already_exists():
    client = _mock_client()
    client.repo.get_label.return_value = MagicMock()

    ensure_labels(client)

    client.repo.create_label.assert_not_called()


def test_open_pr_success():
    client = _mock_client()
    f = _make_finding()
    r = _make_result()

    mock_pr = MagicMock()
    mock_pr.html_url = "https://github.com/owner/repo/pull/1"
    client.repo.create_pull.return_value = mock_pr
    type(client.repo).default_branch = PropertyMock(return_value="main")

    with patch("sigil.github.push_branch", return_value=True):
        url = open_pr(client, f, r, "sigil/auto/test-branch", Path("/tmp"))

    assert url == "https://github.com/owner/repo/pull/1"
    client.repo.create_pull.assert_called_once()


def test_open_pr_push_fails():
    client = _mock_client()
    f = _make_finding()
    r = _make_result()

    with patch("sigil.github.push_branch", return_value=False):
        url = open_pr(client, f, r, "sigil/auto/test-branch", Path("/tmp"))

    assert url is None
    client.repo.create_pull.assert_not_called()


def test_open_pr_github_error():
    client = _mock_client()
    f = _make_finding()
    r = _make_result()
    client.repo.create_pull.side_effect = GithubException(422, {}, {})
    type(client.repo).default_branch = PropertyMock(return_value="main")

    with patch("sigil.github.push_branch", return_value=True):
        url = open_pr(client, f, r, "sigil/auto/test-branch", Path("/tmp"))

    assert url is None


def test_publish_results_respects_limits():
    client = _mock_client()
    config = Config(max_prs_per_run=1, max_issues_per_run=1)

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

    with patch("sigil.github.push_branch", return_value=True):
        pr_urls, issue_urls, pushed = publish_results(
            Path("/tmp"), config, client, exec_results, issue_items
        )

    assert len(pr_urls) == 1
    assert len(issue_urls) == 1
    assert len(pushed) == 1


def test_open_issue_success():
    client = _mock_client()
    f = _make_finding()

    mock_issue = MagicMock()
    mock_issue.html_url = "https://github.com/owner/repo/issues/1"
    client.repo.create_issue.return_value = mock_issue
    client.repo.get_label.return_value = MagicMock()

    url = open_issue(client, f)

    assert url == "https://github.com/owner/repo/issues/1"
    client.repo.create_issue.assert_called_once()
    mock_issue.add_to_labels.assert_called_once_with("sigil:dead_code")


def test_open_issue_github_error():
    client = _mock_client()
    f = _make_finding()
    client.repo.create_issue.side_effect = GithubException(500, {}, {})

    url = open_issue(client, f)

    assert url is None


def test_open_issue_creates_category_label():
    client = _mock_client()
    f = _make_finding(category="security")

    mock_issue = MagicMock()
    mock_issue.html_url = "https://github.com/owner/repo/issues/2"
    client.repo.create_issue.return_value = mock_issue
    client.repo.get_label.side_effect = GithubException(404, {}, {})

    open_issue(client, f)

    client.repo.create_label.assert_called_once_with(name="sigil:security", color="CCCCCC")


def test_category_label_finding():
    f = _make_finding(category="security")
    assert _category_label(f) == "sigil:security"


def test_category_label_idea():
    idea = _make_idea()
    assert _category_label(idea) == "sigil:feature"
