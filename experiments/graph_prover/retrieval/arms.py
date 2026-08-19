"""Retrieval arms A/B/C behind one interface (arms D/E add mutations.py on top).

  A  semantic top-K            FormalRetriever cosine over formal slogan embeddings
  B  A + typed one-hop         GRAPH_EXPAND_SQL parents of A's seeds, RRF-fused
  C  B + informal->formal      graph_pack() (INTEGRATION.md spec), RRF-fused

Every arm returns (pool, RetrievalStep) where pool is a ranked list[Candidate] of at
most POOL_K entries, forbidden ids/names already masked, provenance tags attached.

The query embedding is IDENTICAL across arms — the target's own slogan vector, exactly
like lean_premise_retrieval/scripts/build_rag_context.py — so the arm contrast isolates
the graph machinery, not query quality.

GRAPH_EXPAND_SQL is copied (edge types parameterized) from
experiments/leansearch_v2_replication/eval_mpr.py; rrf_fuse follows the same file.
"""
from __future__ import annotations

import os
from collections import defaultdict

from .. import config
from ..provenance import Candidate, RetrievalStep

# Copied from experiments/leansearch_v2_replication/eval_mpr.py::GRAPH_EXPAND_SQL,
# with edge_type parameterized (spike edge_census decides the live set).
GRAPH_EXPAND_SQL = """
SELECT DISTINCT
    fd.src_id::text                       AS child_id,
    parent.statement_id::text             AS parent_id,
    fd.edge_type                          AS edge_type,
    parent_fm.decl_name                   AS parent_decl_name
FROM formal_dependency fd
JOIN statement parent ON parent.statement_id = fd.dep_id
JOIN paper p ON p.paper_id = parent.paper_id
JOIN formal_metadata parent_fm ON parent_fm.statement_id = parent.statement_id
WHERE fd.src_id = ANY(%(child_ids)s::uuid[])
  AND fd.edge_type = ANY(%(edge_types)s)
  AND p.external_id = ANY(%(mathlib_ids)s)
  AND parent_fm.decl_name IS NOT NULL
"""

DEFAULT_EDGE_TYPES = [t.strip() for t in
                      os.environ.get("GP_EDGE_TYPES", "sig,extends,field").split(",")]


class RetrievalContext:
    """Lazily-initialized shared resources so arm A runs with no DB/network at all."""

    def __init__(self, meter=None):
        self.meter = meter
        self._retriever = None
        self._conn = None
        self._oai = None
        self._names = None      # statement_id -> decl_name (LPR cache/decl_names.json)
        self._sigs = None       # decl_name -> signature   (LPR cache/ml429_namesigs.tsv)
        self.edge_types = list(DEFAULT_EDGE_TYPES)

    @property
    def retriever(self):
        if self._retriever is None:
            self._retriever = config.load_formal_retriever()
        return self._retriever

    @property
    def conn(self):
        if self._conn is None:
            self._conn = config.get_rds_conn()
        return self._conn

    @property
    def oai(self):
        if self._oai is None:
            self._oai = config.make_nebius_client()
        return self._oai

    @property
    def names(self) -> dict:
        if self._names is None:
            import json
            self._names = json.loads((config.LPR_CACHE / "decl_names.json").read_text())
        return self._names

    @property
    def sigs(self) -> dict:
        if self._sigs is None:
            self._sigs = {}
            p = config.LPR_CACHE / "ml429_namesigs.tsv"
            if p.exists():
                for line in p.read_text().splitlines():
                    name, _, sig = line.partition("\t")
                    if name:
                        self._sigs[name] = sig
        return self._sigs

    def embed_query(self, text: str) -> list[float]:
        """Nebius Qwen3-Embedding-8B with the corpus query instruction, L2-normalized.
        Pattern from eval_mpr.py::embed_query."""
        import math
        resp = self.oai.embeddings.create(
            model="Qwen/Qwen3-Embedding-8B",
            input=config.QUERY_INSTRUCTION + text, encoding_format="float")
        if self.meter is not None and getattr(resp, "usage", None):
            self.meter.record_embedding(resp.usage.prompt_tokens)
        v = resp.data[0].embedding
        n = math.sqrt(sum(x * x for x in v))
        return [x / n for x in v] if n > 0 else v

    def hydrate(self, statement_id: str, score: float, provenance: str) -> Candidate:
        name = self.names.get(statement_id, "")
        return Candidate(statement_id=statement_id, decl_name=name,
                         sig=self.sigs.get(name, ""), score=score, provenance=provenance)


def rrf_fuse(*ranked_lists: list[Candidate], k: int) -> list[Candidate]:
    """Reciprocal-rank fusion (constant RRF_K, as in eval_mpr.py). First list wins ties
    on the kept Candidate object, so earlier provenance tags are preserved."""
    scores: dict[str, float] = defaultdict(float)
    keep: dict[str, Candidate] = {}
    for lst in ranked_lists:
        for rank, c in enumerate(lst, 1):
            scores[c.statement_id] += 1.0 / (config.RRF_K + rank)
            keep.setdefault(c.statement_id, c)
    out = sorted(keep.values(), key=lambda c: -scores[c.statement_id])
    return out[:k]


def _mask(pool: list[Candidate], task: dict) -> list[Candidate]:
    forb_ids = set(task["forbidden_ids"])
    forb_names = set(task["forbidden_names"])
    return [c for c in pool
            if c.statement_id not in forb_ids and c.decl_name not in forb_names]


def _assert_no_leak(pool: list[Candidate], task: dict):
    """Hard leakage gate (approved plan §Verification) — never soften to a warning."""
    leaked = [c.decl_name or c.statement_id for c in pool
              if c.statement_id in set(task["forbidden_ids"])
              or c.decl_name in set(task["forbidden_names"])]
    assert not leaked, f"forbidden-set leak in retrieval pool: {leaked}"


def arm_a(ctx: RetrievalContext, task: dict, attempt_idx: int = 0,
          k: int | None = None) -> tuple[list[Candidate], RetrievalStep]:
    k = k or config.POOL_K
    qvec = ctx.retriever.vec_for(task["tid"])
    if qvec is None:
        raise KeyError(f"{task['tid']} not in the formal index")
    hits = ctx.retriever.search_by_vec(qvec, k=k + len(task["forbidden_ids"]),
                                       exclude_ids=frozenset(task["forbidden_ids"]))
    pool = [ctx.hydrate(sid, score, f"cosine#{r}")
            for r, (sid, score) in enumerate(hits, 1)]
    pool = _mask(pool, task)[:k]
    _assert_no_leak(pool, task)
    step = RetrievalStep(attempt_idx=attempt_idx, query_kind="slogan-vec",
                         query_text=task["tid"], seeds=[task["tid"]],
                         candidates=pool, excluded=sorted(task["forbidden_names"])[:50])
    return pool, step


def expand_typed_one_hop(ctx: RetrievalContext, seeds: list[Candidate],
                         task: dict) -> tuple[list[Candidate], list[tuple[str, str, str]]]:
    child_ids = [c.statement_id for c in seeds]
    with ctx.conn.cursor() as cur:
        cur.execute(GRAPH_EXPAND_SQL, {"child_ids": child_ids,
                                       "edge_types": ctx.edge_types,
                                       "mathlib_ids": config.MATHLIB_EXTERNAL_IDS})
        rows = cur.fetchall()
    rank_of = {c.statement_id: i for i, c in enumerate(seeds, 1)}
    child_name = {c.statement_id: c.decl_name for c in seeds}
    best: dict[str, tuple[int, Candidate]] = {}
    edges = []
    for child_id, parent_id, edge_type, parent_decl in rows:
        edges.append((child_id, edge_type, parent_id))
        r = rank_of.get(child_id, 999)
        cand = Candidate(statement_id=parent_id, decl_name=parent_decl,
                         sig=ctx.sigs.get(parent_decl, ""), score=1.0 / r,
                         provenance=f"graph:{edge_type}-parent-of:"
                                    f"{child_name.get(child_id, child_id)}")
        if parent_id not in best or r < best[parent_id][0]:
            best[parent_id] = (r, cand)
    parents = [c for _, c in sorted(best.values(), key=lambda t: t[0])]
    return _mask(parents, task), edges


def arm_b(ctx: RetrievalContext, task: dict, attempt_idx: int = 0,
          seed_slice: slice = slice(0, 15)) -> tuple[list[Candidate], RetrievalStep]:
    base, step_a = arm_a(ctx, task, attempt_idx)
    seeds = base[seed_slice]
    parents, edges = expand_typed_one_hop(ctx, seeds, task)
    pool = rrf_fuse(base, parents, k=config.POOL_K)
    _assert_no_leak(pool, task)
    step = RetrievalStep(attempt_idx=attempt_idx, query_kind="slogan-vec+graph-expand",
                         query_text=task["tid"],
                         seeds=[c.statement_id for c in seeds],
                         edges_traversed=edges, candidates=pool,
                         excluded=step_a.excluded)
    return pool, step


def arm_c(ctx: RetrievalContext, task: dict, attempt_idx: int = 0
          ) -> tuple[list[Candidate], RetrievalStep]:
    from .graph_pack import graph_pack
    pool_b, step_b = arm_b(ctx, task, attempt_idx)
    nl_query = ctx.retriever.slogans.get(task["tid"]) or task.get("slogan") or ""
    xform, cross_links = ([], [])
    if nl_query:
        xform, cross_links = graph_pack(ctx, nl_query, k=15,
                                        exclude_names=set(task["forbidden_names"]))
        xform = _mask(xform, task)
    pool = rrf_fuse(pool_b, xform, k=config.POOL_K)
    _assert_no_leak(pool, task)
    step = RetrievalStep(attempt_idx=attempt_idx,
                         query_kind="slogan-vec+graph-expand+xform",
                         query_text=nl_query[:500],
                         seeds=step_b.seeds, edges_traversed=step_b.edges_traversed,
                         cross_links=cross_links, candidates=pool,
                         excluded=step_b.excluded)
    return pool, step


ARMS = {"A": arm_a, "B": arm_b, "C": arm_c}
