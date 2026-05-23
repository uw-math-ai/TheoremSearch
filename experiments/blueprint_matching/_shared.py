"""Shared utilities for the blueprint-matching experiment.

Centralises the metric registry, similarity computation, scoring, and ASCII
table formatting so each question module stays focused on its analysis.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Sequence, Set, Tuple

import numpy as np
from tqdm import tqdm

from experiments.formal_graph.blueprint_matching import metrics

from .data import FormalStmt, InformalStmt


MetricFn = Callable[[List[str], List[str]], np.ndarray]

# Text/IR baselines, in the order we want them displayed.
# difflib_ratio dropped: pure-Python O(N*M) per pair was the hang on 2M-pair
# pools, and it's redundant with edit_norm.
TEXT_METRICS: List[Tuple[str, MetricFn]] = [
    ("edit_norm",       metrics.edit_norm),
    ("jaccard_tokens",  metrics.jaccard_tokens),
    ("char_3gram",      lambda a, b: metrics.char_ngram_jaccard(a, b, 3)),
    ("char_4gram",      lambda a, b: metrics.char_ngram_jaccard(a, b, 4)),
    ("tfidf_cosine",    metrics.tfidf_cosine),
    ("bm25",            metrics.bm25),
]

EMBEDDING_METRIC = "db_embedding_cos"


# ── Similarity computation ─────────────────────────────────────────────── #

@dataclass
class MatchedPools:
    """Ground-truth-matched subsets of the informal and formal pools,
    aligned with their similarity matrices."""
    informal:      List[InformalStmt]
    formal:        List[FormalStmt]
    informal_ids:  List[str]
    formal_ids:    List[str]
    truth:         Set[Tuple[str, str]]
    # Per-method I×F similarity matrices. F→I is just .T.
    sims:          Dict[str, np.ndarray]


def _embedding_similarities(
    conn,
    informal_ids: List[str],
    formal_ids:   List[str],
    embedding_model: str,
    shortlist_size: int = 500,
) -> np.ndarray:
    """Two-phase ANN per informal: binary-Hamming HNSW shortlist over the
    formal pool, full-precision cosine rerank. Mirrors the production
    /search pattern in api/routes/search.py — entirely server-side, so no
    embeddings are shipped to the client.

    Entries outside each row's shortlist remain 0; oversample ``shortlist_size``
    if downstream metrics care about deeper ranks.
    """
    n, m = len(informal_ids), len(formal_ids)
    sim = np.zeros((n, m), dtype=np.float32)
    formal_pos = {str(sid): j for j, sid in enumerate(formal_ids)}
    pool_pg = [str(s) for s in formal_ids]

    sql = """
    WITH q AS (
        SELECT embedding AS vec
          FROM embedding
         WHERE slogan_id = %(qid)s::uuid
           AND model_name = %(model)s
    )
    SELECT e.slogan_id::text,
           (1.0 - (e.embedding <=> (SELECT vec FROM q)))::float AS sim
      FROM embedding e
     WHERE e.model_name = %(model)s
       AND e.slogan_id = ANY(%(pool)s::uuid[])
     ORDER BY binary_quantize(e.embedding)::bit(4096)
          <~> binary_quantize((SELECT vec FROM q))::bit(4096)
     LIMIT %(k)s
    """

    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL hnsw.ef_search = %s;", (max(80, shortlist_size * 4),))
            cur.execute("SET LOCAL hnsw.iterative_scan = 'relaxed_order';")
            for i, qid in enumerate(tqdm(
                informal_ids, leave=False, unit="query", desc="      shortlist+rerank",
            )):
                cur.execute(sql, {
                    "qid":   str(qid),
                    "model": embedding_model,
                    "pool":  pool_pg,
                    "k":     shortlist_size,
                })
                for sid, s in cur.fetchall():
                    j = formal_pos.get(sid)
                    if j is not None:
                        sim[i, j] = float(s)
    finally:
        # End the transaction so SET LOCAL is discarded — otherwise the GUCs
        # leak into the next caller's queries (Q4's plain-vector ORDER BY
        # tripped "unrecognized BufferAccessStrategyType: 0" until we did this).
        conn.rollback()
    return sim


def compute_similarities(
    informal: List[InformalStmt],
    formal:   List[FormalStmt],
    conn,
    embedding_model: str,
) -> Dict[str, np.ndarray]:
    """Run every registered metric on the (informal, formal) cross-product.

    Returns ``{method_name: ndarray of shape (len(informal), len(formal))}``.
    The embedding metric uses the same two-phase ANN pattern as the API.
    """
    out: Dict[str, np.ndarray] = {}
    inf_texts = [s.slogan for s in informal]
    fml_texts = [s.slogan for s in formal]
    inf_sl_ids = [s.slogan_id for s in informal]
    fml_sl_ids = [s.slogan_id for s in formal]

    steps: List[Tuple[str, Callable[[], np.ndarray]]] = [
        *((name, (lambda fn=fn: fn(inf_texts, fml_texts))) for name, fn in TEXT_METRICS),
        (EMBEDDING_METRIC, lambda: _embedding_similarities(
            conn, inf_sl_ids, fml_sl_ids, embedding_model,
        )),
    ]

    total = len(steps)
    for i, (name, runner) in enumerate(steps, start=1):
        print(f"  [{i}/{total}] {name}...", flush=True)
        t0 = time.perf_counter()
        out[name] = runner()
        print(f"  [{i}/{total}] {name} done in {time.perf_counter() - t0:.1f}s",
              flush=True)
    return out


# ── Scoring ────────────────────────────────────────────────────────────── #

def score(
    sim: np.ndarray,
    a_ids: Sequence[str],
    b_ids: Sequence[str],
    truth_a_to_b: Set[Tuple[str, str]],
) -> Dict[str, float]:
    """Rank-based metrics for a single direction.

    ``sim[i, j]`` is the similarity between ``a_ids[i]`` and ``b_ids[j]``.
    ``truth_a_to_b`` is the set of correct ``(a_id, b_id)`` pairs in this
    direction. Items with no ground-truth target in the candidate pool are
    excluded from the denominator.

    Returns top-1 / top-5 / top-10 / MRR plus the gap (mean true similarity
    − mean false similarity), useful for thresholding analysis.
    """
    n, m = sim.shape
    a_idx = {aid: i for i, aid in enumerate(a_ids)}
    b_idx = {bid: j for j, bid in enumerate(b_ids)}

    truth_mask = np.zeros((n, m), dtype=bool)
    for a, b in truth_a_to_b:
        i = a_idx.get(a)
        j = b_idx.get(b)
        if i is not None and j is not None:
            truth_mask[i, j] = True

    has_gold = truth_mask.any(axis=1)
    evaluated = int(has_gold.sum())
    if evaluated == 0:
        return {
            "evaluated": 0, "top1": 0.0, "top5": 0.0, "top10": 0.0,
            "mrr": 0.0, "mean_true": 0.0, "mean_false": 0.0, "gap": 0.0,
        }

    sim_e   = sim[has_gold]                            # (E, m)
    truth_e = truth_mask[has_gold]                     # (E, m)
    order   = np.argsort(-sim_e, axis=1)               # (E, m) descending
    # argmax returns the position of the first True per row → best gold rank.
    best_rank = np.take_along_axis(truth_e, order, axis=1).argmax(axis=1) + 1

    top1  = float((best_rank <= 1).mean())
    top5  = float((best_rank <= 5).mean())
    top10 = float((best_rank <= 10).mean())
    mrr   = float((1.0 / best_rank).mean())

    true_scores  = sim_e[truth_e]
    false_scores = sim_e[~truth_e]
    mean_t = float(true_scores.mean())  if true_scores.size  else 0.0
    mean_f = float(false_scores.mean()) if false_scores.size else 0.0
    return {
        "evaluated":  evaluated,
        "top1":       top1,
        "top5":       top5,
        "top10":      top10,
        "mrr":        mrr,
        "mean_true":  mean_t,
        "mean_false": mean_f,
        "gap":        mean_t - mean_f,
    }


def top1_indices(sim: np.ndarray) -> np.ndarray:
    """Per-row argmax (top-1 column). For ties, picks the lowest index."""
    return np.argmax(sim, axis=1)


# ── Output formatting ──────────────────────────────────────────────────── #

def fmt(v) -> str:
    if isinstance(v, float):
        if v == 0:
            return "0.000"
        if abs(v) < 10:
            return f"{v:+.3f}" if v < 0 else f"{v:.3f}"
        return f"{v:.3f}"
    return str(v)


def render_table(headers: Sequence[str], rows: Sequence[Sequence]) -> str:
    """Plain ASCII table, two-space column gutters, header underline."""
    cells = [[h] for h in headers]
    for r in rows:
        for i, v in enumerate(r):
            cells[i].append(fmt(v))
    widths = [max(len(c) for c in col) for col in cells]
    gut = "  "
    lines = [
        gut.join(h.ljust(widths[i]) for i, h in enumerate(headers)),
        gut.join("-" * widths[i] for i in range(len(headers))),
    ]
    for r in rows:
        lines.append(gut.join(fmt(v).ljust(widths[i]) for i, v in enumerate(r)))
    return "\n".join(lines)


def render_file(title: str, description: str, sections: List[Tuple[str, str]]) -> str:
    """Assemble the final file body: banner, description, then each
    (subheading, body) section."""
    rule = "=" * 72
    parts = [
        rule,
        title,
        rule,
        "",
        description.strip(),
        "",
    ]
    for heading, body in sections:
        parts.append("")
        parts.append(heading)
        parts.append("-" * len(heading))
        parts.append(body)
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"
