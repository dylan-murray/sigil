import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sigil.core.config import Config
from sigil.integrations.github import (
    GitHubClient,
    InlineComment,
    PRInfo,
    fetch_pr_diff,
    fetch_pr_info,
    post_inline_comments,
    post_review_comment,
)
from sigil.pipeline.review import (
    PRReviewFinding,
    ReviewResult,
    review_pr,
)


def _mock_client() -> GitHubClient:
    repo = MagicMock()
    gh = MagicMock()
    return GitHubClient(gh=gh, repo=repo)


def _make_finding(**kw) -> PRReviewFinding:
    defaults = dict(
        category="bug",
        file="src/main.py",
        line=10,
        description="Potential null pointer dereference",
        severity="high",
        suggested_fix="Add null check before accessing property",
        disposition="comment",
    )
    defaults.update(kw)
    return PRReviewFinding(**defaults)


class TestPRReviewFinding:
    def test_construction_defaults(self):
        f = PRReviewFinding(
            category="bug",
            file="src/main.py",
            line=10,
            description="Null deref",
            severity="high",
            suggested_fix="Add check",
            disposition="comment",
        )
        assert f.category == "bug"
        assert f.file == "src/main.py"
        assert f.line == 10
        assert f.description == "Null deref"
        assert f.severity == "high"
        assert f.suggested_fix == "Add check"
        assert f.disposition == "comment"

    def test_disposition_fix(self):
        f = _make_finding(disposition="fix")
        assert f.disposition == "fix"

    def test_disposition_skip(self):
        f = _make_finding(disposition="skip")
        assert f.disposition == "skip"

    def test_line_none(self):
        f = _make_finding(line=None)
        assert f.line is None


class TestReviewResult:
    def test_construction(self):
        findings = [_make_finding()]
        result = ReviewResult(
            findings=findings,
            summary_comment_url="https://github.com/owner/repo/pull/1#issuecomment-1",
            inline_comment_count=2,
            fix_pr_url=None,
        )
        assert len(result.findings) == 1
        assert result.summary_comment_url is not None
        assert result.inline_comment_count == 2
        assert result.fix_pr_url is None

    def test_empty_result(self):
        result = ReviewResult(
            findings=[],
            summary_comment_url=None,
            inline_comment_count=0,
            fix_pr_url=None,
        )
        assert result.findings == []
        assert result.summary_comment_url is None


class TestPRInfo:
    def test_construction(self):
        info = PRInfo(
            number=42,
            title="Add feature X",
            author="developer",
            base_ref="main",
            head_ref="feature-x",
            body="This PR adds feature X",
            changed_files=["src/main.py", "tests/test_main.py"],
        )
        assert info.number == 42
        assert info.title == "Add feature X"
        assert info.author == "developer"
        assert info.base_ref == "main"
        assert info.head_ref == "feature-x"
        assert len(info.changed_files) == 2


class TestInlineComment:
    def test_construction(self):
        comment = InlineComment(
            path="src/main.py",
            line=10,
            body="Consider adding a null check here.",
        )
        assert comment.path == "src/main.py"
        assert comment.line == 10
        assert comment.body == "Consider adding a null check here."


class TestFetchPrDiff:
    async def test_fetch_pr_diff_success(self):
        client = _mock_client()
        mock_pr = MagicMock()
        mock_pr.diff.return_value = "diff --git a/file.py b/file.py\n+added line"
        client.repo.get_pull.return_value = mock_pr

        result = await fetch_pr_diff(client, 42)
        assert "added line" in result
        client.repo.get_pull.assert_called_once_with(42)

    async def test_fetch_pr_diff_error(self):
        client = _mock_client()
        client.repo.get_pull.side_effect = GithubException(404, {}, {})

        result = await fetch_pr_diff(client, 42)
        assert result == ""


class TestFetchPrInfo:
    async def test_fetch_pr_info_success(self):
        client = _mock_client()
        mock_pr = MagicMock()
        mock_pr.number = 42
        mock_pr.title = "Add feature X"
        mock_pr.user.login = "developer"
        mock_pr.base.ref = "main"
        mock_pr.head.ref = "feature-x"
        mock_pr.body = "This PR adds feature X"
        mock_file = MagicMock()
        mock_file.filename = "src/main.py"
        mock_pr.get_files.return_value = [mock_file]
        client.repo.get_pull.return_value = mock_pr

        result = await fetch_pr_info(client, 42)
        assert result.number == 42
        assert result.title == "Add feature X"
        assert result.author == "developer"
        assert result.base_ref == "main"
        assert result.head_ref == "feature-x"
        assert result.changed_files == ["src/main.py"]


class TestPostReviewComment:
    async def test_post_review_comment_success(self):
        client = _mock_client()
        mock_pr = MagicMock()
        mock_comment = MagicMock()
        mock_comment.html_url = "https://github.com/owner/repo/pull/1#issuecomment-1"
        mock_pr.get_issue_comments.return_value = []
        mock_pr.create_issue_comment.return_value = mock_comment
        client.repo.get_pull.return_value = mock_pr

        result = await post_review_comment(client, 42, "## Review Summary\n\nNo issues found.")
        assert result == "https://github.com/owner/repo/pull/1#issuecomment-1"
        mock_pr.create_issue_comment.assert_called_once()

    async def test_post_review_comment_error(self):
        client = _mock_client()
        client.repo.get_pull.side_effect = GithubException(404, {}, {})

        result = await post_review_comment(client, 42, "Review comment")
        assert result is None


class TestPostInlineComments:
    async def test_post_inline_comments_success(self):
        client = _mock_client()
        mock_pr = MagicMock()
        mock_review = MagicMock()
        mock_review.submit.return_value = MagicMock()
        mock_pr.create_review.return_value = mock_review
        client.repo.get_pull.return_value = mock_pr

        comments = [
            InlineComment(path="src/main.py", line=10, body="Bug here"),
            InlineComment(path="src/utils.py", line=20, body="Style issue"),
        ]

        result = await post_inline_comments(client, 42, comments)
        assert len(result) == 2
        mock_pr.create_review.assert_called_once()
        call_kwargs = mock_pr.create_review.call_args
        assert call_kwargs[1]["body"] == ""
        assert len(call_kwargs[1]["comments"]) == 2

    async def test_post_inline_comments_empty(self):
        client = _mock_client()
        result = await post_inline_comments(client, 42, [])
        assert result == []

    async def test_post_inline_comments_error(self):
        client = _mock_client()
        client.repo.get_pull.side_effect = GithubException(404, {}, {})

        comments = [InlineComment(path="src/main.py", line=10, body="Bug")]
        result = await post_inline_comments(client, 42, comments)
        assert result == []


class TestReviewPrDryRun:
    async def test_review_pr_dry_run_no_posting(self, tmp_path):
        client = _mock_client()
        config = Config()

        mock_diff = "diff --git a/file.py b/file.py\n+added line"
        mock_info = PRInfo(
            number=42,
            title="Test PR",
            author="dev",
            base_ref="main",
            head_ref="feature",
            body="Test body",
            changed_files=["file.py"],
        )

        findings = [
            PRReviewFinding(
                category="bug",
                file="file.py",
                line=1,
                description="Test finding",
                severity="medium",
                suggested_fix="Fix it",
                disposition="comment",
            )
        ]

        with (
            patch(
                "sigil.pipeline.review.fetch_pr_diff",
                new_callable=AsyncMock,
                return_value=mock_diff,
            ),
            patch(
                "sigil.pipeline.review.fetch_pr_info",
                new_callable=AsyncMock,
                return_value=mock_info,
            ),
            patch(
                "sigil.pipeline.review._run_review_agent",
                new_callable=AsyncMock,
                return_value=findings,
            ),
            patch("sigil.pipeline.review.post_review_comment", new_callable=AsyncMock) as mock_post,
            patch(
                "sigil.pipeline.review.post_inline_comments", new_callable=AsyncMock
            ) as mock_inline,
        ):
            result = await review_pr(tmp_path, config, client, 42, dry_run=True)

        assert len(result.findings) == 1
        assert result.findings[0].description == "Test finding"
        assert result.summary_comment_url is None
        assert result.inline_comment_count == 0
        mock_post.assert_not_called()
        mock_inline.assert_not_called()

    async def test_review_pr_dry_run_posts_comments(self, tmp_path):
        client = _mock_client()
        config = Config()

        mock_diff = "diff --git a/file.py b/file.py\n+added line"
        mock_info = PRInfo(
            number=42,
            title="Test PR",
            author="dev",
            base_ref="main",
            head_ref="feature",
            body="Test body",
            changed_files=["file.py"],
        )

        findings = [
            PRReviewFinding(
                category="bug",
                file="file.py",
                line=1,
                description="Test finding",
                severity="medium",
                suggested_fix="Fix it",
                disposition="comment",
            )
        ]

        with (
            patch(
                "sigil.pipeline.review.fetch_pr_diff",
                new_callable=AsyncMock,
                return_value=mock_diff,
            ),
            patch(
                "sigil.pipeline.review.fetch_pr_info",
                new_callable=AsyncMock,
                return_value=mock_info,
            ),
            patch(
                "sigil.pipeline.review._run_review_agent",
                new_callable=AsyncMock,
                return_value=findings,
            ),
            patch(
                "sigil.pipeline.review.post_review_comment",
                new_callable=AsyncMock,
                return_value="https://github.com/owner/repo/pull/1#issuecomment-1",
            ) as mock_post,
            patch(
                "sigil.pipeline.review.post_inline_comments",
                new_callable=AsyncMock,
                return_value=["https://github.com/owner/repo/pull/1#discussion_r1"],
            ) as mock_inline,
        ):
            result = await review_pr(tmp_path, config, client, 42, dry_run=False)

        assert len(result.findings) == 1
        assert result.summary_comment_url == "https://github.com/owner/repo/pull/1#issuecomment-1"
        assert result.inline_comment_count == 1
        mock_post.assert_called_once()
        mock_inline.assert_called_once()

    async def test_review_pr_respects_max_comments(self, tmp_path):
        client = _mock_client()
        config = Config(review_max_comments=1)

        mock_diff = "diff --git a/file.py b/file.py\n+added line"
        mock_info = PRInfo(
            number=42,
            title="Test PR",
            author="dev",
            base_ref="main",
            head_ref="feature",
            body="Test body",
            changed_files=["file.py"],
        )

        findings = [
            PRReviewFinding(
                category="bug",
                file="file.py",
                line=1,
                description="Bug 1",
                severity="high",
                suggested_fix="Fix 1",
                disposition="comment",
            ),
            PRReviewFinding(
                category="style",
                file="file.py",
                line=5,
                description="Style issue",
                severity="low",
                suggested_fix="Fix 2",
                disposition="comment",
            ),
        ]

        with (
            patch(
                "sigil.pipeline.review.fetch_pr_diff",
                new_callable=AsyncMock,
                return_value=mock_diff,
            ),
            patch(
                "sigil.pipeline.review.fetch_pr_info",
                new_callable=AsyncMock,
                return_value=mock_info,
            ),
            patch(
                "sigil.pipeline.review._run_review_agent",
                new_callable=AsyncMock,
                return_value=findings,
            ),
            patch(
                "sigil.pipeline.review.post_review_comment",
                new_callable=AsyncMock,
                return_value="url1",
            ) as mock_post,
            patch(
                "sigil.pipeline.review.post_inline_comments",
                new_callable=AsyncMock,
                return_value=["url2"],
            ) as mock_inline,
        ):
            result = await review_pr(tmp_path, config, client, 42, dry_run=False)

        assert result.inline_comment_count == 1
        call_args = mock_inline.call_args
        posted_comments = call_args[0][2]
        assert len(posted_comments) == 1

    async def test_review_pr_no_findings(self, tmp_path):
        client = _mock_client()
        config = Config()

        mock_diff = "diff --git a/file.py b/file.py\n+added line"
        mock_info = PRInfo(
            number=42,
            title="Test PR",
            author="dev",
            base_ref="main",
            head_ref="feature",
            body="Test body",
            changed_files=["file.py"],
        )

        with (
            patch(
                "sigil.pipeline.review.fetch_pr_diff",
                new_callable=AsyncMock,
                return_value=mock_diff,
            ),
            patch(
                "sigil.pipeline.review.fetch_pr_info",
                new_callable=AsyncMock,
                return_value=mock_info,
            ),
            patch(
                "sigil.pipeline.review._run_review_agent", new_callable=AsyncMock, return_value=[]
            ),
            patch(
                "sigil.pipeline.review.post_review_comment",
                new_callable=AsyncMock,
                return_value="url",
            ) as mock_post,
        ):
            result = await review_pr(tmp_path, config, client, 42, dry_run=False)

        assert len(result.findings) == 0
        mock_post.assert_called_once()
        call_body = mock_post.call_args[0][2]
        assert "No issues found" in call_body

    async def test_review_pr_no_github_client(self, tmp_path):
        config = Config()

        mock_diff = "diff --git a/file.py b/file.py\n+added line"
        mock_info = PRInfo(
            number=42,
            title="Test PR",
            author="dev",
            base_ref="main",
            head_ref="feature",
            body="Test body",
            changed_files=["file.py"],
        )

        findings = [
            PRReviewFinding(
                category="bug",
                file="file.py",
                line=1,
                description="Test finding",
                severity="medium",
                suggested_fix="Fix it",
                disposition="comment",
            )
        ]

        with (
            patch(
                "sigil.pipeline.review.fetch_pr_diff",
                new_callable=AsyncMock,
                return_value=mock_diff,
            ),
            patch(
                "sigil.pipeline.review.fetch_pr_info",
                new_callable=AsyncMock,
                return_value=mock_info,
            ),
            patch(
                "sigil.pipeline.review._run_review_agent",
                new_callable=AsyncMock,
                return_value=findings,
            ),
        ):
            result = await review_pr(tmp_path, config, None, 42, dry_run=True)

        assert len(result.findings) == 1
        assert result.summary_comment_url is None


class TestConfigReviewFields:
    def test_default_review_auto_fix(self):
        config = Config()
        assert config.review_auto_fix is False

    def test_default_review_max_comments(self):
        config = Config()
        assert config.review_max_comments == 25

    def test_load_review_config(self, tmp_path):
        from sigil.core.config import SIGIL_DIR, CONFIG_FILE

        config_dir = tmp_path / SIGIL_DIR
        config_dir.mkdir(parents=True)
        config_file = config_dir / CONFIG_FILE
        config_file.write_text(
            "version: 1\n"
            "model: anthropic/claude-sonnet-4-6\n"
            "boldness: bold\n"
            "review_auto_fix: true\n"
            "review_max_comments: 10\n"
        )

        config = Config.load(tmp_path)
        assert config.review_auto_fix is True
        assert config.review_max_comments == 10

    def test_to_yaml_includes_review_fields(self):
        config = Config(review_auto_fix=True, review_max_comments=15)
        yaml_str = config.to_yaml()
        assert "review_auto_fix: True" in yaml_str
        assert "review_max_comments: 15" in yaml_str


class TestFormatReviewSummary:
    def test_format_review_summary_with_findings(self):
        from sigil.pipeline.review import _format_review_summary

        findings = [
            PRReviewFinding(
                category="bug",
                file="src/main.py",
                line=10,
                description="Null deref",
                severity="high",
                suggested_fix="Add null check",
                disposition="comment",
            ),
            PRReviewFinding(
                category="style",
                file="src/utils.py",
                line=5,
                description="Bad naming",
                severity="low",
                suggested_fix="Rename variable",
                disposition="comment",
            ),
        ]

        summary = _format_review_summary(findings)
        assert "2 finding(s)" in summary
        assert "bug" in summary
        assert "style" in summary
        assert "Null deref" in summary
        assert "Bad naming" in summary

    def test_format_review_summary_empty(self):
        from sigil.pipeline.review import _format_review_summary

        summary = _format_review_summary([])
        assert "No issues found" in summary

    def test_format_review_summary_with_fix_disposition(self):
        from sigil.pipeline.review import _format_review_summary

        findings = [
            PRReviewFinding(
                category="bug",
                file="src/main.py",
                line=10,
                description="Typo",
                severity="low",
                suggested_fix="Fix typo",
                disposition="fix",
            ),
        ]

        summary = _format_review_summary(findings)
        assert "1 finding(s)" in summary
        assert "fix" in summary.lower() or "Typo" in summary
