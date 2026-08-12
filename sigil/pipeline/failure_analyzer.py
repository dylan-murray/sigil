import logging
from dataclasses import dataclass
from sigil.core.agent import ToolResult
from sigil.core.config import Config
from sigil.core.llm import acompletion
from sigil.pipeline.models import ExecutionResult, FailureType, WorkItem

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnalysisDecision:
    should_retry: bool
    reasoning: str
    guidance: str = ""


class FailureAnalyzer:
    def __init__(self, config: Config):
        self.config = config
        self.model = config.model_for("engineer")

    def is_retryable_failure(self, result: ExecutionResult) -> bool:
        if result.success:
            return False

        # Retryable: Post-hooks failed, no changes made, or doom loop
        # Non-retryable: Worktree creation, commit, or rebase failures (usually environmental/structural)
        retryable_types = {
            FailureType.POST_HOOK,
            FailureType.NO_CHANGES,
            FailureType.DOOM_LOOP,
        }

        return result.failure_type in retryable_types

    async def analyze_failure(
        self,
        item: WorkItem,
        result: ExecutionResult,
        diff: str,
        prior_attempts: str,
    ) -> AnalysisDecision:
        prompt = (
            "You are a failure analysis agent for Sigil. An attempt to implement a code change failed.\n\n"
            f"Task: {item.implementation_spec or 'No spec provided'}\n"
            f"Failure Type: {result.failure_type}\n"
            f"Failure Reason: {result.failure_reason}\n"
            f"Prior Attempts History:\n{prior_attempts}\n\n"
            f"Git Diff of the failed attempt:\n```\n{diff[:10000]}\n```\n\n"
            "Analyze why this failed and determine if a retry with a modified approach is likely to succeed.\n"
            "If you recommend a retry, provide specific, concrete guidance to append to the implementation spec.\n\n"
            "Respond in the following format:\n"
            "DECISION: [RETRY | DOWNGRADE]\n"
            "REASONING: [Detailed explanation of why it failed and why the new approach should work]\n"
            "GUIDANCE: [Concrete instructions for the engineer agent to follow in the next attempt]"
        )

        try:
            response = await acompletion(
                label="failure_analyzer",
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=1024,
            )
            content = response.choices[0].message.content or ""

            decision = "DOWNGRADE"
            reasoning = "Analysis failed or no content returned."
            guidance = ""

            if "DECISION: RETRY" in content:
                decision = "RETRY"

            # Simple parsing of the structured response
            for part in ["REASONING:", "GUIDANCE:"]:
                if part in content:
                    start = content.find(part) + len(part)
                    end = content.find("\n\n", start) if "\n\n" in content[start:] else len(content)
                    # If there are multiple parts, find the next marker
                    next_marker = -1
                    for other in ["DECISION:", "REASONING:", "GUIDANCE:"]:
                        if other != part:
                            pos = content.find(other, start)
                            if pos != -1 and (next_marker == -1 or pos < next_marker):
                                next_marker = pos

                    if next_marker != -1:
                        end = next_marker

                    val = content[start:end].strip()
                    if part == "REASONING:":
                        reasoning = val
                    elif part == "GUIDANCE:":
                        guidance = val

            return AnalysisDecision(
                should_retry=(decision == "RETRY"),
                reasoning=reasoning,
                guidance=guidance,
            )
        except Exception as exc:
            logger.warning("Failure analysis failed: %s", exc)
            return AnalysisDecision(
                should_retry=False,
                reasoning=f"Analysis error: {exc}",
            )
