import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from github import GithubException

from sigil.core.llm import acompletion, safe_max_tokens
from sigil.core.utils import StatusCallback
from sigil.integrations.github import GitHubClient
from sigil.state.memory import save_lessons

logger = logging.getLogger(__name__)

LESSONS_FILE = "lessons.md"
MAX_PRS = 50
MAX_LESSONS_CHARS = 2000


@dataclass(frozen=True)
class PROutcome:
    number: int
    title: str
    state: str
    category: str
    review_comments: list[str]
    body_snippet: str


def _fetch_pr_outcomes_sync(client: GitHubClient, *, max_prs: int = MAX_PRS) -> list[PROutcome]:
    outcomes: list[PROutcome] = []
    try:
        pulls = client.repo.get_pulls(state="all", sort="updated", direction="desc")
    except GithubException as e:
        logger.warning("Failed to fetch PRs: %s", e)
        return outcomes

    for pr in pulls:
        if len(outcomes) >= max_prs:
            break
        has_sigil = any(lbl.name == "sigil" for lbl in pr.labels)
        if not has_sigil:
            continue

        if pr.merged:
            state = "merged"
        elif pr.state == "closed":
            state = "closed"
        else:
            state = "open"

        category = ""
        for lbl in pr.labels:
            if lbl.name.startswith("sigil:") and lbl.name != "sigil":
                category = lbl.name.replace("sigil:", "", 1)
                break

        comments: list[str] = []
        try:
            for rc in pr.get_review_comments():
                body = (rc.body or "").strip()
                if body:
                    comments.append(body)
        except Exception as e:
            logger.warning("Failed to fetch review comments for PR #%d: %s", pr.number, e)

        body_snippet = (pr.body or "")[:300]

        outcomes.append(
            PROutcome(
                number=pr.number,
                title=pr.title,
                state=state,
                category=category,
                review_comments=comments,
                body_snippet=body_snippet,
            )
        )

    return outcomes


async def fetch_pr_outcomes(client: GitHubClient, *, max_prs: int = MAX_PRS) -> list[PROutcome]:
    return await asyncio.to_thread(_fetch_pr_outcomes_sync, client, max_prs=max_prs)


DISTILL_PROMPT = """\
You are analyzing the outcomes of previously opened pull requests by an AI agent (Sigil) \
to extract actionable lessons for future runs.

## PR Outcomes

{outcomes}

## Task

Write a concise markdown document of lessons learned. For each lesson:
- Be specific: reference categories, patterns, or file types
- Be actionable: what should the agent do differently?
- Be brief: one bullet point per lesson, under 2000 characters total

Focus on:
- Types of changes that were rejected (closed without merging) and why
- Patterns that reviewers flagged as problematic
- Categories of findings that keep getting vetoed
- Common review feedback themes

If all PRs were merged with no negative feedback, note that the agent is performing well \
and should continue its current approach.

Output ONLY the markdown lessons (no preamble, no code fences). Keep it under 2000 characters."""


async def _distill_lessons(outcomes: list[PROutcome], model: str) -> str:
    lines: list[str] = []
    for o in outcomes:
        comments_str = ""
        if o.review_comments:
            truncated = [c[:200] for c in o.review_comments[:5]]
            comments_str = "; ".join(truncated)
        lines.append(
            f"- PR #{o.number} [{o.state}] {o.title}"
            f"{' (category: ' + o.category + ')' if o.category else ''}"
            f"{' | Comments: ' + comments_str if comments_str else ''}"
        )
    outcomes_text = "\n".join(lines)

    msgs = [{"role": "user", "content": DISTILL_PROMPT.format(outcomes=outcomes_text)}]
    try:
        response = await acompletion(
            label="feedback:distill",
            model=model,
            messages=msgs,
            temperature=0.0,
            max_tokens=safe_max_tokens(model, msgs, requested=1_024),
        )
        content = response.choices[0].message.content or ""
        if len(content) > MAX_LESSONS_CHARS:
            content = content[:MAX_LESSONS_CHARS]
        return content.strip()
    except Exception as e:
        logger.warning("Lesson distillation failed: %s", e)
        return ""


async def collect_lessons(
    repo: Path,
    client: GitHubClient,
    model: str,
    *,
    on_status: StatusCallback | None = None,
) -> str | None:
    if on_status:
        on_status("Fetching PR outcomes...")

    outcomes = await fetch_pr_outcomes(client)
    if not outcomes:
        logger.info("No prior Sigil PRs found — skipping lesson collection")
        return None

    if on_status:
        on_status(f"Distilling lessons from {len(outcomes)} PR(s)...")

    lessons = await _distill_lessons(outcomes, model)
    if not lessons:
        return None

    save_lessons(repo, lessons)
    return lessons
