import math
import re
from dataclasses import dataclass, field

BM25_K1 = 1.5
BM25_B = 0.75
TITLE_WEIGHT = 0.3
BODY_WEIGHT = 0.7

STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "if",
        "then",
        "else",
        "for",
        "to",
        "of",
        "in",
        "on",
        "at",
        "by",
        "with",
        "from",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "they",
        "them",
        "their",
        "we",
        "us",
        "our",
        "you",
        "your",
        "i",
        "me",
        "my",
        "do",
        "does",
        "did",
        "have",
        "has",
        "had",
        "will",
        "would",
        "should",
        "could",
        "can",
        "may",
        "might",
        "must",
        "not",
        "no",
        "nor",
        "so",
        "than",
        "too",
        "very",
        "just",
    }
)

DEFAULT_SYNONYMS: dict[str, str] = {
    "saboteur": "adversarial",
    "sabotage": "adversarial",
    "chaos": "adversarial",
    "redteam": "adversarial",
    "attack": "adversarial",
    "attacker": "adversarial",
    "drift": "drift",
    "stale": "drift",
    "outdated": "drift",
    "obsolete": "drift",
    "budget": "cost",
    "spend": "cost",
    "spending": "cost",
    "token": "cost",
    "tokens": "cost",
    "price": "cost",
    "pricing": "cost",
    "duplicate": "dedup",
    "duplicates": "dedup",
    "dedupe": "dedup",
    "deduplicate": "dedup",
    "deduplication": "dedup",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_MIN_TOKEN_LEN = 2


def tokenize(text: str) -> list[str]:
    if not text:
        return []
    out: list[str] = []
    for tok in _TOKEN_RE.findall(text.lower()):
        if len(tok) < _MIN_TOKEN_LEN or tok in STOPWORDS:
            continue
        out.append(DEFAULT_SYNONYMS.get(tok, tok))
    return out


def _term_freq(tokens: list[str]) -> dict[str, int]:
    tf: dict[str, int] = {}
    for t in tokens:
        tf[t] = tf.get(t, 0) + 1
    return tf


@dataclass(frozen=True)
class CorpusStats:
    n_docs: int
    df: dict[str, int] = field(default_factory=dict)
    idf: dict[str, float] = field(default_factory=dict)
    avg_dl: float = 0.0


def build_corpus_stats(docs_tokens: list[list[str]]) -> CorpusStats:
    n_docs = len(docs_tokens)
    if n_docs == 0:
        return CorpusStats(n_docs=0)
    df: dict[str, int] = {}
    total_len = 0
    for toks in docs_tokens:
        total_len += len(toks)
        for term in set(toks):
            df[term] = df.get(term, 0) + 1
    avg_dl = total_len / n_docs if n_docs else 0.0
    idf: dict[str, float] = {}
    for term, freq in df.items():
        idf[term] = math.log(((n_docs - freq + 0.5) / (freq + 0.5)) + 1.0)
    return CorpusStats(n_docs=n_docs, df=df, idf=idf, avg_dl=avg_dl)


def _bm25_raw(
    q_tokens: list[str],
    d_tokens: list[str],
    stats: CorpusStats,
    *,
    k1: float = BM25_K1,
    b: float = BM25_B,
) -> float:
    if not q_tokens or not d_tokens or stats.n_docs == 0:
        return 0.0
    d_len = len(d_tokens)
    d_tf = _term_freq(d_tokens)
    denom_norm = 1.0 - b + b * (d_len / stats.avg_dl if stats.avg_dl else 1.0)
    score = 0.0
    for term in set(q_tokens):
        tf = d_tf.get(term, 0)
        if tf == 0:
            continue
        idf = stats.idf.get(term, 0.0)
        score += idf * (tf * (k1 + 1.0)) / (tf + k1 * denom_norm)
    return score


def bm25_score(
    q_tokens: list[str],
    d_tokens: list[str],
    stats: CorpusStats,
) -> float:
    if not q_tokens or not d_tokens:
        return 0.0
    raw = _bm25_raw(q_tokens, d_tokens, stats)
    self_raw = _bm25_raw(q_tokens, q_tokens, stats)
    if self_raw <= 0.0:
        return 0.0
    return max(0.0, min(1.0, raw / self_raw))


def tfidf_cosine(
    a_tokens: list[str],
    b_tokens: list[str],
    stats: CorpusStats,
) -> float:
    if not a_tokens or not b_tokens or stats.n_docs == 0:
        return 0.0

    def _vec(tokens: list[str]) -> dict[str, float]:
        return {t: count * stats.idf.get(t, 0.0) for t, count in _term_freq(tokens).items()}

    a_vec = _vec(a_tokens)
    b_vec = _vec(b_tokens)
    dot = sum(a_vec[t] * b_vec[t] for t in a_vec.keys() & b_vec.keys())
    a_norm = math.sqrt(sum(v * v for v in a_vec.values()))
    b_norm = math.sqrt(sum(v * v for v in b_vec.values()))
    if a_norm == 0.0 or b_norm == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (a_norm * b_norm)))


def _field_agreement(
    a_tokens: list[str],
    b_tokens: list[str],
    stats: CorpusStats,
) -> float:
    if not a_tokens or not b_tokens:
        return 0.0
    return min(bm25_score(a_tokens, b_tokens, stats), tfidf_cosine(a_tokens, b_tokens, stats))


def similarity(
    a_title: str,
    a_body: str,
    b_title: str,
    b_body: str,
    *,
    title_stats: CorpusStats,
    body_stats: CorpusStats,
) -> float:
    title_agree = _field_agreement(tokenize(a_title), tokenize(b_title), title_stats)
    body_agree = _field_agreement(tokenize(a_body), tokenize(b_body), body_stats)
    return TITLE_WEIGHT * title_agree + BODY_WEIGHT * body_agree


def top_k_similar(
    candidate: tuple[str, str],
    existing: list[tuple[str, str]],
    *,
    k: int = 3,
) -> list[tuple[int, float]]:
    if not existing or k <= 0:
        return []
    all_docs = [candidate] + list(existing)
    title_tokens = [tokenize(t) for (t, _) in all_docs]
    body_tokens = [tokenize(b) for (_, b) in all_docs]
    title_stats = build_corpus_stats(title_tokens)
    body_stats = build_corpus_stats(body_tokens)
    cand_title_toks = title_tokens[0]
    cand_body_toks = body_tokens[0]
    scored: list[tuple[int, float]] = []
    for i in range(len(existing)):
        title_agree = _field_agreement(cand_title_toks, title_tokens[i + 1], title_stats)
        body_agree = _field_agreement(cand_body_toks, body_tokens[i + 1], body_stats)
        scored.append((i, TITLE_WEIGHT * title_agree + BODY_WEIGHT * body_agree))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:k]
