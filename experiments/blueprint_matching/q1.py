"""Q1 — Directional recovery: can the slogan embedding retrieve the known
partner from the other side?"""
from __future__ import annotations

from typing import Set, Tuple

from ._shared import (
    EMBEDDING_METRIC, MatchedPools, render_file, render_table, score,
)

NAME  = "q1"
TITLE = "Q1 — Directional recovery (embedding only)"

_DESCRIPTION = """
For each ground-truth (informal, formal) pair derived from
`informal_metadata.lean`, we rank the candidate pool by slogan-embedding
cosine similarity and ask where the correct partner lands.

  informal → formal : for each informal, rank every formal in the matched
                      pool. Best-rank metrics over the gold formals.
  formal → informal : the mirror direction. Same ground-truth pairs, but
                      now we rank informals from each formal's perspective.

This isolates the asymmetry between sides: formal slogans tend to be
terser than their informal counterparts, so we'd expect formal → informal
to be the harder direction.
""".strip()


def _flip(truth: Set[Tuple[str, str]]) -> Set[Tuple[str, str]]:
    return {(b, a) for a, b in truth}


def run(pools: MatchedPools) -> str:
    sim = pools.sims[EMBEDDING_METRIC]
    s_if = score(sim,   pools.informal_ids, pools.formal_ids,   pools.truth)
    s_fi = score(sim.T, pools.formal_ids,   pools.informal_ids, _flip(pools.truth))

    headers = ("direction", "evaluated", "top1", "top5", "top10",
               "mrr", "mean_true", "mean_false", "gap")
    rows = [
        ("informal → formal", s_if["evaluated"], s_if["top1"], s_if["top5"], s_if["top10"],
         s_if["mrr"], s_if["mean_true"], s_if["mean_false"], s_if["gap"]),
        ("formal → informal", s_fi["evaluated"], s_fi["top1"], s_fi["top5"], s_fi["top10"],
         s_fi["mrr"], s_fi["mean_true"], s_fi["mean_false"], s_fi["gap"]),
    ]
    table = render_table(headers, rows)
    return render_file(
        TITLE, _DESCRIPTION,
        [(f"Embedding ({EMBEDDING_METRIC})", table)],
    )
