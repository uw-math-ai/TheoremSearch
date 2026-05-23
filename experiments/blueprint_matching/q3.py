"""Q3 — Bidirectional agreement: where do I → F and F → I disagree, and can
basic NLP methods break the tie?"""
from __future__ import annotations

from typing import Dict, List

import numpy as np

from ._shared import (
    EMBEDDING_METRIC, MatchedPools, TEXT_METRICS,
    render_file, render_table, top1_indices,
)

NAME  = "q3"
TITLE = "Q3 — Bidirectional agreement and method consensus"

_DESCRIPTION = """
For each ground-truth (informal I, formal F) pair, take each method's
top-1 in both directions:

    pred_F_for_I = argmax over formals       of sim[I, :]
    pred_I_for_F = argmax over informals     of sim[:, F]

…and classify the pair into one of four buckets:

    both_correct   pred_F_for_I = F  and  pred_I_for_F = I
    if_only        only I → F gets the right partner
    fi_only        only F → I gets the right partner
    neither        both directions miss

The first table shows the partition counts per method. High both_correct
share means the method is confident and bidirectionally consistent.

The second table digs into the embedding's one-way cases: for the
embedding's `if_only` pairs (I → F got it right, F → I didn't), do the
text/IR methods recover the correct informal in the F → I direction?
And conversely for `fi_only`. This tests whether simpler methods can
serve as a tie-breaker / confidence signal where the embedding is
asymmetric.
""".strip()


def _bucket_pairs(
    sim: np.ndarray,
    pools: MatchedPools,
) -> Dict[str, List[int]]:
    """Bucket each ground-truth pair (by its index in pools.truth, ordered)
    into one of the four direction-agreement categories.

    Returns {bucket_name: list of (informal_id, formal_id) tuples}.
    """
    informal_idx = {sid: i for i, sid in enumerate(pools.informal_ids)}
    formal_idx   = {sid: j for j, sid in enumerate(pools.formal_ids)}

    # Gold sets per side (for many-to-many tolerance).
    gold_F: Dict[int, set] = {i: set() for i in range(len(pools.informal_ids))}
    gold_I: Dict[int, set] = {j: set() for j in range(len(pools.formal_ids))}
    for a, b in pools.truth:
        if a in informal_idx and b in formal_idx:
            gold_F[informal_idx[a]].add(formal_idx[b])
            gold_I[formal_idx[b]].add(informal_idx[a])

    top1_F = top1_indices(sim)        # for each informal i: best formal j
    top1_I = top1_indices(sim.T)      # for each formal j:   best informal i

    buckets = {"both_correct": [], "if_only": [], "fi_only": [], "neither": []}
    for a, b in pools.truth:
        if a not in informal_idx or b not in formal_idx:
            continue
        i, j = informal_idx[a], formal_idx[b]
        if_correct = top1_F[i] in gold_F[i]
        fi_correct = top1_I[j] in gold_I[j]
        if if_correct and fi_correct:
            key = "both_correct"
        elif if_correct:
            key = "if_only"
        elif fi_correct:
            key = "fi_only"
        else:
            key = "neither"
        buckets[key].append((a, b))
    return buckets


def _partition_table(pools: MatchedPools) -> str:
    method_order = [name for name, _ in TEXT_METRICS] + [EMBEDDING_METRIC]
    headers = ("method", "both_correct", "if_only", "fi_only", "neither",
               "total", "both_pct")
    rows = []
    for name in method_order:
        b = _bucket_pairs(pools.sims[name], pools)
        total = sum(len(v) for v in b.values())
        pct = (len(b["both_correct"]) / total) if total else 0.0
        rows.append((name, len(b["both_correct"]), len(b["if_only"]),
                     len(b["fi_only"]), len(b["neither"]), total, pct))
    rows.sort(key=lambda r: -r[1])
    return render_table(headers, rows)


def _consensus_table(pools: MatchedPools) -> str:
    """For embedding-side `if_only` and `fi_only` pairs, what fraction does
    each text/IR method recover in the *failing* direction?"""
    informal_idx = {sid: i for i, sid in enumerate(pools.informal_ids)}
    formal_idx   = {sid: j for j, sid in enumerate(pools.formal_ids)}
    gold_F: Dict[int, set] = {i: set() for i in range(len(pools.informal_ids))}
    gold_I: Dict[int, set] = {j: set() for j in range(len(pools.formal_ids))}
    for a, b in pools.truth:
        if a in informal_idx and b in formal_idx:
            gold_F[informal_idx[a]].add(formal_idx[b])
            gold_I[formal_idx[b]].add(informal_idx[a])

    emb_buckets = _bucket_pairs(pools.sims[EMBEDDING_METRIC], pools)
    if_only_idx = [(informal_idx[a], formal_idx[b]) for a, b in emb_buckets["if_only"]]
    fi_only_idx = [(informal_idx[a], formal_idx[b]) for a, b in emb_buckets["fi_only"]]

    headers = ("method", "if_only_pool", "rescued_fi",
               "fi_only_pool", "rescued_if")
    rows = []
    for name, _ in TEXT_METRICS:
        sim = pools.sims[name]
        top1_F = top1_indices(sim)
        top1_I = top1_indices(sim.T)
        # if_only: embedding's F→I failed. Can this text method's F→I find I?
        rescued_fi = sum(1 for (i, j) in if_only_idx if top1_I[j] in gold_I[j])
        # fi_only: embedding's I→F failed. Can this text method's I→F find F?
        rescued_if = sum(1 for (i, j) in fi_only_idx if top1_F[i] in gold_F[i])
        rows.append((name, len(if_only_idx), rescued_fi,
                     len(fi_only_idx), rescued_if))
    rows.sort(key=lambda r: -(r[2] + r[4]))
    return render_table(headers, rows)


def run(pools: MatchedPools) -> str:
    return render_file(
        TITLE, _DESCRIPTION,
        [
            ("Direction-agreement partition per method", _partition_table(pools)),
            ("Can text methods rescue the embedding's failing direction?",
             _consensus_table(pools)),
        ],
    )
