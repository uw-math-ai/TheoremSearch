"""Headline-table sweep: run topk on every blueprint gold-pair query in
both directions, write to nl_fl_match_pilot.

A1 (--direction f2i): 1,577 gold formals → top-K from all_informals
A2 (--direction i2f): 1,308 gold informals → top-K from project_formals

A1 and A2 are independent and can be launched as two parallel processes.

Usage:
    python -m experiments.nl_fl_matching.runners.run_gold_pair_sweep \
        --direction f2i

    python -m experiments.nl_fl_matching.runners.run_gold_pair_sweep \
        --direction i2f
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import List

# Flush partial results to RDS every N queries. Means an interrupted run
# can be resumed by simply re-launching with the same args — idempotent
# upsert on the PK overwrites stale rows.
WRITE_FLUSH_EVERY = 100

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "rds"))

from utils.connect import get_rds_connection  # noqa: E402

from experiments.nl_fl_matching import gold, pools, store, topk, topk_matmul  # noqa: E402


EMBEDDING_MODEL = "qwen3-8b"

# Per-direction config.
#
# Mode selection:
#   "ann"     — pgvector binary-HNSW + cosine rerank. Use when the candidate
#               pool is a meaningful fraction of the embedding index.
#   "matmul"  — load the entire candidate pool into RAM, compute cosine via
#               numpy. Use when the pool is small (≲ a few 100k rows). For
#               i2f the pool is 36k project_formals — a single ~570 MB
#               matrix, ms-scale per-query matmul. Avoids the ann_k=2000
#               cost we'd otherwise need to leave enough survivors.
#
# ann_k for ANN mode is chosen by how rare the candidate pool is in the
# 12M-row embedding index (see topk.embedding_topk docstring).
CONFIG = {
    "f2i": {
        "mode":             "ann",
        "candidate_pool":   "all_informals",
        "ann_k":            50,
        "pool_descriptor":  "gold_subset_f2i",
        "k":                10,
    },
    "i2f": {
        "mode":             "matmul",
        "candidate_pool":   "project_formals",
        "pool_descriptor":  "gold_subset_i2f",
        "k":                10,
    },
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--direction", choices=("f2i", "i2f"), required=True)
    parser.add_argument("--limit", type=int, default=None,
                        help="Optional cap on query count for testing.")
    parser.add_argument("--exclusion", default="statement",
                        choices=("statement", "paper"))
    args = parser.parse_args()

    cfg = CONFIG[args.direction]
    conn = get_rds_connection("v2")

    print(f"[1/3] ensuring nl_fl_match_pilot exists...", flush=True)
    store.ensure_table(conn)

    print(f"[2/3] loading gold pairs...", flush=True)
    t0 = time.perf_counter()
    g = gold.load_gold(conn, embedding_model=EMBEDDING_MODEL)
    print(f"      {len(g.informals)} informals, {len(g.formals)} formals, "
          f"{len(g.pairs)} pairs ({time.perf_counter()-t0:.1f}s)", flush=True)

    queries = g.formals if args.direction == "f2i" else g.informals
    if args.limit:
        queries = queries[: args.limit]
        cfg = {**cfg, "pool_descriptor": cfg["pool_descriptor"] + f"_limit{args.limit}"}
    print(f"      using {len(queries)} {args.direction} queries", flush=True)

    # Idempotent re-run: wipe any prior rows for this exact (direction,
    # exclusion, pool_descriptor) combo so we don't accumulate stale ranks.
    cleared = store.clear_run(
        conn,
        direction=args.direction, exclusion=args.exclusion,
        embedding_model=EMBEDDING_MODEL,
        pool_descriptor=cfg["pool_descriptor"],
    )
    if cleared:
        print(f"      cleared {cleared} prior rows", flush=True)

    print(f"[3/3] running topk ({cfg['mode']}) vs '{cfg['candidate_pool']}' "
          f"(k={cfg['k']})  — streaming writes every {WRITE_FLUSH_EVERY} queries",
          flush=True)
    t0 = time.perf_counter()
    empty = 0
    total_written = 0

    if cfg["mode"] == "ann":
        result_stream = topk.embedding_topk(
            conn, queries,
            candidate_pool=cfg["candidate_pool"],
            k=cfg["k"], ann_k=cfg["ann_k"],
            exclusion=args.exclusion,
            embedding_model=EMBEDDING_MODEL,
        )
    elif cfg["mode"] == "matmul":
        filter_sql = pools.CANDIDATE_FILTERS[cfg["candidate_pool"]]
        print(f"      loading candidate pool into RAM...", flush=True)
        pool = topk_matmul.load_candidate_pool(
            conn, filter_sql, embedding_model=EMBEDDING_MODEL,
        )
        print(f"      pool: {len(pool.statement_ids):,} rows, "
              f"matrix shape {pool.matrix.shape}", flush=True)
        result_stream = topk_matmul.embedding_topk_matmul(
            conn, queries, pool,
            k=cfg["k"], exclusion=args.exclusion,
            embedding_model=EMBEDDING_MODEL,
        )
    else:
        raise SystemExit(f"unknown mode: {cfg['mode']}")

    # Stream writes: flush every WRITE_FLUSH_EVERY queries so a mid-run
    # crash leaves the table in a partially-populated but useful state.
    # Idempotent upsert on the PK means a restart with the same args
    # safely overwrites prior partial rows.
    pending: List = []
    queries_done = 0
    for results in result_stream:
        queries_done += 1
        if not results:
            empty += 1
        else:
            pending.extend(results)
        if queries_done % WRITE_FLUSH_EVERY == 0 and pending:
            n = store.write_rows(
                conn, pending,
                direction=args.direction, exclusion=args.exclusion,
                pool_descriptor=cfg["pool_descriptor"],
                embedding_model=EMBEDDING_MODEL,
            )
            total_written += n
            pending.clear()
            print(f"      [{queries_done}/{len(queries)}] flushed "
                  f"{total_written} rows so far", flush=True)
    if pending:
        n = store.write_rows(
            conn, pending,
            direction=args.direction, exclusion=args.exclusion,
            pool_descriptor=cfg["pool_descriptor"],
            embedding_model=EMBEDDING_MODEL,
        )
        total_written += n

    elapsed = time.perf_counter() - t0
    print(f"      done. {total_written} rows in {elapsed:.1f}s "
          f"({elapsed/max(1,len(queries))*1000:.0f} ms/q, "
          f"{empty} empty)", flush=True)
    conn.close()
    print(f"done.", flush=True)


if __name__ == "__main__":
    main()
