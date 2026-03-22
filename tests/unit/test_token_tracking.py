from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sigil.cli import _format_cost, _format_ticker
from sigil.llm import TokenUsage, acompletion, get_usage_snapshot, reset_usage


@pytest.fixture(autouse=True)
def _clean_usage():
    reset_usage()
    yield
    reset_usage()


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr("sigil.llm.INITIAL_DELAY", 0.0)


@pytest.mark.parametrize(
    "model,prompt_tok,completion_tok,expected_cost",
    [
        ("anthropic/claude-sonnet-4-6", 1_000_000, 100_000, 3.00 + 1.50),
        ("anthropic/claude-opus-4-6", 500_000, 50_000, 7.50 + 3.75),
        ("anthropic/claude-haiku-4-5", 2_000_000, 500_000, 1.60 + 2.00),
    ],
    ids=["sonnet", "opus", "haiku"],
)
def test_cost_calculation(model, prompt_tok, completion_tok, expected_cost):
    usage = TokenUsage()
    usage.record(model, prompt_tok, completion_tok)
    assert usage.prompt_tokens == prompt_tok
    assert usage.completion_tokens == completion_tok
    assert usage.calls == 1
    assert usage.cost_usd == pytest.approx(expected_cost)


def test_record_per_model_breakdown():
    usage = TokenUsage()
    usage.record("anthropic/claude-sonnet-4-6", 100, 50)
    usage.record("anthropic/claude-opus-4-6", 200, 100)
    usage.record("anthropic/claude-sonnet-4-6", 300, 150)

    assert len(usage.by_model) == 2
    sonnet = usage.by_model["anthropic/claude-sonnet-4-6"]
    opus = usage.by_model["anthropic/claude-opus-4-6"]
    assert sonnet.calls == 2
    assert sonnet.prompt_tokens == 400
    assert sonnet.completion_tokens == 200
    assert opus.calls == 1
    assert opus.prompt_tokens == 200
    assert opus.completion_tokens == 100


def test_record_unknown_model_defaults():
    usage = TokenUsage()
    usage.record("some/unknown-model", 1_000_000, 1_000_000)
    expected = (1_000_000 * 3.00 + 1_000_000 * 15.00) / 1_000_000
    assert usage.cost_usd == pytest.approx(expected)


async def test_acompletion_records_usage():
    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 500
    mock_usage.completion_tokens = 200
    mock_response = MagicMock()
    mock_response.usage = mock_usage

    with patch("sigil.llm.litellm.acompletion", new_callable=AsyncMock, return_value=mock_response):
        await acompletion(model="anthropic/claude-sonnet-4-6", messages=[])

    calls, total_tok, cost = get_usage_snapshot()
    assert calls == 1
    assert total_tok == 700
    assert cost == pytest.approx((500 * 3.00 + 200 * 15.00) / 1_000_000)


async def test_acompletion_no_usage_attr():
    mock_response = MagicMock(spec=[])

    with patch("sigil.llm.litellm.acompletion", new_callable=AsyncMock, return_value=mock_response):
        await acompletion(model="anthropic/claude-sonnet-4-6", messages=[])

    calls, total_tok, cost = get_usage_snapshot()
    assert calls == 0
    assert total_tok == 0
    assert cost == 0.0


@pytest.mark.parametrize(
    "cost,expected",
    [
        (0.005, "0.0050"),
        (0.0001, "0.0001"),
        (0.01, "0.01"),
        (1.50, "1.50"),
        (123.456, "123.46"),
    ],
    ids=["sub-cent", "tiny", "threshold", "normal", "large"],
)
def test_format_cost(cost, expected):
    assert _format_cost(cost) == expected


@pytest.mark.parametrize(
    "snapshot,expected_fragment",
    [
        ((5, 500, 0.50), "500 tokens"),
        ((10, 5_500, 1.00), "5.5k tokens"),
        ((20, 42_000, 5.00), "42k tokens"),
    ],
    ids=["under-1k", "1k-to-10k", "over-10k"],
)
def test_format_ticker_ranges(snapshot, expected_fragment):
    result = _format_ticker(snapshot=snapshot)
    assert expected_fragment in result


def test_format_ticker_no_calls():
    assert _format_ticker(snapshot=(0, 0, 0.0)) == ""
