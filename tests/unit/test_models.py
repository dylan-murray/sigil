import pytest

from sigil.pipeline.models import BOLDNESS_RANK, boldness_allowed


@pytest.mark.parametrize(
    "item_boldness, current_boldness, expected",
    [
        ("conservative", "conservative", True),
        ("conservative", "balanced", True),
        ("conservative", "bold", True),
        ("conservative", "experimental", True),
        ("balanced", "conservative", False),
        ("balanced", "balanced", True),
        ("balanced", "bold", True),
        ("balanced", "experimental", True),
        ("bold", "conservative", False),
        ("bold", "balanced", False),
        ("bold", "bold", True),
        ("bold", "experimental", True),
        ("experimental", "conservative", False),
        ("experimental", "balanced", False),
        ("experimental", "bold", False),
        ("experimental", "experimental", True),
    ],
)
def test_boldness_allowed_valid_pairs(item_boldness, current_boldness, expected):
    assert boldness_allowed(item_boldness, current_boldness) == expected


def test_boldness_rank_covers_all_levels():
    assert set(BOLDNESS_RANK.keys()) == {"conservative", "balanced", "bold", "experimental"}


def test_boldness_rank_is_monotonically_increasing():
    levels = ["conservative", "balanced", "bold", "experimental"]
    for i in range(len(levels) - 1):
        assert BOLDNESS_RANK[levels[i]] < BOLDNESS_RANK[levels[i + 1]]


@pytest.mark.parametrize(
    "item_boldness, current_boldness",
    [
        ("unknown_level", "bold"),
        ("bold", "unknown_level"),
        ("", "bold"),
    ],
)
def test_boldness_allowed_unknown_defaults_to_balanced(item_boldness, current_boldness):
    result = boldness_allowed(item_boldness, current_boldness)
    assert isinstance(result, bool)
