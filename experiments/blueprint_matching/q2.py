"""Q2 — Method comparison: does embedding cosine beat basic NLP baselines?"""
from __future__ import annotations

from typing import Set, Tuple

from ._shared import (
    EMBEDDING_METRIC, MatchedPools, TEXT_METRICS,
    render_file, render_table, score,
)

NAME  = "q2"
TITLE = "Q2 — Method comparison across baselines and embeddings"

_DESCRIPTION = """
Same evaluation as Q1, but expanded across the full method suite:

  - String/token:  edit_norm, jaccard_tokens, char_3gram, char_4gram,
                   difflib_ratio
  - IR:            tfidf_cosine, bm25
  - Embedding:     db_embedding_cos (qwen3-8b slogan embeddings)

For each method and direction, we report top-1 / top-5 / top-10 / MRR
plus the **gap** — the mean similarity on true pairs minus the mean on
false pairs. The gap matters because it tells you whether a method's
scores actually separate matches from non-matches in absolute terms —
the prerequisite for threshold-based use downstream (e.g. the
`/graph/statement?return=representations` cutoff).
""".strip()


def _flip(truth: Set[Tuple[str, str]]) -> Set[Tuple[str, str]]:
    return {(b, a) for a, b in truth}


def _format_direction(pools: MatchedPools, direction: str) -> str:
    headers = ("method", "evaluated", "top1", "top5", "top10",
               "mrr", "mean_true", "mean_false", "gap")
    rows = []
    method_order = [name for name, _ in TEXT_METRICS] + [EMBEDDING_METRIC]
    for name in method_order:
        sim = pools.sims[name]
        if direction == "i->f":
            s = score(sim, pools.informal_ids, pools.formal_ids, pools.truth)
        else:
            s = score(sim.T, pools.formal_ids, pools.informal_ids, _flip(pools.truth))
        rows.append((name, s["evaluated"], s["top1"], s["top5"], s["top10"],
                     s["mrr"], s["mean_true"], s["mean_false"], s["gap"]))
    # Re-sort each table by top-1 desc so the best method floats up.
    rows.sort(key=lambda r: (-r[2], -r[5]))
    return render_table(headers, rows)


def run(pools: MatchedPools) -> str:
    return render_file(
        TITLE, _DESCRIPTION,
        [
            ("informal → formal", _format_direction(pools, "i->f")),
            ("formal → informal", _format_direction(pools, "f->i")),
        ],
    )
