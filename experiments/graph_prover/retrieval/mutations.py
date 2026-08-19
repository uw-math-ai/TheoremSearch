"""Arm D/E: compiler-conditioned retrieval mutations.

After a failed attempt, the retrieval pool is MUTATED based on what the compiler said,
instead of retrying with the same premises (the anti-anchoring design — see
lean_premise_retrieval/docs/compiler_loop_results.md finding #3: a static premise pool
primes premature convergence).

Operators, applied in priority order for arm D (stacked one per retry) and
independently for arm E (one branch each):

  trigram-repair   every `unknown identifier/constant 'X'` in the error log gets a
                   pg_trgm name search (TRIGRAM_SQL from eval_mpr.py); top-3 each join
                   the pool
  error-requery    embed(last error text + proof sketch) -> 10 fresh cosine candidates
  forbid-tried     premises offered in >=2 failed attempts and never used get excluded,
                   freeing pool slots
  seed-swap        re-expand from cosine ranks 16-30 instead of 1-15, and toggle the
                   edge set (drop 'sig' <-> add 'proof')

TRIGRAM_SQL requires the mathlib_decl_names temp table + trigram index; build once per
connection with ensure_trigram_index(ctx).
"""
from __future__ import annotations

import re

from .. import config
from ..provenance import Candidate, RetrievalStep
from .arms import RetrievalContext, arm_a, expand_typed_one_hop, rrf_fuse, _mask, _assert_no_leak

MUTATION_OPS = ["trigram-repair", "error-requery", "forbid-tried", "seed-swap"]

# the closing ' is a delimiter, but ' is also a legal Lean identifier char (foo'):
# accept the quote as closing only when followed by a non-identifier char or the end.
UNKNOWN_RE = re.compile(
    r"[Uu]nknown (?:identifier|constant) '(.+?)'(?=$|[^A-Za-z0-9_'.₀-₉¡-￿])")

# Copied from experiments/leansearch_v2_replication/eval_mpr.py (TRIGRAM_INDEX_SQL /
# TRIGRAM_SQL), unchanged except the module-local docstring.
TRIGRAM_INDEX_SQL = """
CREATE TEMP TABLE IF NOT EXISTS mathlib_decl_names AS
SELECT DISTINCT fm.decl_name, st.statement_id, st.kind, p.paper_id
FROM formal_metadata fm
JOIN statement st ON st.statement_id = fm.statement_id
JOIN paper p      ON p.paper_id     = st.paper_id
WHERE p.external_id = ANY(%(mathlib_ids)s)
  AND fm.decl_name IS NOT NULL
"""

TRIGRAM_SQL = """
SELECT statement_id, decl_name,
       similarity(decl_name, %(q)s) AS trigram_sim
FROM mathlib_decl_names
WHERE decl_name %% %(q)s
  AND similarity(decl_name, %(q)s) >= %(min_sim)s
ORDER BY trigram_sim DESC
LIMIT %(k)s
"""

_trigram_ready: set[int] = set()


def ensure_trigram_index(ctx: RetrievalContext):
    key = id(ctx.conn)
    if key in _trigram_ready:
        return
    with ctx.conn.cursor() as cur:
        cur.execute("SET pg_trgm.similarity_threshold = 0.2")
        cur.execute(TRIGRAM_INDEX_SQL, {"mathlib_ids": config.MATHLIB_EXTERNAL_IDS})
        cur.execute("CREATE INDEX IF NOT EXISTS mathlib_decl_names_trgm "
                    "ON mathlib_decl_names USING gin (decl_name gin_trgm_ops)")
        cur.execute("ANALYZE mathlib_decl_names")
    ctx.conn.commit()
    _trigram_ready.add(key)


def unknown_identifiers(errors: list[dict]) -> list[str]:
    out, seen = [], set()
    for e in errors:
        for m in UNKNOWN_RE.finditer(e.get("message", "")):
            name = m.group(1)
            if name not in seen:
                seen.add(name)
                out.append(name)
    return out


def _tried_never_used(attempts) -> set[str]:
    """Decl names offered in >=2 failed attempts and never in premises_used."""
    offered_count: dict[str, int] = {}
    used: set[str] = set()
    for a in attempts:
        comp = a.compile
        failed = comp is None or not comp.solved
        for c in a.premises_offered:
            if failed and c.decl_name:
                offered_count[c.decl_name] = offered_count.get(c.decl_name, 0) + 1
        used.update(a.premises_used)
    return {n for n, k in offered_count.items() if k >= 2 and n not in used}


def mutate(ctx: RetrievalContext, task: dict, attempts: list, op: str,
           attempt_idx: int) -> tuple[list[Candidate], RetrievalStep]:
    """Produce a fresh pool for the next attempt via one mutation operator.

    `attempts` is the failed-attempt history (last one carries the fresh errors)."""
    last = attempts[-1] if attempts else None
    last_errors = (last.compile.errors if last and last.compile else []) or []
    base_pool = list(last.premises_offered) if last else arm_a(ctx, task, attempt_idx)[0]
    extra: list[Candidate] = []
    edges: list[tuple[str, str, str]] = []
    query_kind, query_text = op, ""

    if op == "trigram-repair":
        ensure_trigram_index(ctx)
        missing = unknown_identifiers(last_errors)
        query_text = ",".join(missing[:10])
        with ctx.conn.cursor() as cur:
            for name in missing[:5]:
                cur.execute(TRIGRAM_SQL, {"q": name, "min_sim": 0.2, "k": 3})
                for sid, decl, sim in cur.fetchall():
                    extra.append(Candidate(statement_id=str(sid), decl_name=decl,
                                           sig=ctx.sigs.get(decl, ""), score=float(sim),
                                           provenance=f"trigram:{name}"))

    elif op == "error-requery":
        err_text = " ; ".join(e.get("message", "") for e in last_errors[:5])
        sketch = (last.proof_text[:1500] if last else "")
        query_text = (err_text + "\n" + sketch)[:2000]
        if query_text.strip():
            import numpy as np
            qvec = np.asarray(ctx.embed_query(query_text), dtype="float32")
            hits = ctx.retriever.search_by_vec(
                qvec, k=10 + len(task["forbidden_ids"]),
                exclude_ids=frozenset(task["forbidden_ids"]))
            extra = [ctx.hydrate(sid, s, f"error-requery#{r}")
                     for r, (sid, s) in enumerate(hits, 1)][:10]

    elif op == "forbid-tried":
        stale = _tried_never_used(attempts)
        query_text = ",".join(sorted(stale)[:20])
        base_pool = [c for c in base_pool if c.decl_name not in stale]
        # refill freed slots from deeper cosine ranks
        refill, _ = arm_a(ctx, task, attempt_idx, k=config.POOL_K * 2)
        have = {c.decl_name for c in base_pool}
        extra = [c for c in refill if c.decl_name not in have and c.decl_name not in stale]

    elif op == "seed-swap":
        deep, _ = arm_a(ctx, task, attempt_idx, k=config.POOL_K)
        seeds = deep[15:30]
        toggled = RetrievalContext.__new__(RetrievalContext)  # shallow view w/ toggled edges
        toggled.__dict__ = dict(ctx.__dict__)
        toggled.edge_types = (["proof"] + [t for t in ctx.edge_types if t != "sig"]
                              if "sig" in ctx.edge_types else ["sig"] + list(ctx.edge_types))
        query_text = f"edges={toggled.edge_types}"
        extra, edges = expand_typed_one_hop(toggled, seeds, task)

    else:
        raise ValueError(f"unknown mutation op {op!r}")

    extra = _mask(extra, task)
    pool = rrf_fuse(base_pool, extra, k=config.POOL_K)
    _assert_no_leak(pool, task)
    step = RetrievalStep(attempt_idx=attempt_idx, query_kind=query_kind,
                         query_text=query_text,
                         seeds=[c.statement_id for c in base_pool[:5]],
                         edges_traversed=edges, candidates=pool, mutation_op=op)
    return pool, step


def _selftest():
    """Pure-python selftest: error parsing + forbid-tried bookkeeping (no DB/net)."""
    errs = [{"message": "unknown identifier 'Filtration.natural'"},
            {"message": "unknown constant 'MeasureTheory.wienerMeasure'"},
            {"message": "type mismatch at application"},
            {"message": "unknown identifier 'Filtration.natural'"}]
    ids = unknown_identifiers(errs)
    ok1 = ids == ["Filtration.natural", "MeasureTheory.wienerMeasure"]
    print(f"  [{'ok' if ok1 else 'MISMATCH'}] unknown_identifiers -> {ids}")

    from ..provenance import Attempt, CompileResult
    cand = lambda n: Candidate(statement_id=n, decl_name=n)
    fail = CompileResult(compiles=False, sorry_free=False)
    atts = [Attempt(idx=0, premises_offered=[cand("a"), cand("b")], compile=fail,
                    premises_used=["b"]),
            Attempt(idx=1, premises_offered=[cand("a"), cand("b")], compile=fail,
                    premises_used=[])]
    stale = _tried_never_used(atts)
    ok2 = stale == {"a"}
    print(f"  [{'ok' if ok2 else 'MISMATCH'}] _tried_never_used -> {stale}")
    print("SELFTEST", "PASS" if ok1 and ok2 else "FAIL")
    return ok1 and ok2


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        sys.exit(0 if _selftest() else 1)
