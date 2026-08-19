"""graph_pack: the informal->formal two-hop retrieval arm.

Implements the spec in experiments/lean_premise_retrieval/INTEGRATION.md ("What
graph_pack does internally"): NL query -> top informal anchors by ANN over the
qwen3-8b embedding corpus -> formalization_candidate_neighborhood.resolved_decls
(formal siblings the informal-dep graph predicts are relevant) -> rank by
anchor_support DESC, best_anchor_sim DESC.

Run the 5-query pilot (INTEGRATION.md prerequisite #3) before trusting coverage:
    python -m experiments.graph_prover.retrieval.graph_pack --pilot
"""
from __future__ import annotations

import sys

from .. import config
from ..provenance import Candidate

# SQL from INTEGRATION.md, lightly adapted: anchors restricted to informal statements
# (informal_metadata join) and the walk returns anchor ids so cross-links are loggable.
GRAPH_PACK_SQL = """
WITH anchor_hits AS (
    SELECT s.statement_id,
           1 - (e.embedding <=> %(q)s::vector) AS sim
    FROM embedding e
    JOIN slogan s ON s.slogan_id = e.slogan_id
    JOIN informal_metadata im ON im.statement_id = s.statement_id
    WHERE e.model_name = %(model)s
    ORDER BY e.embedding <=> %(q)s::vector
    LIMIT %(n_anchors)s
)
SELECT gw.decl_name, gw.best_anchor_sim, gw.anchor_support, gw.anchor_ids
FROM (
    SELECT UNNEST(fcn.resolved_decls) AS decl_name,
           MAX(ah.sim) AS best_anchor_sim,
           COUNT(*) AS anchor_support,
           ARRAY_AGG(DISTINCT ah.statement_id::text) AS anchor_ids
    FROM anchor_hits ah
    JOIN formalization_candidate_neighborhood fcn
      ON fcn.anchor_statement_id = ah.statement_id
    WHERE fcn.status = 'resolved'
    GROUP BY 1
) gw
WHERE gw.decl_name <> ALL(%(forbidden)s::text[])
ORDER BY gw.anchor_support DESC, gw.best_anchor_sim DESC
LIMIT %(k)s
"""


def _vec_literal(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"


def graph_pack(ctx, nl_query: str, k: int = 15,
               exclude_names: set[str] | None = None, n_anchors: int = 10
               ) -> tuple[list[Candidate], list[tuple[str, str]]]:
    """Returns (candidates, cross_links) where cross_links = [(anchor stmt id, decl)]."""
    qvec = ctx.embed_query(nl_query)
    with ctx.conn.cursor() as cur:
        cur.execute(GRAPH_PACK_SQL, {"q": _vec_literal(qvec),
                                     "model": config.EMBED_MODEL,
                                     "n_anchors": n_anchors,
                                     "forbidden": sorted(exclude_names or []),
                                     "k": k})
        rows = cur.fetchall()

    name_to_sid = {}   # best-effort reverse map for statement_id provenance
    for sid, name in ctx.names.items():
        if name and name not in name_to_sid:
            name_to_sid[name] = sid

    cands, links = [], []
    for decl_name, best_sim, support, anchor_ids in rows:
        anchor = anchor_ids[0] if anchor_ids else ""
        cands.append(Candidate(
            statement_id=name_to_sid.get(decl_name, f"decl:{decl_name}"),
            decl_name=decl_name, sig=ctx.sigs.get(decl_name, ""),
            score=float(support) + float(best_sim),
            provenance=f"xform:anchor={anchor}"))
        for a in anchor_ids or []:
            links.append((a, decl_name))
    return cands, links


def _pilot():
    """5-query sanity pilot: eyeball decl sensibility + fcn coverage counts."""
    from .arms import RetrievalContext
    queries = [
        "the composition of two continuous functions is continuous",
        "a martingale bounded in L1 converges almost surely",
        "the fundamental group of the circle is the integers",
        "every finite integral domain is a field",
        "Fatou's lemma for a sequence of nonnegative measurable functions",
    ]
    ctx = RetrievalContext()
    for q in queries:
        cands, links = graph_pack(ctx, q, k=10)
        print(f"\nQUERY: {q}\n  candidates={len(cands)} cross_links={len(links)}")
        for c in cands[:10]:
            print(f"    {c.decl_name}  (score {c.score:.3f}, {c.provenance})")
    print("\nIf most queries return 0 candidates, formalization_candidate_neighborhood "
          "coverage is too thin — fall back to informal_metadata.lean blueprint bridges "
          "(approved plan, risk #2).")


if __name__ == "__main__":
    if "--pilot" in sys.argv:
        _pilot()
