"""Q4 — Unconstrained discovery: what does the embedding surface when the
candidate pool isn't restricted by formality?"""
from __future__ import annotations

import random
from typing import List, Tuple

from tqdm import tqdm

from ._shared import EMBEDDING_METRIC, MatchedPools, render_file, render_table

NAME  = "q4"
TITLE = "Q4 — Unconstrained discovery (full pool, sampled)"

_DESCRIPTION = """
For a stratified sample of query statements (some informal, some
formal), find the top-K nearest neighbours in the full sloganed pool —
no formality restriction, self-excluded. Approximates what
`/graph/statement?return=representations` would actually surface in
production.

Nearest-neighbour search runs server-side via the binary-Hamming
HNSW shortlist (`<~>` on `binary_quantize(embedding)::bit(4096)`)
followed by a full-precision cosine rerank — same two-phase pattern
as the production /search endpoint.

Each top result is annotated with the candidate's formality + paper_id
so you can eyeball:

  (a) The known ground-truth partner showing up at rank 1 (sanity check)
  (b) Cross-paper restatements / equivalent results
  (c) Same-formality near-duplicates from another paper
  (d) Noise
""".strip()

SAMPLE_PER_SIDE  = 15        # query statements drawn from each side
TOP_K            = 5         # neighbours per query
SHORTLIST_SIZE   = 200       # ANN candidates before cosine rerank
SLOGAN_PREVIEW   = 90        # chars before truncating in the table

_NN_SQL = """
WITH q AS (
    SELECT e.embedding AS vec
    FROM embedding e
    JOIN slogan sl ON sl.slogan_id = e.slogan_id
    WHERE sl.statement_id = %(qid)s::uuid
      AND e.model_name    = %(model)s
      AND NOT sl.insufficient_context
    ORDER BY sl.created_at
    LIMIT 1
),
ann AS (
    SELECT e.slogan_id, e.embedding
    FROM embedding e
    WHERE e.model_name = %(model)s
    ORDER BY binary_quantize(e.embedding)::bit(4096)
         <~> binary_quantize((SELECT vec FROM q))::bit(4096)
    LIMIT %(shortlist)s
)
SELECT st.statement_id, st.paper_id, st.formality, sl.slogan,
       (1.0 - (a.embedding <=> (SELECT vec FROM q)))::float AS similarity
FROM ann a
JOIN slogan sl    ON sl.slogan_id    = a.slogan_id
JOIN statement st ON st.statement_id = sl.statement_id
WHERE st.statement_id != %(qid)s::uuid
  AND NOT sl.insufficient_context
ORDER BY similarity DESC
LIMIT %(k)s;
"""


def _truncate(s: str, n: int) -> str:
    s = (s or "").replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _neighbours(cur, qid: str, model: str, k: int) -> List[Tuple]:
    cur.execute(_NN_SQL, {
        "qid": qid, "model": model, "k": k, "shortlist": SHORTLIST_SIZE,
    })
    return cur.fetchall()


def run(pools: MatchedPools, conn, embedding_model: str, rng_seed: int = 0) -> str:
    rng = random.Random(rng_seed)

    n_inf = min(SAMPLE_PER_SIDE, len(pools.informal))
    n_fml = min(SAMPLE_PER_SIDE, len(pools.formal))
    inf_sample = rng.sample(pools.informal, n_inf)
    fml_sample = rng.sample(pools.formal,   n_fml)

    headers = ("query_id", "query_formality", "rank",
               "neighbour_id", "neigh_formality", "neigh_paper_id",
               "similarity", "slogan_preview")

    def _rows_for(queries, query_formality: str):
        rows = []
        try:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL hnsw.ef_search = %s;",
                            (max(80, SHORTLIST_SIZE * 4),))
                cur.execute("SET LOCAL hnsw.iterative_scan = 'relaxed_order';")
                for q in tqdm(queries, leave=False, unit="query",
                              desc=f"      {query_formality}"):
                    results = _neighbours(cur, q.statement_id, embedding_model, TOP_K)
                    if not results:
                        rows.append((q.statement_id[:8], query_formality,
                                     "-", "-", "-", "-", 0.0, "(no embedding)"))
                        continue
                    for rank, (nid, pid, formality, slogan, sim) in enumerate(results, 1):
                        rows.append((
                            q.statement_id[:8], query_formality, rank,
                            str(nid)[:8], formality, str(pid)[:8],
                            float(sim), _truncate(slogan, SLOGAN_PREVIEW),
                        ))
                    # blank row between queries for readability
                    rows.append(("", "", "", "", "", "", "", ""))
        finally:
            # SET LOCAL is scoped to the transaction; rollback discards the
            # GUCs so they don't leak into later queries.
            conn.rollback()
        return rows

    inf_table = render_table(headers, _rows_for(inf_sample, "informal"))
    fml_table = render_table(headers, _rows_for(fml_sample, "formal"))

    sample_note = (
        f"Sampled {n_inf} informal + {n_fml} formal queries (seed={rng_seed}); "
        f"top-{TOP_K} neighbours each."
    )
    return render_file(
        TITLE, _DESCRIPTION + "\n\n" + sample_note,
        [
            ("Informal queries → top neighbours across the full pool", inf_table),
            ("Formal queries → top neighbours across the full pool",  fml_table),
        ],
    )
