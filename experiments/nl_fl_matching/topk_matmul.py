"""In-memory top-K matching for small candidate pools.

When the candidate pool fits in RAM (≲ a few hundred thousand × 4096 floats),
loading the embeddings once and computing cosine via numpy matmul beats ANN
— especially when the cluster is contended on I/O. For the i2f experiment
(1,308 queries × 36,708 candidates), this turns a 10+ hour ANN sweep into
a ~minute-scale matmul.

Embeddings are L2-normalized at load time so cosine collapses to a single
inner product. Per-query work is ~36k × 4096 = 150M FLOPs ≈ a few ms on
CPU; query embedding fetch from RDS is the bottleneck.

API mirrors topk.embedding_topk so runners can swap them interchangeably.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, List, Optional, Tuple

import numpy as np
from tqdm import tqdm

from .pools import Stmt
from .topk import TopKResult


@dataclass
class CandidatePool:
    """Stacked candidate matrix kept around between calls so a runner can
    reuse it across many query batches.

    `matrix` is L2-normalized: cosine(q, c) = q_normed @ matrix[i].
    """
    statement_ids: List[str]
    paper_ids:     List[str]
    matrix:        np.ndarray   # shape (N, dim), float32, L2-normalized


_FETCH_POOL_SQL = """
WITH first_slogan AS (
    SELECT DISTINCT ON (sl.statement_id)
           sl.statement_id, sl.slogan_id
      FROM slogan sl
     WHERE NOT sl.insufficient_context
       AND sl.model_name = ANY(%(slogan_models)s)
     ORDER BY sl.statement_id, sl.created_at
)
SELECT st.statement_id::text, st.paper_id::text, e.embedding
  FROM first_slogan fs
  JOIN statement   st ON st.statement_id = fs.statement_id
  JOIN embedding   e  ON e.slogan_id = fs.slogan_id
                     AND e.model_name = %(model)s
 WHERE {filter_sql}
"""


def _parse_pgvector(emb) -> np.ndarray:
    if isinstance(emb, str):
        return np.fromstring(emb[1:-1], sep=",", dtype=np.float32)
    return np.asarray(emb, dtype=np.float32)


def _l2_normalize_rows(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return m / norms


def load_candidate_pool(
    conn,
    candidate_filter_sql: str,
    *,
    embedding_model: str = "qwen3-8b",
    slogan_models: Optional[List[str]] = None,
    show_progress: bool = True,
) -> CandidatePool:
    """Pull every (statement, slogan, embedding) row matching the filter
    into a normalized float32 matrix. ``candidate_filter_sql`` is a fragment
    referencing ``st.*`` (statement alias).

    For project_formals (~36k rows × 4096 dims × 4 bytes) this allocates
    ~570 MB. Caller pays once per pool.
    """
    if slogan_models is None:
        slogan_models = ["qwen3-235b"]

    sql = _FETCH_POOL_SQL.format(filter_sql=candidate_filter_sql)
    sids: List[str] = []
    pids: List[str] = []
    vecs: List[np.ndarray] = []

    # psycopg2 server-side cursor — keeps memory bounded on the DB side
    # when we're pulling tens of thousands of 4096-dim vectors.
    conn.rollback()
    with conn.cursor(name="pool_load_stream") as cur:
        cur.itersize = 1024
        cur.execute(sql, {"model": embedding_model, "slogan_models": slogan_models})
        it = tqdm(cur, unit="row", desc="loading pool", disable=not show_progress)
        for sid, pid, emb in it:
            sids.append(sid)
            pids.append(pid)
            vecs.append(_parse_pgvector(emb))
    matrix = np.stack(vecs).astype(np.float32, copy=False)
    matrix = _l2_normalize_rows(matrix)
    return CandidatePool(statement_ids=sids, paper_ids=pids, matrix=matrix)


_FETCH_QUERY_VEC_SQL = """
SELECT e.embedding
  FROM embedding e
  JOIN slogan s ON s.slogan_id = e.slogan_id
 WHERE s.slogan_id = %s::uuid
   AND e.model_name = %s
   AND NOT s.insufficient_context
 LIMIT 1
"""


def embedding_topk_matmul(
    conn,
    queries: List[Stmt],
    pool: CandidatePool,
    *,
    k: int = 10,
    exclusion: str = "statement",
    embedding_model: str = "qwen3-8b",
    show_progress: bool = True,
) -> Iterator[List[TopKResult]]:
    """Top-K candidates for each query via numpy matmul against ``pool``.

    Cosine is the dot product because pool.matrix and the query vector are
    both L2-normalized. We use argpartition + small sort to avoid the full
    sort over 36k candidates.

    Exclusion is enforced on the result before truncating to k.
    """
    if exclusion not in {"statement", "paper"}:
        raise ValueError(f"exclusion must be 'statement' or 'paper', got {exclusion!r}")

    pool_sid_to_idx = {sid: i for i, sid in enumerate(pool.statement_ids)}

    # Build the per-query exclusion mask lazily; for "paper" mode we need to
    # know the per-row paper assignment, which is in pool.paper_ids.
    pool_paper_arr = np.array(pool.paper_ids)

    conn.rollback()
    cur = conn.cursor()
    it = tqdm(queries, unit="q", disable=not show_progress)
    for q in it:
        cur.execute(_FETCH_QUERY_VEC_SQL, (q.slogan_id, embedding_model))
        row = cur.fetchone()
        if row is None:
            yield []
            continue
        qvec = _parse_pgvector(row[0])
        n = np.linalg.norm(qvec)
        if n == 0:
            yield []
            continue
        qvec = qvec / n

        sims = pool.matrix @ qvec  # (N,)

        # Mask out self before topk so we don't shrink k post-hoc.
        if exclusion == "statement":
            idx = pool_sid_to_idx.get(q.statement_id)
            if idx is not None:
                sims[idx] = -np.inf
        else:  # paper
            mask = pool_paper_arr == q.paper_id
            if mask.any():
                sims[mask] = -np.inf

        # argpartition for top-k, then sort just those k indices.
        if k >= len(sims):
            order = np.argsort(-sims)
        else:
            cand = np.argpartition(-sims, k)[:k]
            order = cand[np.argsort(-sims[cand])]

        yield [
            TopKResult(
                query_statement_id=q.statement_id,
                rank=rank,
                candidate_statement_id=pool.statement_ids[i],
                candidate_paper_id=pool.paper_ids[i],
                similarity=float(sims[i]),
            )
            for rank, i in enumerate(order, 1)
            if np.isfinite(sims[i])
        ]
    cur.close()
