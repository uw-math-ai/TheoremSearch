"""Re-run the 114 non-gold f→i queries that returned 0 results at ann_k=50.

Root cause (see analysis/diagnose_empties.py + notes in
formalized_graph/docs/paper_writing/nongold_random_sweep.md §empty-query):
for non-gold project formals with deep-Mathlib-style slogans, the 50
nearest binary-HNSW candidates can all be formal, so the
`formality='informal'` filter kills all 50.

Solution: bump ann_k to 500 (10x the default). Writes to the same
nl_fl_match_pilot row family with a distinguishing pool_descriptor so
we can join the two slabs cleanly.

  pool_descriptor='nongold_random_f2i_annk500'

Wall: ~10 min (114 queries × ~5 s/q at ann_k=500).

Reproduce:
    python -m experiments.nl_fl_matching.runners.run_nongold_empties_retry
"""
from __future__ import annotations

import random
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "rds"))

from utils.connect import get_rds_connection  # noqa: E402
from experiments.nl_fl_matching import gold, pools, store, topk  # noqa: E402

EMBEDDING_MODEL = "qwen3-8b"
ANN_K = 500
K = 10
POOL_DESCRIPTOR = "nongold_random_f2i_annk500"


def main() -> None:
    conn = get_rds_connection("v2")
    store.ensure_table(conn)

    print("recomputing intended non-gold sample (seed=42)...", flush=True)
    g = gold.load_gold(conn, embedding_model=EMBEDDING_MODEL)
    all_formals = pools.fetch_project_formals(conn, embedding_model=EMBEDDING_MODEL)
    gold_fsids = {fid for _, fid in g.pairs}
    nongold_pool = [s for s in all_formals if s.statement_id not in gold_fsids]
    rng = random.Random(42)
    rng.shuffle(nongold_pool)
    sample = nongold_pool[:500]

    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT query_statement_id::text FROM nl_fl_match_pilot
             WHERE direction='f2i' AND pool_descriptor='nongold_random_f2i'
        """)
        has_rows = {r[0] for r in cur.fetchall()}
    empties = [s for s in sample if s.statement_id not in has_rows]
    print(f"  total sample: {len(sample)}, empties to retry: {len(empties)}",
          flush=True)

    if not empties:
        print("nothing to retry; exiting.")
        return

    store.clear_run(
        conn, direction="f2i", exclusion="statement",
        embedding_model=EMBEDDING_MODEL, pool_descriptor=POOL_DESCRIPTOR,
    )

    print(f"running ANN topk at ann_k={ANN_K}, k={K}...", flush=True)
    t0 = time.perf_counter()
    pending = []
    queries_done = 0
    rescued = 0
    for results in topk.embedding_topk(
        conn, empties, candidate_pool="all_informals",
        k=K, ann_k=ANN_K, exclusion="statement",
        embedding_model=EMBEDDING_MODEL,
    ):
        queries_done += 1
        if results:
            rescued += 1
            pending.extend(results)
        if queries_done % 25 == 0 and pending:
            n = store.write_rows(
                conn, pending,
                direction="f2i", exclusion="statement",
                pool_descriptor=POOL_DESCRIPTOR,
                embedding_model=EMBEDDING_MODEL,
            )
            pending.clear()
            print(f"  [{queries_done}/{len(empties)}] rescued={rescued} "
                  f"({time.perf_counter()-t0:.0f}s)", flush=True)
    if pending:
        store.write_rows(
            conn, pending,
            direction="f2i", exclusion="statement",
            pool_descriptor=POOL_DESCRIPTOR,
            embedding_model=EMBEDDING_MODEL,
        )

    elapsed = time.perf_counter() - t0
    print(f"done. {queries_done} queries, rescued={rescued}/{queries_done} "
          f"({rescued/max(1,queries_done):.1%}), {elapsed:.0f}s "
          f"({elapsed*1000/max(1,queries_done):.0f} ms/q)", flush=True)
    conn.close()


if __name__ == "__main__":
    main()
