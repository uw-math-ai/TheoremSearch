#!/usr/bin/env python3
"""
Build cycle-consistency experiment data for the Observable dashboard.
Reads experiments/cycle_consistency_pilot/results.csv and emits
src/data/cycle_consistency.json.

Usage (from the observable_dashboard directory):
    python3 build_cycle_data.py [--out src/data]
"""

import argparse
import csv
import json
from pathlib import Path
from collections import defaultdict

REPO = Path(__file__).resolve().parents[2]
RESULTS = REPO / "experiments/cycle_consistency_pilot/results.csv"
DESIGN  = REPO / "experiments/cycle_consistency_pilot/design.md"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="src/data", help="Output directory")
    args = parser.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = list(csv.DictReader(open(RESULTS)))

    # ── Per-candidate records (for the detail table) ──────────────────────────
    candidates = []
    for r in rows:
        candidates.append({
            "node_id":      int(r["node_id"]),
            "full_name":    r["full_name"],
            "short_name":   r["full_name"].split(".")[-1],
            "indeg":        r["stratum_indeg"],
            "size":         r["stratum_size"],
            "dep_count":    int(r["dep_count"]),
            "dep_truncated": int(r["dep_truncated"]),
            "prefer":       r["judge_prefer"],
            "judge_notes":  r["judge_notes"],
            "vacuous_B":    r["vacuous_B"] == "True",
            "vacuous_T":    r["vacuous_T"] == "True",
            "edit_dist_B":  int(r["edit_dist_B"]),
            "edit_dist_T":  int(r["edit_dist_T"]),
            # Keep NL and formalization outputs for hover/detail
            "NL":           r["NL"],
            "F_sig":        r["F_signature"],
            "F_B":          r["F_B"],
            "F_T":          r["F_T"],
        })

    # ── Summary ───────────────────────────────────────────────────────────────
    n = len(candidates)
    t_count = sum(1 for c in candidates if c["prefer"] == "T")
    b_count = sum(1 for c in candidates if c["prefer"] == "B")
    tie_count = sum(1 for c in candidates if c["prefer"] == "tie")

    # Wilcoxon (compute here so the page doesn't need scipy)
    try:
        from scipy.stats import wilcoxon
        coded = [1 if c["prefer"] == "T" else (-1 if c["prefer"] == "B" else 0)
                 for c in candidates]
        non_zero = [x for x in coded if x != 0]
        if len(non_zero) >= 10:
            stat, pval = wilcoxon(coded)
            wilcoxon_p = round(float(pval), 6)
            wilcoxon_stat = round(float(stat), 2)
        else:
            wilcoxon_p = None
            wilcoxon_stat = None
    except Exception:
        wilcoxon_p = None
        wilcoxon_stat = None

    import numpy as np
    eds_b = [c["edit_dist_B"] for c in candidates]
    eds_t = [c["edit_dist_T"] for c in candidates]

    summary = {
        "n": n,
        "t_count": t_count,
        "b_count": b_count,
        "tie_count": tie_count,
        "t_pct": round(100 * t_count / n, 1),
        "b_pct": round(100 * b_count / n, 1),
        "tie_pct": round(100 * tie_count / n, 1),
        "wilcoxon_stat": wilcoxon_stat,
        "wilcoxon_p": wilcoxon_p,
        "vacuous_rate_B": round(100 * sum(c["vacuous_B"] for c in candidates) / n, 1),
        "vacuous_rate_T": round(100 * sum(c["vacuous_T"] for c in candidates) / n, 1),
        "edit_mean_B": round(float(np.mean(eds_b)), 1),
        "edit_mean_T": round(float(np.mean(eds_t)), 1),
        "edit_median_B": float(np.median(eds_b)),
        "edit_median_T": float(np.median(eds_t)),
        "models": {
            "informalizer": "claude-sonnet-4-5 (Bedrock)",
            "formalizer":   "claude-haiku-4-5 (Bedrock, same for B and T)",
            "judge":        "claude-sonnet-4-5 (Bedrock)",
        },
        "strata_cutoffs": {
            "p25_indeg": 0, "p75_indeg": 4,
            "p25_siglen": 124, "p75_siglen": 314,
        },
        "seed": 42,
    }

    # ── Stratified breakdown ──────────────────────────────────────────────────
    cell_stats = defaultdict(lambda: {"T": 0, "B": 0, "tie": 0, "n": 0})
    for c in candidates:
        key = (c["indeg"], c["size"])
        cell_stats[key][c["prefer"]] += 1
        cell_stats[key]["n"] += 1

    strata = []
    for (indeg, size), cs in sorted(cell_stats.items()):
        strata.append({
            "indeg": indeg,
            "size": size,
            "cell": f"{indeg} × {size}",
            "n": cs["n"],
            "T": cs["T"],
            "B": cs["B"],
            "tie": cs["tie"],
            "t_pct": round(100 * cs["T"] / cs["n"], 1) if cs["n"] else 0,
        })

    # ── Edit-distance scatter (one point per candidate per condition) ─────────
    edit_scatter = []
    for c in candidates:
        edit_scatter.append({
            "full_name": c["full_name"],
            "indeg": c["indeg"],
            "size": c["size"],
            "prefer": c["prefer"],
            "dep_count": c["dep_count"],
            "edit_dist": c["edit_dist_B"],
            "condition": "B (baseline)",
        })
        edit_scatter.append({
            "full_name": c["full_name"],
            "indeg": c["indeg"],
            "size": c["size"],
            "prefer": c["prefer"],
            "dep_count": c["dep_count"],
            "edit_dist": c["edit_dist_T"],
            "condition": "T (treatment)",
        })

    out = {
        "summary": summary,
        "candidates": candidates,
        "strata": strata,
        "edit_scatter": edit_scatter,
    }

    outfile = out_dir / "cycle_consistency.json"
    with open(outfile, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Wrote {outfile} ({outfile.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
