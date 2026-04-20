import logging
from sigil.core.llm import BudgetExceededError

logger = logging.getLogger(__name__)


def enforce_token_budget(current_usage: int, limit: int) -> None:
    """
    Compares current token usage against a limit.
    Raises BudgetExceededError if the limit is exceeded.
    Logs a warning if usage exceeds 80% of the limit.
    """
    if current_usage > limit:
        raise BudgetExceededError(f"Token budget exceeded: {current_usage:,} > {limit:,} tokens")

    if current_usage > limit * 0.8:
        logger.warning(
            "Token budget warning: usage is at %.1f%% (%d / %d)",
            (current_usage / limit) * 100,
            current_usage,
            limit,
        )


class TokenBudgetManager:
    """
    Tracks token usage at the start of pipeline stages and enforces
    both global and stage-specific limits.
    """

    def __init__(self, global_limit: int):
        self.global_limit = global_limit
        self.stage_start_usage: int = 0

    def mark_stage_start(self, current_usage: int) -> None:
        """Records the token usage at the beginning of a stage."""
        self.stage_start_usage = current_usage

    def enforce_global_budget(self, current_usage: int) -> None:
        """Enforces the global token budget."""
        enforce_token_budget(current_usage, self.global_limit)

    def get_stage_usage(self, current_usage: int) -> int:
        """Calculates tokens used within the current stage."""
        return current_usage - self.stage_start_usage

    def enforce_stage_budget(self, current_usage: int, stage_limit: int) -> None:
        """Enforces a token budget for the current stage."""
        stage_usage = self.get_stage_usage(current_usage)
        enforce_token_budget(stage_usage, stage_limit)
