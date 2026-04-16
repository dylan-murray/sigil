import logging
import pytest
from sigil.core.llm import BudgetExceededError
from sigil.pipeline.tokens import TokenBudgetManager, enforce_token_budget


def test_enforce_token_budget_happy_path():
    # Should not raise or log warning
    enforce_token_budget(100, 1000)


def test_enforce_token_budget_warning(caplog):
    with caplog.at_level(logging.WARNING):
        enforce_token_budget(850, 1000)
    assert "Token budget warning" in caplog.text
    assert "85.0%" in caplog.text


def test_enforce_token_budget_error():
    with pytest.raises(BudgetExceededError) as excinfo:
        enforce_token_budget(1100, 1000)
    assert "Token budget exceeded" in str(excinfo.value)


def test_token_budget_manager_global_enforcement():
    manager = TokenBudgetManager(global_limit=1000)

    # Happy path
    manager.enforce_global_budget(500)

    # Warning path (logs to logger, but we just check it doesn't raise)
    manager.enforce_global_budget(850)

    # Error path
    with pytest.raises(BudgetExceededError):
        manager.enforce_global_budget(1100)


def test_token_budget_manager_stage_tracking():
    manager = TokenBudgetManager(global_limit=10000)

    # Start stage at 1000 tokens
    manager.mark_stage_start(1000)

    # Current usage is 1500, so stage usage is 500
    assert manager.get_stage_usage(1500) == 500

    # Enforce stage budget of 1000
    manager.enforce_stage_budget(1800, 1000)  # 800 used, ok

    # Exceed stage budget
    with pytest.raises(BudgetExceededError):
        manager.enforce_stage_budget(2100, 1000)  # 1100 used, fail
