"""Per-query top-K ANN search — the workhorse for every matching runner.

Two-phase pattern identical to api/routes/graph.py::_REPRESENTATIONS_SQL:

  1. binary-quantized HNSW shortlist (Hamming distance on bit(4096))
  2. full-precision cosine rerank over the shortlist

Pool filter is named (resolved via pools.CANDIDATE_FILTERS) so the SQL
fragment is never user-derived. Exclusion is a flag, not interpolated text.

Per-query cost ≈ 200-500ms depending on pool size + ACU level. Streams
results as it goes so a 36k-query sweep doesn't sit in RAM.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, List, Optional, Tuple

from tqdm import tqdm

from .pools import CANDIDATE_FILTERS, Stmt


@dataclass
class TopKResult:
    """One ranked candidate for a query."""
    query_statement_id: str
    rank: int
    candidate_statement_id: str
    candidate_paper_id: str
    similarity: float


# Slogan-model pin: every embedding is keyed by (slogan_id, model_name) so
# we also pin the slogan side to keep top-K results to ≈K distinct statements
# (not K × slogan_variants). Mirrors api/routes/graph.py::_SLOGAN_MODELS.
_SLOGAN_MODELS = ["qwen3-235b"]


def _build_sql(candidate_filter: str, exclusion: str) -> str:
    """Materialize the topk SQL with the candidate filter and exclusion
    inlined. Filter is a named registry value (never user-derived);
    exclusion is one of {'statement','paper'} (validated by caller)."""
    if exclusion == "statement":
        excl_sql = "st.statement_id != %(qid)s::uuid"
    elif exclusion == "paper":
        excl_sql = "st.paper_id != %(qpid)s::uuid"
    else:
        raise ValueError(f"exclusion must be 'statement' or 'paper', got {exclusion!r}")

    return f"""
WITH ann AS (
    SELECT e.slogan_id, e.embedding
      FROM embedding e
      JOIN slogan s ON s.slogan_id = e.slogan_id
     WHERE e.model_name = %(model)s
       AND s.model_name = ANY(%(slogan_models)s)
     ORDER BY
        binary_quantize(e.embedding)::bit(4096)
        <~>
        binary_quantize(%(q)s::vector(4096))::bit(4096)
     LIMIT %(ann_k)s
),
ranked AS (
    SELECT
        st.statement_id::text  AS statement_id,
        st.paper_id::text      AS paper_id,
        1.0 - (ann.embedding <=> %(q)s::vector(4096)) AS similarity
      FROM ann
      JOIN slogan s     ON s.slogan_id     = ann.slogan_id
      JOIN statement st ON st.statement_id = s.statement_id
      JOIN paper p      ON p.paper_id      = st.paper_id
     WHERE NOT s.insufficient_context
       AND {excl_sql}
       AND ({candidate_filter})
),
deduped AS (
    SELECT DISTINCT ON (statement_id)
        statement_id, paper_id, similarity
      FROM ranked
     ORDER BY statement_id, similarity DESC
)
SELECT statement_id, paper_id, similarity
  FROM deduped
 ORDER BY similarity DESC
 LIMIT %(k)s;
"""


_FETCH_QUERY_VEC_SQL = """
SELECT e.embedding
  FROM embedding e
  JOIN slogan s ON s.slogan_id = e.slogan_id
 WHERE s.slogan_id = %s::uuid
   AND e.model_name = %s
   AND NOT s.insufficient_context
 LIMIT 1
"""


def embedding_topk(
    conn,
    queries: List[Stmt],
    candidate_pool: str,
    *,
    k: int = 10,
    exclusion: str = "statement",
    ann_k: Optional[int] = None,
    embedding_model: str = "qwen3-8b",
    statement_timeout_ms: int = 60_000,
    show_progress: bool = True,
) -> Iterator[List[TopKResult]]:
    """Yield ranked candidates per query.

    ``ann_k`` is the HNSW shortlist size before the candidate-pool filter
    and cosine rerank. Choose it based on how rare the candidate pool is
    in the embedding index — the filter is applied AFTER the ANN scan
    (planner limitation in pgvector), so you need enough shortlist headroom
    to leave ≥ k * 5 survivors:

      candidate_pool        rough share of index    suggested ann_k
      all_informals         ~96%                    50-100
      blueprint_informals   ~0.02%                  not recommended via ANN
      project_formals       ~0.3%                   2000-4000

    Defaults to ``max(200, k*20)`` for safety; override per-pool.

    Per-query cost scales roughly linearly with ann_k (HNSW graph traversal
    bound). At ann_k=50 expect ~1.4s; at ann_k=200 expect ~2.8s on the
    cluster's current ACU sizing (cold-cache I/O dominated).

    Caller iterates this and writes via store.write_rows so 36k-query sweeps
    stream straight to RDS without buffering. Each yielded list is the top-K
    for one query (possibly empty if no embedding found for the query
    slogan, which shouldn't happen for our pools but is defended for).
    """
    if candidate_pool not in CANDIDATE_FILTERS:
        raise ValueError(
            f"unknown candidate_pool {candidate_pool!r}; "
            f"valid: {sorted(CANDIDATE_FILTERS)}"
        )
    sql = _build_sql(CANDIDATE_FILTERS[candidate_pool], exclusion)
    if ann_k is None:
        ann_k = max(200, k * 20)

    # Clear any prior transaction state so SET LOCAL applies to a fresh
    # transaction scoped to this generator. psycopg2 is transactional by
    # default; we just need to start clean.
    conn.rollback()
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = %s", (statement_timeout_ms,))
            cur.execute("SET LOCAL hnsw.ef_search = %s", (max(ann_k, 200),))
            cur.execute("SET LOCAL hnsw.iterative_scan = 'relaxed_order'")
            # Bumped 2026-05-26: the default `hnsw.max_scan_tuples = 20000` caps
            # how far `iterative_scan` will traverse the HNSW graph when the
            # post-filter (e.g. st.formality='informal') starves the shortlist.
            # Without this, formal-anchored f→i queries that hit dense
            # same-formality clusters in the index returned 0–10 informal
            # survivors instead of ~k*5. At 500k tuples the iterative_scan can
            # cover ~4% of the 12M-row index per query — enough to compensate
            # for the worst-case starvation while keeping per-query wall under
            # ~2 s (vs ~17 s at ann_k=500).
            cur.execute("SET LOCAL hnsw.max_scan_tuples = 500000")

            it = tqdm(queries, unit="q", leave=False) if show_progress else queries
            for q in it:
                cur.execute(_FETCH_QUERY_VEC_SQL, (q.slogan_id, embedding_model))
                row = cur.fetchone()
                if row is None:
                    yield []
                    continue
                query_vec = row[0]

                cur.execute(sql, {
                    "q":             query_vec,
                    "model":         embedding_model,
                    "slogan_models": _SLOGAN_MODELS,
                    "ann_k":         ann_k,
                    "k":             k,
                    "qid":           q.statement_id,
                    "qpid":          q.paper_id,
                })
                rows = cur.fetchall()
                yield [
                    TopKResult(
                        query_statement_id=q.statement_id,
                        rank=rank,
                        candidate_statement_id=cand_sid,
                        candidate_paper_id=cand_pid,
                        similarity=float(sim),
                    )
                    for rank, (cand_sid, cand_pid, sim) in enumerate(rows, 1)
                ]
    finally:
        # SET LOCAL is transaction-scoped, so rollback discards the GUCs.
        # Without this the timeout/ef_search settings leak into reuse of
        # this connection.
        conn.rollback()
