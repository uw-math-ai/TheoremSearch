"""Strand (G) — random non-gold project formals → top-K informals.

Samples N project formals that are NOT in the blueprint gold set, then
runs each as an f→i query against the full 11.7M informal pool via the
same binary-quantized HNSW shortlist + cosine rerank used in
run_gold_pair_sweep.py (direction='f2i', pool='all_informals').

Purpose: characterize the rank-1 similarity *distribution* outside the
gold subset. Without a gold partner we cannot compute Hit@k, but a few
useful things drop out:
  - shape of the sim distribution (does it bimodal between "real match"
    and "topical neighbour"?)
  - very-high-sim non-gold matches → blueprint-annotation backfill
    candidates beyond the 45 mutual-NN ones already surfaced
  - cross-source matches (Lean Repo ↔ arxiv etc.) that the project's
    authors may not be aware of

Writes:
  direction='f2i', exclusion='statement',
  pool_descriptor='nongold_random_f2i'

Wall (n=1000, ann_k=50): ~15 min based on f2i benchmark (22 min for 1,562).

Usage:
    python -m experiments.nl_fl_matching.runners.run_nongold_random_f2i \
        --n 1000 --seed 42
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "rds"))

from utils.connect import get_rds_connection  # noqa: E402

from experiments.nl_fl_matching import gold, pools, store, topk  # noqa: E402

EMBEDDING_MODEL = "qwen3-8b"
DIRECTION       = "f2i"
EXCLUSION       = "statement"
POOL            = "all_informals"
ANN_K           = 50
K               = 10
WRITE_FLUSH_EVERY = 100


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=1000)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--pool-descriptor", default="nongold_random_f2i")
    args = p.parse_args()

    rng = random.Random(args.seed)
    conn = get_rds_connection("v2")
    store.ensure_table(conn)

    print(f"[1/4] loading gold pairs (for exclusion)...", flush=True)
    t0 = time.perf_counter()
    g = gold.load_gold(conn, embedding_model=EMBEDDING_MODEL)
    gold_formal_sids = {fid for _, fid in g.pairs}
    print(f"      {len(gold_formal_sids):,} gold formal SIDs "
          f"({time.perf_counter()-t0:.1f}s)", flush=True)

    print(f"[2/4] fetching all {args.n}+ candidate formals...", flush=True)
    t0 = time.perf_counter()
    all_formals = pools.fetch_project_formals(conn, embedding_model=EMBEDDING_MODEL)
    pool_nongold = [s for s in all_formals if s.statement_id not in gold_formal_sids]
    print(f"      {len(all_formals):,} project formals, "
          f"{len(pool_nongold):,} non-gold ({time.perf_counter()-t0:.1f}s)", flush=True)

    rng.shuffle(pool_nongold)
    queries = pool_nongold[: args.n]
    print(f"      sampled {len(queries)} queries (seed={args.seed})", flush=True)

    cleared = store.clear_run(
        conn, direction=DIRECTION, exclusion=EXCLUSION,
        embedding_model=EMBEDDING_MODEL, pool_descriptor=args.pool_descriptor,
    )
    if cleared:
        print(f"      cleared {cleared} prior rows", flush=True)

    print(f"[3/4] running ANN topk vs '{POOL}' (ann_k={ANN_K}, k={K})...", flush=True)
    t0 = time.perf_counter()
    stream = topk.embedding_topk(
        conn, queries,
        candidate_pool=POOL,
        k=K, ann_k=ANN_K,
        exclusion=EXCLUSION,
        embedding_model=EMBEDDING_MODEL,
    )

    pending: List = []
    queries_done = 0
    total_written = 0
    empty = 0
    for results in stream:
        queries_done += 1
        if not results:
            empty += 1
        else:
            pending.extend(results)
        if queries_done % WRITE_FLUSH_EVERY == 0 and pending:
            n = store.write_rows(
                conn, pending,
                direction=DIRECTION, exclusion=EXCLUSION,
                pool_descriptor=args.pool_descriptor,
                embedding_model=EMBEDDING_MODEL,
            )
            total_written += n
            pending.clear()
            elapsed = time.perf_counter() - t0
            print(f"      [{queries_done}/{len(queries)}] wrote {total_written:,} "
                  f"({elapsed:.0f}s elapsed, "
                  f"{queries_done/max(elapsed,1):.1f} q/s)", flush=True)
    if pending:
        n = store.write_rows(
            conn, pending,
            direction=DIRECTION, exclusion=EXCLUSION,
            pool_descriptor=args.pool_descriptor,
            embedding_model=EMBEDDING_MODEL,
        )
        total_written += n

    elapsed = time.perf_counter() - t0
    print(f"[4/4] done. {queries_done:,} queries, {total_written:,} rows, "
          f"{empty} empty, {elapsed:.0f}s "
          f"({elapsed*1000/max(1,queries_done):.0f} ms/q)", flush=True)
    conn.close()


if __name__ == "__main__":
    main()
