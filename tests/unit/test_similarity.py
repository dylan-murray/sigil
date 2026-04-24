import math

import pytest

from sigil.state.similarity import (
    bm25_score,
    build_corpus_stats,
    similarity,
    tfidf_cosine,
    tokenize,
    top_k_similar,
)


@pytest.fixture
def fruit_stats():
    return build_corpus_stats([["apple"], ["banana"], ["cherry"]])


def test_tokenize_pipeline():
    assert tokenize("The X-RAY Yy, a CHAOS!") == ["ray", "yy", "adversarial"]


@pytest.mark.parametrize(
    "word, canonical",
    [
        ("saboteur", "adversarial"),
        ("sabotage", "adversarial"),
        ("chaos", "adversarial"),
        ("redteam", "adversarial"),
        ("attack", "adversarial"),
        ("attacker", "adversarial"),
        ("drift", "drift"),
        ("stale", "drift"),
        ("outdated", "drift"),
        ("obsolete", "drift"),
        ("budget", "cost"),
        ("spend", "cost"),
        ("tokens", "cost"),
        ("pricing", "cost"),
        ("dedupe", "dedup"),
        ("deduplication", "dedup"),
        ("widget", "widget"),
    ],
)
def test_tokenize_synonyms(word, canonical):
    assert tokenize(word) == [canonical]


def test_tokenize_empty():
    assert tokenize("") == []


def test_build_corpus_stats_math():
    stats = build_corpus_stats([["a", "b", "c"], ["a", "b"], ["a"]])
    assert stats.n_docs == 3
    assert stats.avg_dl == pytest.approx(2.0)
    assert stats.df == {"a": 3, "b": 2, "c": 1}
    assert stats.idf["a"] == pytest.approx(math.log(8 / 7), rel=1e-6)
    assert stats.idf["b"] == pytest.approx(math.log(8 / 5), rel=1e-6)
    assert stats.idf["c"] == pytest.approx(math.log(8 / 3), rel=1e-6)


@pytest.mark.parametrize(
    "q, d, expected",
    [
        (["apple"], ["apple"], "full"),
        (["apple"], ["banana"], "none"),
        (["apple", "banana"], ["apple"], "partial"),
    ],
    ids=["self", "disjoint", "partial"],
)
def test_bm25_extremes(fruit_stats, q, d, expected):
    score = bm25_score(q, d, fruit_stats)
    if expected == "full":
        assert score == pytest.approx(1.0)
    elif expected == "none":
        assert score == 0.0
    else:
        assert 0.0 < score < 1.0


@pytest.mark.parametrize(
    "a, b, expected",
    [
        (["apple"], ["apple"], "full"),
        (["apple"], ["banana"], "none"),
        (["apple", "banana"], ["apple"], "partial"),
    ],
    ids=["identical", "disjoint", "partial"],
)
def test_tfidf_cosine_extremes(fruit_stats, a, b, expected):
    score = tfidf_cosine(a, b, fruit_stats)
    if expected == "full":
        assert score == pytest.approx(1.0)
    elif expected == "none":
        assert score == 0.0
    else:
        assert 0.0 < score < 1.0


@pytest.mark.parametrize(
    "a_title, a_body, b_title, b_body, expected",
    [
        ("widget shop", "lorem ipsum", "widget shop", "foo bar", 0.3),
        ("apple pie", "widget shop opens", "cherry bowl", "widget shop opens", 0.7),
    ],
    ids=["title-only", "body-only"],
)
def test_similarity_weighted_formula(a_title, a_body, b_title, b_body, expected):
    title_stats = build_corpus_stats([tokenize(a_title), tokenize(b_title)])
    body_stats = build_corpus_stats([tokenize(a_body), tokenize(b_body)])
    score = similarity(
        a_title,
        a_body,
        b_title,
        b_body,
        title_stats=title_stats,
        body_stats=body_stats,
    )
    assert score == pytest.approx(expected, abs=1e-6)


def test_similarity_identical_pair_is_one():
    title = "widget cost dashboard"
    body = "tracks widget cost over time"
    title_stats = build_corpus_stats([tokenize(title), tokenize(title)])
    body_stats = build_corpus_stats([tokenize(body), tokenize(body)])
    score = similarity(title, body, title, body, title_stats=title_stats, body_stats=body_stats)
    assert score == pytest.approx(1.0, abs=1e-6)


@pytest.mark.parametrize(
    "k, expected_indices",
    [
        (1, [1]),
        (2, [1, 2]),
        (3, [1, 2, 0]),
        (5, [1, 2, 0]),
    ],
)
def test_top_k_ordering_and_k(k, expected_indices):
    candidate = ("widget dashboard", "widget usage metrics")
    existing = [
        ("unrelated apple", "cherry banana"),
        ("widget dashboard", "widget usage metrics"),
        ("widget metrics", "metrics dashboard"),
    ]
    result = top_k_similar(candidate, existing, k=k)
    assert [i for i, _ in result] == expected_indices
    scores = [s for _, s in result]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.parametrize(
    "existing, k",
    [
        ([], 3),
        ([("a", "b")], 0),
        ([("a", "b")], -1),
    ],
    ids=["empty-existing", "k-zero", "k-negative"],
)
def test_top_k_empty_inputs(existing, k):
    assert top_k_similar(("query", "body"), existing, k=k) == []
