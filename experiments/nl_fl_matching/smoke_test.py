"""Smoke test for the matching foundation.

Picks 100 project formals, runs them against the all_informals candidate
pool with k=10, writes the results to nl_fl_match_pilot, and prints
per-query timing + a similarity-distribution summary. End-to-end gut-check
before any of the full sweeps.

Run from repo root:

    python -m experiments.nl_fl_matching.smoke_test
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Allow running from the repo root without installing the package.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "rds"))

from utils.connect import get_rds_connection  # noqa: E402

from experiments.nl_fl_matching import pools, store, topk  # noqa: E402


SMOKE_DIRECTION = "f2i"
SMOKE_EXCLUSION = "statement"
SMOKE_POOL      = "all_informals"
SMOKE_QUERIES   = 100
SMOKE_K         = 10
SMOKE_ANN_K     = 50    # all_informals ≈ 96% of index → small ann_k is fine
SMOKE_DESCRIPTOR = "smoke_test"
EMBEDDING_MODEL = "qwen3-8b"


def main() -> None:
    conn = get_rds_connection("v2")

    print(f"[1/4] ensuring nl_fl_match_pilot exists...", flush=True)
    store.ensure_table(conn)
    existing = store.count_rows(conn, pool_descriptor=SMOKE_DESCRIPTOR)
    if existing:
        print(f"      clearing {existing} prior smoke_test rows", flush=True)
        store.clear_run(
            conn,
            direction=SMOKE_DIRECTION, exclusion=SMOKE_EXCLUSION,
            embedding_model=EMBEDDING_MODEL,
            pool_descriptor=SMOKE_DESCRIPTOR,
        )

    print(f"[2/4] fetching {SMOKE_QUERIES} project_formals...", flush=True)
    t0 = time.perf_counter()
    queries = pools.fetch_project_formals(
        conn, embedding_model=EMBEDDING_MODEL, limit=SMOKE_QUERIES,
    )
    print(f"      got {len(queries)} ({time.perf_counter() - t0:.1f}s)", flush=True)
    if not queries:
        raise SystemExit("no project formals returned — check pool definition")

    print(f"[3/4] running topk vs '{SMOKE_POOL}' (k={SMOKE_K})...", flush=True)
    t0 = time.perf_counter()
    total_rows = 0
    sims = []
    empty = 0
    # Stream: write each query's results as they come in so the smoke test
    # also exercises the streaming-write path.
    all_rows = []
    for results in topk.embedding_topk(
        conn, queries, candidate_pool=SMOKE_POOL,
        k=SMOKE_K, exclusion=SMOKE_EXCLUSION,
        embedding_model=EMBEDDING_MODEL,
    ):
        if not results:
            empty += 1
            continue
        all_rows.extend(results)
        for r in results:
            sims.append(r.similarity)
    elapsed = time.perf_counter() - t0
    print(f"      {len(all_rows)} rows in {elapsed:.1f}s "
          f"({elapsed / max(1, len(queries)) * 1000:.0f} ms/query, "
          f"{empty} empty-result queries)", flush=True)

    print(f"[4/4] writing to RDS...", flush=True)
    written = store.write_rows(
        conn, all_rows,
        direction=SMOKE_DIRECTION, exclusion=SMOKE_EXCLUSION,
        pool_descriptor=SMOKE_DESCRIPTOR,
        embedding_model=EMBEDDING_MODEL,
    )
    print(f"      wrote {written} rows", flush=True)

    # Similarity summary so we can sanity-check that the embeddings are
    # behaving (no all-zeros, no all-ones, distribution skewed toward 1.0
    # is fine because we filtered to the matched subset).
    if sims:
        sims_sorted = sorted(sims)
        n = len(sims_sorted)
        def pct(p):
            return sims_sorted[min(n - 1, int(n * p))]
        print()
        print(f"  similarity stats over {n} ranked candidates:")
        print(f"    min    = {sims_sorted[0]:.4f}")
        print(f"    p10    = {pct(0.10):.4f}")
        print(f"    p50    = {pct(0.50):.4f}")
        print(f"    p90    = {pct(0.90):.4f}")
        print(f"    max    = {sims_sorted[-1]:.4f}")

    conn.close()
    print()
    print("smoke test ok")


if __name__ == "__main__":
    main()
