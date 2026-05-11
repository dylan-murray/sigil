import logging
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from sigil.core.config import Config
from sigil.core.llm import StructuredOutputError, structured_completion
from sigil.core.utils import StatusCallback
from sigil.integrations.github import GitHubClient, add_label_to_pr, fetch_open_sigil_prs

logger = logging.getLogger(__name__)

MCS_LABEL = "sigil:mcs"
MCS_LABEL_COLOR = "0E8A16"

MCS_SYSTEM_PROMPT = """\
You are a senior engineer evaluating pull requests for merge readiness. You \
assess each PR on quality, risk, and impact, then rank the best candidates \
for immediate merging.

For each PR, consider:
- **Correctness**: Does the change do what it claims? Are there obvious bugs?
- **Risk**: How likely is this to introduce regressions? Small, focused changes \
are lower risk.
- **Impact**: How valuable is this change? Bug fixes and security patches rank \
higher than cosmetic changes.
- **Test coverage**: Does the PR include tests? Untested changes are riskier.

Score each PR 1-10 (10 = most merge-ready). Be decisive — differentiate \
between PRs rather than giving everything the same score.
"""

MCS_CONTEXT_PROMPT = """\
Evaluate these open pull requests for merge readiness. Rank them by quality, \
lowest risk, and highest impact.

## Pull Requests

{pr_summaries}

Call the mcs_ranking tool with your ranked list of candidates.
"""


class MCSCandidate(BaseModel):
    pr_number: int = Field(description="The PR number")
    reasoning: str = Field(description="Brief reasoning for the score")
    score: int = Field(description="Merge readiness score 1-10, where 10 is most ready")


class MCSRanking(BaseModel):
    candidates: list[MCSCandidate] = Field(description="Ranked candidates, highest score first")


@dataclass(frozen=True)
class MCSResult:
    approved: list[int]
    reasons: dict[int, str]


def _build_mcs_prompt(prs: list) -> str:
    entries = []
    for pr in prs:
        body_excerpt = (pr.body or "")[:500]
        stats_line = f"+{pr.additions}/-{pr.deletions} across {pr.changed_files} file(s)"
        entries.append(
            f"### PR #{pr.number}: {pr.title}\n"
            f"URL: {pr.url}\n"
            f"Stats: {stats_line}\n"
            f"Body excerpt:\n{body_excerpt}"
        )
    return "\n\n".join(entries)


async def run_mcs(
    repo: Path,
    config: Config,
    gh_client: GitHubClient,
    *,
    on_status: StatusCallback | None = None,
) -> MCSResult | None:
    if on_status:
        on_status("Fetching open sigil PRs for MCS evaluation...")

    prs = await fetch_open_sigil_prs(gh_client)
    if not prs:
        logger.info("MCS: no open sigil PRs found, skipping")
        return None

    if on_status:
        on_status(f"Evaluating {len(prs)} PR(s) for merge readiness...")

    prompt_text = _build_mcs_prompt(prs)
    model = config.model_for("mcs")

    try:
        ranking = await structured_completion(
            label="mcs:rank",
            model=model,
            messages=[
                {"role": "system", "content": MCS_SYSTEM_PROMPT},
                {"role": "user", "content": MCS_CONTEXT_PROMPT.format(pr_summaries=prompt_text)},
            ],
            schema=MCSRanking,
            temperature=0.0,
            max_tokens=4096,
        )
    except StructuredOutputError as exc:
        logger.warning("MCS ranking failed: %s", exc)
        return None
    except Exception as exc:
        logger.warning("MCS ranking failed: %s", exc)
        return None

    if not isinstance(ranking, MCSRanking):
        logger.warning("MCS ranking returned unexpected type: %s", type(ranking))
        return None

    pr_numbers = {pr.number for pr in prs}
    valid_candidates = [c for c in ranking.candidates if c.pr_number in pr_numbers]

    top_n = config.mcs_top_n
    approved = valid_candidates[:top_n]

    if on_status:
        on_status(f"Labeling top {len(approved)} PR(s) with {MCS_LABEL}...")

    reasons: dict[int, str] = {}
    for candidate in approved:
        reasons[candidate.pr_number] = candidate.reasoning
        try:
            await add_label_to_pr(gh_client, candidate.pr_number, MCS_LABEL)
        except Exception as exc:
            logger.warning("MCS: failed to label PR #%d: %s", candidate.pr_number, exc)

    return MCSResult(
        approved=[c.pr_number for c in approved],
        reasons=reasons,
    )
