"""Compare BM25 baseline against qwen3-8b embedding on the same gold sets.

Loads gold using `embedding_model='qwen3-8b'` (gold definition is
embedding-independent), then evaluates *both* the qwen3-8b sweep rows
and the bm25 sweep rows against it. Reports Hit@1/5/10 + MRR@10 side
by side with bootstrap 95% CIs.

This wraps around `eval.score_direction` + `bootstrap_ci.bootstrap_fraction`.

Reproduce:
    python -m experiments.nl_fl_matching.analysis.bm25_vs_embedding
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "rds"))

from utils.connect import get_rds_connection  # noqa: E402
from experiments.nl_fl_matching import gold  # noqa: E402
from experiments.nl_fl_matching.analysis.eval import fetch_rows  # noqa: E402
from experiments.nl_fl_matching.analysis.bootstrap_ci import (  # noqa: E402
    _per_query_hit, bootstrap_fraction, fmt_pct,
)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--resamples", type=int, default=2000)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out-json", type=Path,
                   default=REPO_ROOT / "experiments/nl_fl_matching/data/bm25_vs_embedding.json")
    p.add_argument("--out-md", type=Path,
                   default=REPO_ROOT / "experiments/nl_fl_matching/data/bm25_vs_embedding.md")
    args = p.parse_args()
    rng = np.random.default_rng(args.seed)

    conn = get_rds_connection("v2")
    print("loading gold (qwen3-8b)...", flush=True)
    g = gold.load_gold(conn, embedding_model="qwen3-8b")

    # Pull every sweep.
    sweeps = [
        ("qwen3-8b — f→i (vs 11.7M)",
         "f2i", "qwen3-8b", "gold_subset_f2i", g.formal_to_gold_informals),
        ("bm25 — f→i (vs 2,544 blueprint)",
         "f2i", "bm25", "gold_subset_f2i_bm25_blueprint", g.formal_to_gold_informals),
        ("qwen3-8b — i→f (vs 36,708 projformal)",
         "i2f", "qwen3-8b", "gold_subset_i2f", g.informal_to_gold_formals),
        ("bm25 — i→f (vs 36,708 projformal)",
         "i2f", "bm25", "gold_subset_i2f_bm25_projformal", g.informal_to_gold_formals),
    ]

    result = {"resamples": args.resamples, "seed": args.seed, "rows": []}
    print()
    for label, direction, model, pool, lookup in sweeps:
        print(f"== {label} ==", flush=True)
        ranks = fetch_rows(conn, direction, model,
                           pool_descriptor=pool, exclusion="statement")
        pq = _per_query_hit(ranks, lookup, k_max=10)
        if not pq:
            print("  (no evaluable queries)")
            continue
        h1  = [r[0] for r in pq]
        h5  = [r[1] for r in pq]
        h10 = [r[2] for r in pq]
        rr  = [r[3] for r in pq]
        scores = {
            "n":      len(pq),
            "hit@1":  bootstrap_fraction(h1, args.resamples, rng),
            "hit@5":  bootstrap_fraction(h5, args.resamples, rng),
            "hit@10": bootstrap_fraction(h10, args.resamples, rng),
            "mrr@10": bootstrap_fraction(rr, args.resamples, rng),
        }
        for k in ("hit@1", "hit@5", "hit@10", "mrr@10"):
            t = scores[k]
            print(f"  {k:<8}  n={scores['n']:<5} {fmt_pct(*t)}")
        result["rows"].append({"label": label, "direction": direction,
                               "model": model, "pool": pool, **scores})

    conn.close()

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(result, indent=2))
    print(f"\nwrote {args.out_json}")

    # Markdown table.
    rows = result["rows"]
    md = ["# BM25 baseline vs qwen3-8b embedding\n"]
    md.append(f"Bootstrap 95% CIs over {args.resamples} resamples. "
              "Gold definition (1,595 blueprint pairs) is "
              "embedding-independent; both retrievers evaluated against the "
              "same gold set.\n")
    md.append("| sweep | n | Hit@1 | Hit@5 | Hit@10 | MRR@10 |")
    md.append("|---|---:|---:|---:|---:|---:|")
    for r in rows:
        md.append(f"| {r['label']} | {r['n']} | "
                  f"{fmt_pct(*r['hit@1'])} | "
                  f"{fmt_pct(*r['hit@5'])} | "
                  f"{fmt_pct(*r['hit@10'])} | "
                  f"{fmt_pct(*r['mrr@10'])} |")
    args.out_md.write_text("\n".join(md) + "\n")
    print(f"wrote {args.out_md}")


if __name__ == "__main__":
    main()
