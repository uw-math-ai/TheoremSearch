"""Personalized PageRank search under /graph/pagerank.

Same input as /graph/embedding (a natural-language query) but the ranking
goes through the informal dependency graph: the top-K embedding hits seed
the PPR personalization vector, then PPR redistributes mass through edges
and we return the highest-scoring statements.

Treats the graph as undirected — "relatedness" should flow both ways
between a statement and what cites it. Edges with NULL dep_id (unresolved
informal cites) are dropped.

The graph (~12M nodes / ~8M edges, ~16M directed entries after symmetrizing)
is loaded into process memory once on first request and cached. Power
iteration with damping 0.85 converges in ~30 steps; a typical query is
graph fetch (cached) + ~50 ANN candidates + ~30 sparse matvecs ≈ a few
seconds in steady state.
"""
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from scipy.sparse import csr_matrix, diags

from db import rds_conn
from routes.graph import _embed_query, _EMBED_MODEL, _SLOGAN_MODELS

logger = logging.getLogger(__name__)
router = APIRouter()


# Damping. 0.85 is the standard PageRank value and behaves well for PPR;
# not exposed as a query param since tuning it shifts result semantics in
# a way that's hard to compare across queries.
_DAMPING = 0.85
# PPR converges geometrically in the damping factor; 30 iterations leaves
# residual < 1e-6 in practice. Power iteration is bounded by _TOL too.
_MAX_ITER = 30
_TOL = 1e-6


class PageRankResult(BaseModel):
    statement_id: str
    score: float
    # Embedding similarity if this node was in the seed set, else None.
    # Lets the caller see which results came from the embedding stage vs.
    # were pulled in by graph propagation.
    seed_similarity: Optional[float] = None


class PageRankResponse(BaseModel):
    results: List[PageRankResult]


# ------------------------------------------------------------------ #
# Graph cache                                                         #
# ------------------------------------------------------------------ #

@dataclass
class _Graph:
    # Row-stochastic transition matrix (undirected adjacency, row-normalized).
    M: csr_matrix
    # statement_id (str) -> row index
    id_to_idx: dict
    # row index -> statement_id (str)
    idx_to_id: np.ndarray
    # Boolean mask of dangling nodes (no edges); their mass is redistributed
    # to the personalization vector each iteration so probabilities stay
    # normalized.
    dangling: np.ndarray


_graph_cache: Optional[_Graph] = None
# True while a background thread is building the graph, so concurrent requests
# don't each spawn a builder. Guarded by _graph_lock.
_graph_building = False
# monotonic() time of the last failed build (0.0 = none). Used to back off so a
# persistently broken dependency (e.g. DB down) doesn't trigger an expensive
# ~12M-row rebuild on every single request.
_graph_last_fail_at = 0.0
_GRAPH_RETRY_COOLDOWN_S = 30.0
_graph_lock = threading.Lock()


def _pagerank_enabled() -> bool:
    """Endpoint kill-switch, read per request. PageRank holds the whole
    ~12M-node graph in process memory; set PAGERANK_ENABLED=false to turn the
    route off (returns 404) if it threatens an instance's memory. Read on each
    request rather than frozen at import, so the value isn't stale on a running
    process; defaults on. (On App Runner, changing a service env var also
    triggers a redeploy.)"""
    return os.getenv("PAGERANK_ENABLED", "true").strip().lower() not in (
        "0", "false", "no", "off",
    )


def _load_graph() -> _Graph:
    """Pull all informal statements + edges and build a row-stochastic
    undirected adjacency matrix.

    Loads all informal statements (even isolated ones) so that seed lookups
    never miss — an isolated seed still gets its personalization mass even
    if PPR can't spread it.
    """
    logger.info("Loading informal dependency graph into memory...")
    with rds_conn("v2") as conn, conn.cursor() as cur:
        # Default 10s statement_timeout from db.py is for request-shaped
        # queries; the one-shot graph load pulls 12M IDs + 8M edges and
        # routinely takes 30–60s. Lifted to 10min for this transaction only.
        cur.execute("SET LOCAL statement_timeout = '600000';")
        cur.execute(
            """
            SELECT statement_id::text
            FROM statement
            WHERE formality = 'informal'
            """
        )
        ids = [r[0] for r in cur.fetchall()]
        n = len(ids)
        id_to_idx = {sid: i for i, sid in enumerate(ids)}
        idx_to_id = np.array(ids, dtype=object)
        logger.info("Loaded %d informal statements", n)

        cur.execute(
            """
            SELECT src_id::text, dep_id::text
            FROM informal_dependency
            WHERE dep_id IS NOT NULL
            """
        )
        edges = cur.fetchall()
        logger.info("Loaded %d informal edges", len(edges))

    # Symmetrize: each edge contributes both (src,dep) and (dep,src). We
    # overallocate then trim — `id_to_idx.get` may return None for an edge
    # endpoint whose statement row was missing (shouldn't happen, but the
    # graph load and the edge load aren't transactionally tied).
    src = np.empty(2 * len(edges), dtype=np.int32)
    dst = np.empty(2 * len(edges), dtype=np.int32)
    write = 0
    skipped = 0
    for s, d in edges:
        si = id_to_idx.get(s)
        di = id_to_idx.get(d)
        if si is None or di is None:
            skipped += 1
            continue
        src[write] = si
        dst[write] = di
        src[write + 1] = di
        dst[write + 1] = si
        write += 2
    src = src[:write]
    dst = dst[:write]
    if skipped:
        logger.warning("Skipped %d edges with missing endpoints", skipped)

    data = np.ones(write, dtype=np.float32)
    A = csr_matrix((data, (src, dst)), shape=(n, n))

    # Row-normalize so M is a random-walk transition matrix.
    deg = np.asarray(A.sum(axis=1)).ravel()
    dangling = deg == 0
    inv = np.zeros_like(deg, dtype=np.float32)
    inv[~dangling] = 1.0 / deg[~dangling]
    M = (diags(inv) @ A).tocsr()

    logger.info(
        "Graph ready: %d nodes, %d directed entries, %d dangling",
        n, M.nnz, int(dangling.sum()),
    )
    return _Graph(M=M, id_to_idx=id_to_idx, idx_to_id=idx_to_id, dangling=dangling)


def _build_graph_in_background() -> None:
    """Build the graph off the request path and publish it to the cache.

    Runs on a dedicated daemon thread (started by `_graph_or_none`). On
    failure the building flag is cleared and the failure time recorded so a
    later request retries after a cooldown.
    """
    global _graph_cache, _graph_building, _graph_last_fail_at
    try:
        g = _load_graph()
    except Exception:
        logger.exception("PageRank graph build failed; will retry after cooldown")
        g = None
    with _graph_lock:
        if g is not None:
            _graph_cache = g
        else:
            _graph_last_fail_at = time.monotonic()
        _graph_building = False


def _graph_or_none() -> Optional[_Graph]:
    """Return the cached graph if ready, else None — kicking off a one-time
    background build on first call.

    The build pulls ~12M ids + ~8M edges and takes ~30-60s. Building it inline
    would pin a request thread (one of FastAPI's limited threadpool workers)
    for that whole time and risk tripping App Runner's request timeout /
    health check. So the request thread never waits on it: callers get None
    while the graph warms and should surface a 503.
    """
    global _graph_building
    if _graph_cache is not None:
        return _graph_cache
    with _graph_lock:
        # Re-check under the lock: another thread may have just published it.
        if _graph_cache is not None:
            return _graph_cache
        if not _graph_building:
            # Back off after a failed build so a broken dependency doesn't
            # trigger an expensive rebuild on every request.
            if _graph_last_fail_at and (
                time.monotonic() - _graph_last_fail_at < _GRAPH_RETRY_COOLDOWN_S
            ):
                return None
            t = threading.Thread(
                target=_build_graph_in_background,
                name="pagerank-graph-build",
                daemon=True,
            )
            try:
                t.start()
            except Exception:
                # Never leave the flag stuck True if the thread won't start —
                # that would wedge the endpoint into a permanent 503.
                logger.exception("Failed to start PageRank graph build thread")
                return None
            # Set only after a successful start, so a start() failure above
            # leaves the flag False and the next request can retry.
            _graph_building = True
        return None


# ------------------------------------------------------------------ #
# Seeding: top-K embedding hits become the personalization vector     #
# ------------------------------------------------------------------ #

# Same two-stage ANN as /graph/embedding (binary-quantized HNSW + cosine
# rerank), but pared down to just (statement_id, similarity) and pinned to
# informal statements. Multiple slogans per statement are deduped to the
# best-similarity one.
_SEED_SQL = """
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
    SELECT st.statement_id::text AS statement_id,
           1.0 - (ann.embedding <=> %(q)s::vector(4096)) AS similarity
    FROM ann
    JOIN slogan s     ON s.slogan_id    = ann.slogan_id
    JOIN statement st ON st.statement_id = s.statement_id
    WHERE NOT s.insufficient_context
      AND st.formality = 'informal'
)
SELECT statement_id, MAX(similarity) AS similarity
FROM ranked
GROUP BY statement_id
ORDER BY similarity DESC
LIMIT %(k)s;
"""


def _fetch_seeds(query_vec: List[float], k: int) -> List[Tuple[str, float]]:
    ann_k = max(k * 10, 500)
    with rds_conn("v2") as conn, conn.cursor() as cur:
        cur.execute("SET LOCAL hnsw.ef_search = %s;", (min(ann_k, 1000),))
        cur.execute("SET LOCAL hnsw.iterative_scan = 'relaxed_order';")
        cur.execute(_SEED_SQL, {
            "q":             query_vec,
            "model":         _EMBED_MODEL,
            "slogan_models": _SLOGAN_MODELS,
            "ann_k":         ann_k,
            "k":             k,
        })
        return [(sid, float(sim)) for sid, sim in cur.fetchall()]


# ------------------------------------------------------------------ #
# PPR                                                                 #
# ------------------------------------------------------------------ #

def _personalized_pagerank(
    g: _Graph,
    seed_indices: np.ndarray,
    seed_weights: np.ndarray,
) -> np.ndarray:
    """Power iteration for PPR.

        r_{t+1} = damping * (M^T r_t + dangling_mass * s) + (1-damping) * s

    where s is the personalization vector (seed mass) and dangling_mass is
    the probability sitting on no-out-edge nodes — redistributed back to
    the seeds so total mass stays at 1. Equivalent to the standard
    teleportation trick (Page et al.) restricted to the personalization
    distribution instead of uniform.

    Graph is undirected so M == M^T; we still write M.T to keep the formula
    correct if a directed variant is added later.
    """
    n = g.M.shape[0]
    s = np.zeros(n, dtype=np.float32)
    total = float(seed_weights.sum())
    if total <= 0:
        return s
    s[seed_indices] = seed_weights / total

    r = s.copy()
    MT = g.M.T.tocsr()
    for it in range(_MAX_ITER):
        dangling_mass = float(r[g.dangling].sum())
        r_new = _DAMPING * (MT @ r + dangling_mass * s) + (1.0 - _DAMPING) * s
        delta = float(np.abs(r_new - r).sum())
        r = r_new
        if delta < _TOL:
            logger.debug("PPR converged in %d iterations (delta=%g)", it + 1, delta)
            break
    return r


# ------------------------------------------------------------------ #
# Route                                                               #
# ------------------------------------------------------------------ #

@router.get(
    "/graph/pagerank",
    response_model=PageRankResponse,
    response_model_exclude_none=True,
)
def graph_pagerank(
    query: str = Query(..., min_length=1, description="Natural-language search query."),
    n_results: int = Query(10, ge=1, le=100, description="How many ranked results to return."),
    n_seeds: int = Query(
        50, ge=1, le=500,
        description=(
            "How many top embedding hits to use as PPR seeds. Larger = closer "
            "to dense retrieval; smaller = more graph-flavored."
        ),
    ),
):
    if not _pagerank_enabled():
        raise HTTPException(status_code=404, detail="The PageRank endpoint is disabled.")

    try:
        g = _graph_or_none()
        if g is None:
            # Graph is building on a background thread; don't block this
            # request thread for the ~30-60s build — tell the caller to retry.
            raise HTTPException(
                status_code=503,
                detail="PageRank graph is warming up; retry in ~1 minute.",
            )

        query_vec = _embed_query(query)
        seeds = _fetch_seeds(query_vec, n_seeds)
        if not seeds:
            return PageRankResponse(results=[])

        # Map seed statement_ids → graph indices (drop any that aren't in
        # the cached graph — shouldn't happen, but the cache is point-in-time).
        seed_idx_list: List[int] = []
        seed_weight_list: List[float] = []
        seed_sim_by_id: dict = {}
        for sid, sim in seeds:
            idx = g.id_to_idx.get(sid)
            if idx is None:
                continue
            seed_idx_list.append(idx)
            seed_weight_list.append(max(sim, 0.0))
            seed_sim_by_id[sid] = sim
        if not seed_idx_list:
            return PageRankResponse(results=[])

        seed_indices = np.array(seed_idx_list, dtype=np.int32)
        seed_weights = np.array(seed_weight_list, dtype=np.float32)

        r = _personalized_pagerank(g, seed_indices, seed_weights)

        # Top-n_results by score. argpartition is O(n) — argsort would copy
        # and sort the full 12M-vector.
        if n_results >= len(r):
            top_idx = np.argsort(-r)
        else:
            part = np.argpartition(-r, n_results)[:n_results]
            top_idx = part[np.argsort(-r[part])]

        results = []
        for i in top_idx:
            score = float(r[i])
            if score <= 0:
                # Rest of the vector is zero (PPR didn't reach it); no point
                # padding the response with arbitrarily-ordered zero-score IDs.
                break
            sid = str(g.idx_to_id[i])
            results.append(PageRankResult(
                statement_id=sid,
                score=score,
                seed_similarity=seed_sim_by_id.get(sid),
            ))
        return PageRankResponse(results=results)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("/graph/pagerank failed")
        raise HTTPException(status_code=500, detail=f"/graph/pagerank failed: {e}")
