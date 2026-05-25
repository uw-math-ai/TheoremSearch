"""f→f same-formality nearest-neighbour sweep with cross-project exclusion.

Each project formal (non-Mathlib, non-Batteries, non-Lean-core) is queried
against the same 36,708-formal pool with `exclusion='paper'` — so the top-K
candidates come from *other* repos. This characterizes cross-project
formalization overlap: how often the same statement is independently
formalized in two different repos.

Writes to nl_fl_match_pilot:
  direction        = 'f2f'
  exclusion        = 'paper'
  pool_descriptor  = 'cross_project_f2f'

Wall-clock target: ~5-10 min total (all-pairs matmul on a 36k × 4096 matrix,
chunked) + ~2 min RDS write of 36k × 10 = 360k rows.

Usage:
    python -m experiments.nl_fl_matching.runners.run_ff_cross_project
    python -m experiments.nl_fl_matching.runners.run_ff_cross_project --limit 500
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "rds"))

from utils.connect import get_rds_connection  # noqa: E402

from experiments.nl_fl_matching import pools, store, topk_matmul  # noqa: E402


EMBEDDING_MODEL  = "qwen3-8b"
POOL_DESCRIPTOR  = "cross_project_f2f"
DIRECTION        = "f2f"
EXCLUSION        = "paper"
K                = 10
WRITE_FLUSH_EVERY_QUERIES = 1000


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=None,
                   help="Optional cap on query count for testing.")
    p.add_argument("--chunk", type=int, default=1024,
                   help="Matmul chunk size (queries per all-pairs slab).")
    args = p.parse_args()

    conn = get_rds_connection("v2")
    store.ensure_table(conn)

    print("[1/3] loading project_formals pool into RAM...", flush=True)
    t0 = time.perf_counter()
    pool = topk_matmul.load_candidate_pool(
        conn, pools.CANDIDATE_FILTERS["project_formals"],
        embedding_model=EMBEDDING_MODEL,
    )
    n = len(pool.statement_ids)
    if args.limit:
        n = min(n, args.limit)
        descriptor = f"{POOL_DESCRIPTOR}_limit{args.limit}"
    else:
        descriptor = POOL_DESCRIPTOR
    print(f"      {len(pool.statement_ids):,} rows, "
          f"matrix {pool.matrix.shape}, "
          f"~{pool.matrix.nbytes / 1024**2:.0f} MB "
          f"({time.perf_counter()-t0:.1f}s)", flush=True)
    print(f"      sweeping {n:,} queries", flush=True)

    cleared = store.clear_run(
        conn, direction=DIRECTION, exclusion=EXCLUSION,
        embedding_model=EMBEDDING_MODEL, pool_descriptor=descriptor,
    )
    if cleared:
        print(f"      cleared {cleared} prior rows", flush=True)

    print(f"[2/3] all-pairs matmul (chunk={args.chunk})...", flush=True)
    t0 = time.perf_counter()

    if args.limit:
        # Trim pool view to N queries: still search against full candidate set,
        # but yield only first N queries. Easiest: monkey-truncate then restore
        # — but cleaner is to early-break the generator.
        result_stream = topk_matmul.embedding_topk_self_matmul(
            pool, k=K, exclusion=EXCLUSION, chunk=args.chunk,
        )
    else:
        result_stream = topk_matmul.embedding_topk_self_matmul(
            pool, k=K, exclusion=EXCLUSION, chunk=args.chunk,
        )

    pending = []
    queries_done = 0
    total_written = 0
    empty = 0
    for results in result_stream:
        queries_done += 1
        if not results:
            empty += 1
        else:
            pending.extend(results)
        if queries_done % WRITE_FLUSH_EVERY_QUERIES == 0 and pending:
            written = store.write_rows(
                conn, pending,
                direction=DIRECTION, exclusion=EXCLUSION,
                pool_descriptor=descriptor, embedding_model=EMBEDDING_MODEL,
            )
            total_written += written
            pending.clear()
            elapsed = time.perf_counter() - t0
            print(f"      [{queries_done}/{n}] wrote {total_written:,} rows "
                  f"({elapsed:.0f}s elapsed, "
                  f"{queries_done/max(elapsed,1):.0f} q/s)", flush=True)
        if args.limit and queries_done >= args.limit:
            break

    if pending:
        written = store.write_rows(
            conn, pending,
            direction=DIRECTION, exclusion=EXCLUSION,
            pool_descriptor=descriptor, embedding_model=EMBEDDING_MODEL,
        )
        total_written += written

    elapsed = time.perf_counter() - t0
    print(f"[3/3] done. {queries_done:,} queries, {total_written:,} rows, "
          f"{empty} empty, {elapsed:.0f}s total "
          f"({elapsed*1000/max(1,queries_done):.1f} ms/q)", flush=True)
    conn.close()


if __name__ == "__main__":
    main()
