"""Blueprint-matching experiment.

Runs four questions over the slogan-embedding ↔ basic-NLP matching of
informal blueprint statements to their `\\lean`-referenced formal
counterparts, writing each result as a self-contained ASCII text file
next to this module (q1.txt … q4.txt).

Usage::

    python -m experiments.blueprint_matching
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from rds.utils.connect import get_rds_connection

from . import q1, q2, q3, q4
from ._shared import MatchedPools, compute_similarities
from .data import build_ground_truth, fetch_formal, fetch_informal


OUT_DIR = Path(__file__).parent


def _load_pools(conn, embedding_model: str) -> MatchedPools:
    t0 = time.perf_counter()
    informal = fetch_informal(conn)
    formal   = fetch_formal(conn)
    truth    = build_ground_truth(informal, formal)
    print(
        f"loaded {len(informal):,} informals (with \\lean), "
        f"{len(formal):,} formals, "
        f"{len(truth):,} ground-truth pairs "
        f"({time.perf_counter() - t0:.1f}s)",
        flush=True,
    )

    # Restrict both pools to statements that appear in some ground-truth pair.
    # This keeps the similarity matrices tractable and matches the evaluation
    # universe used in score().
    matched_inf = {a for a, _ in truth}
    matched_fml = {b for _, b in truth}
    informal = [s for s in informal if s.statement_id in matched_inf]
    formal   = [s for s in formal   if s.statement_id in matched_fml]
    print(f"  matched subset: {len(informal):,} × {len(formal):,}", flush=True)

    t0 = time.perf_counter()
    sims = compute_similarities(informal, formal, conn, embedding_model)
    print(f"  computed {len(sims)} similarity matrices "
          f"({time.perf_counter() - t0:.1f}s)", flush=True)

    return MatchedPools(
        informal=informal,
        formal=formal,
        informal_ids=[s.statement_id for s in informal],
        formal_ids  =[s.statement_id for s in formal],
        truth=truth,
        sims=sims,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--embedding-model", default="qwen3-8b",
        help="embedding_model.name in RDS. Default: qwen3-8b.",
    )
    parser.add_argument(
        "--q4-seed", type=int, default=0,
        help="RNG seed for Q4's stratified sample. Default: 0.",
    )
    args = parser.parse_args()

    import sys
    sys.stdout.reconfigure(line_buffering=True)

    conn  = get_rds_connection("v2")
    pools = _load_pools(conn, args.embedding_model)
    print("  pools loaded; entering question loop", flush=True)

    runners = [
        (q1, lambda: q1.run(pools)),
        (q2, lambda: q2.run(pools)),
        (q3, lambda: q3.run(pools)),
        (q4, lambda: q4.run(pools, conn, args.embedding_model, rng_seed=args.q4_seed)),
    ]
    for mod, runner in runners:
        print(f"  ▶ {mod.NAME} starting", flush=True)
        t0 = time.perf_counter()
        body = runner()
        print(f"  ▶ {mod.NAME} finished in {time.perf_counter() - t0:.1f}s, writing...",
              flush=True)
        path = OUT_DIR / f"{mod.NAME}.txt"
        path.write_text(body)
        print(f"  ✓ wrote {path}", flush=True)


if __name__ == "__main__":
    main()
