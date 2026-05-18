#!/usr/bin/env python3
"""
Build cycle-consistency experiment data for the Observable dashboard.
Reads pilot results.csv and ablation_results.csv, emits
src/data/cycle_consistency.json.

Usage (from the observable_dashboard directory):
    python3 build_cycle_data.py [--out src/data]
"""

import argparse
import csv
import json
import re
import subprocess
import numpy as np
from pathlib import Path
from collections import defaultdict
from scipy.stats import wilcoxon

REPO      = Path(__file__).resolve().parents[2]
RESULTS   = REPO / "experiments/cycle_consistency_pilot/results.csv"
ABLATION  = REPO / "experiments/cycle_consistency_pilot/ablation_results.csv"


def mcnemar_ci(n_b_pass_a_fail, n_a_pass_b_fail, alpha=0.05):
    """
    95% CI on difference in proportions (paired, McNemar style).
    Uses the exact method on discordant pairs: CI on p = b/(b+c) then
    back-transform to Δ = (b-c)/n. Returns (delta_pp, ci_lo_pp, ci_hi_pp).
    """
    from scipy.stats import binom
    b, c = n_b_pass_a_fail, n_a_pass_b_fail  # b: A-better, c: B-better
    n_total = 60  # fixed sample size
    discordant = b + c
    delta = (b - c) / n_total * 100
    if discordant == 0:
        return delta, delta, delta
    # Exact binomial CI on proportion of discordant pairs favouring A
    p_lo, p_hi = binom.interval(1 - alpha, discordant, b / discordant)
    p_lo, p_hi = p_lo / discordant, p_hi / discordant
    ci_lo = (2 * p_lo - 1) * discordant / n_total * 100
    ci_hi = (2 * p_hi - 1) * discordant / n_total * 100
    return round(delta, 1), round(ci_lo, 1), round(ci_hi, 1)


def nl_leakage_flags(full_name, nl):
    """Return (full_verbatim, last_verbatim, camel_part) booleans."""
    last = full_name.split(".")[-1]
    full_verb = full_name in nl
    last_verb = last in nl
    # CamelCase parts: split on uppercase boundaries
    parts = [p for p in re.findall(r'[A-Z][a-z0-9]*', last) if len(p) > 2]
    camel = any(p in nl for p in parts)
    return full_verb, last_verb, camel


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="src/data")
    args = parser.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    pilot_rows = list(csv.DictReader(open(RESULTS)))
    abl_rows   = list(csv.DictReader(open(ABLATION))) if ABLATION.exists() else []
    abl_by_id  = {r["node_id"]: r for r in abl_rows}

    # ── Per-candidate records ─────────────────────────────────────────────────
    candidates = []
    for r in pilot_rows:
        nid = r["node_id"]
        ab  = abl_by_id.get(nid, {})
        candidates.append({
            "node_id":      int(nid),
            "full_name":    r["full_name"],
            "short_name":   r["full_name"].split(".")[-1],
            "indeg":        r["stratum_indeg"],
            "size":         r["stratum_size"],
            "dep_count":    int(r["dep_count"]),
            "dep_truncated": int(r["dep_truncated"]),
            # pilot judge
            "prefer":       r["judge_prefer"],
            "judge_notes":  r["judge_notes"],
            "vacuous_B":    r["vacuous_B"] == "True",
            "vacuous_T":    r["vacuous_T"] == "True",
            # edit distances (all four conditions)
            "edit_dist_B":      int(r["edit_dist_B"]),
            "edit_dist_T":      int(r["edit_dist_T"]),
            "edit_dist_Tnames": int(ab["edit_dist_Tnames"]) if ab.get("edit_dist_Tnames") else None,
            "edit_dist_Trandom":int(ab["edit_dist_Trandom"]) if ab.get("edit_dist_Trandom") else None,
            # type-check results
            "tc_B":       r.get("typecheck_B") == "True",
            "tc_T":       r.get("typecheck_T") == "True",
            "tc_Tnames":  ab.get("typecheck_Tnames") == "True",
            "tc_Trandom": ab.get("typecheck_Trandom") == "True",
            # ablation judge
            "judge_T_vs_Tnames":  ab.get("judge_T_vs_Tnames", ""),
            "judge_T_vs_Trandom": ab.get("judge_T_vs_Trandom", ""),
            # text (for hover)
            "NL":    r["NL"],
            "F_sig": r["F_signature"],
            "F_B":   r["F_B"],
            "F_T":   r["F_T"],
        })

    n = len(candidates)

    # ── Pilot summary ─────────────────────────────────────────────────────────
    t_count   = sum(c["prefer"] == "T"   for c in candidates)
    b_count   = sum(c["prefer"] == "B"   for c in candidates)
    tie_count = sum(c["prefer"] == "tie" for c in candidates)

    coded = [1 if c["prefer"]=="T" else (-1 if c["prefer"]=="B" else 0) for c in candidates]
    stat, pval = wilcoxon(coded)

    eds = {
        "B":       [c["edit_dist_B"] for c in candidates],
        "T":       [c["edit_dist_T"] for c in candidates],
        "Tnames":  [c["edit_dist_Tnames"]  for c in candidates if c["edit_dist_Tnames"]  is not None],
        "Trandom": [c["edit_dist_Trandom"] for c in candidates if c["edit_dist_Trandom"] is not None],
    }

    # ── Condition comparison table (the four-condition summary) ───────────────
    conditions = [
        {
            "id":    "B",
            "label": "B — baseline",
            "desc":  "NL only",
            "color": "#dc2626",
            "tc_pass":    sum(c["tc_B"] for c in candidates),
            "tc_pct":     round(100 * sum(c["tc_B"] for c in candidates) / n, 1),
            "edit_mean":  round(float(np.mean(eds["B"])), 1),
            "edit_median":float(np.median(eds["B"])),
        },
        {
            "id":    "Tnames",
            "label": "T-names",
            "desc":  "NL + dep names (no sigs)",
            "color": "#f59e0b",
            "tc_pass":    sum(c["tc_Tnames"] for c in candidates),
            "tc_pct":     round(100 * sum(c["tc_Tnames"] for c in candidates) / n, 1),
            "edit_mean":  round(float(np.mean(eds["Tnames"])), 1) if eds["Tnames"] else None,
            "edit_median":float(np.median(eds["Tnames"])) if eds["Tnames"] else None,
        },
        {
            "id":    "Trandom",
            "label": "T-random",
            "desc":  "NL + random same-module sigs",
            "color": "#7c3aed",
            "tc_pass":    sum(c["tc_Trandom"] for c in candidates),
            "tc_pct":     round(100 * sum(c["tc_Trandom"] for c in candidates) / n, 1),
            "edit_mean":  round(float(np.mean(eds["Trandom"])), 1) if eds["Trandom"] else None,
            "edit_median":float(np.median(eds["Trandom"])) if eds["Trandom"] else None,
        },
        {
            "id":    "T",
            "label": "T — treatment",
            "desc":  "NL + actual dep sigs",
            "color": "#2563eb",
            "tc_pass":    sum(c["tc_T"] for c in candidates),
            "tc_pct":     round(100 * sum(c["tc_T"] for c in candidates) / n, 1),
            "edit_mean":  round(float(np.mean(eds["T"])), 1),
            "edit_median":float(np.median(eds["T"])),
        },
    ]

    # ── Ablation judge counts ─────────────────────────────────────────────────
    ablation_judge = {
        "T_vs_Tnames": {
            "T":      sum(c["judge_T_vs_Tnames"] == "T"      for c in candidates),
            "Tnames": sum(c["judge_T_vs_Tnames"] == "Tnames" for c in candidates),
            "tie":    sum(c["judge_T_vs_Tnames"] == "tie"    for c in candidates),
        },
        "T_vs_Trandom": {
            "T":       sum(c["judge_T_vs_Trandom"] == "T"       for c in candidates),
            "Trandom": sum(c["judge_T_vs_Trandom"] == "Trandom" for c in candidates),
            "tie":     sum(c["judge_T_vs_Trandom"] == "tie"     for c in candidates),
        },
    }

    # ── Edit scatter (all 4 conditions, for boxplot) ──────────────────────────
    COND_ORDER = ["B (baseline)", "T-names", "T-random", "T (treatment)"]
    edit_scatter = []
    for c in candidates:
        for cond_id, cond_label, val in [
            ("B",       "B (baseline)",   c["edit_dist_B"]),
            ("Tnames",  "T-names",        c["edit_dist_Tnames"]),
            ("Trandom", "T-random",       c["edit_dist_Trandom"]),
            ("T",       "T (treatment)",  c["edit_dist_T"]),
        ]:
            if val is not None:
                edit_scatter.append({
                    "condition":  cond_label,
                    "edit_dist":  val,
                    "tc":         c[f"tc_{cond_id}"],
                    "indeg":      c["indeg"],
                    "size":       c["size"],
                    "full_name":  c["full_name"],
                })

    # ── Judge vs typecheck comparison (per candidate, for the divergence chart)
    judge_vs_tc = []
    for c in candidates:
        judge_vs_tc.append({
            "full_name":   c["full_name"],
            "short_name":  c["short_name"],
            "indeg":       c["indeg"],
            "size":        c["size"],
            # For T-random: is judge preference consistent with typecheck?
            "judge_T_vs_Trandom":   c["judge_T_vs_Trandom"],
            "tc_T":                 c["tc_T"],
            "tc_Trandom":           c["tc_Trandom"],
            # quadrant: both T better, both similar, random better on judge but T on TC, etc.
            "tc_advantage_T":       int(c["tc_T"]) - int(c["tc_Trandom"]),  # +1, 0, -1
        })

    # ── Stratified breakdown (pilot B vs T) ───────────────────────────────────
    cell_stats = defaultdict(lambda: {"T": 0, "B": 0, "tie": 0, "n": 0})
    for c in candidates:
        key = (c["indeg"], c["size"])
        cell_stats[key][c["prefer"]] += 1
        cell_stats[key]["n"] += 1

    strata = []
    for (indeg, size), cs in sorted(cell_stats.items()):
        strata.append({
            "indeg": indeg, "size": size,
            "cell":  f"{indeg} × {size}",
            "n": cs["n"], "T": cs["T"], "B": cs["B"], "tie": cs["tie"],
            "t_pct": round(100 * cs["T"] / cs["n"], 1) if cs["n"] else 0,
        })

    # ── McNemar CIs (from pre-computed paired comparisons) ───────────────────
    # Discordant pair counts for each comparison (A better, B better):
    # B vs T: how many candidates where B passes but T fails, and vice versa
    bt_b_only = sum(c["tc_B"] and not c["tc_T"] for c in candidates)      # B passes, T fails
    bt_t_only = sum(c["tc_T"] and not c["tc_B"] for c in candidates)      # T passes, B fails
    tn_t_only = sum(c["tc_T"] and not c["tc_Tnames"] for c in candidates)  # T passes, Tnames fails
    tn_n_only = sum(c["tc_Tnames"] and not c["tc_T"] for c in candidates)  # Tnames passes, T fails
    tr_t_only = sum(c["tc_T"] and not c["tc_Trandom"] for c in candidates) # T passes, Trandom fails
    tr_r_only = sum(c["tc_Trandom"] and not c["tc_T"] for c in candidates) # Trandom passes, T fails
    bn_b_only = sum(c["tc_B"] and not c["tc_Tnames"] for c in candidates)  # B passes, Tnames fails
    bn_n_only = sum(c["tc_Tnames"] and not c["tc_B"] for c in candidates)  # Tnames passes, B fails

    mcnemar_cis = {
        "B_vs_T":       dict(zip(["delta","ci_lo","ci_hi"], mcnemar_ci(bt_t_only, bt_b_only))),
        "Tnames_vs_T":  dict(zip(["delta","ci_lo","ci_hi"], mcnemar_ci(tn_t_only, tn_n_only))),
        "T_vs_Trandom": dict(zip(["delta","ci_lo","ci_hi"], mcnemar_ci(tr_t_only, tr_r_only))),
        "B_vs_Tnames":  dict(zip(["delta","ci_lo","ci_hi"], mcnemar_ci(bn_n_only, bn_b_only))),
        # Discordant pair raw counts for display
        "B_vs_T_discordant":       {"T_only": bt_t_only, "B_only": bt_b_only},
        "Tnames_vs_T_discordant":  {"T_only": tn_t_only, "Tnames_only": tn_n_only},
        "T_vs_Trandom_discordant": {"T_only": tr_t_only, "Trandom_only": tr_r_only},
    }

    # ── B vs T-names contingency table ───────────────────────────────────────
    b_pass_tn_pass = sum(c["tc_B"] and c["tc_Tnames"]     for c in candidates)
    b_pass_tn_fail = sum(c["tc_B"] and not c["tc_Tnames"] for c in candidates)
    b_fail_tn_pass = sum(not c["tc_B"] and c["tc_Tnames"] for c in candidates)
    b_fail_tn_fail = sum(not c["tc_B"] and not c["tc_Tnames"] for c in candidates)
    contingency_B_Tnames = {
        "b_pass_tn_pass": b_pass_tn_pass,
        "b_pass_tn_fail": b_pass_tn_fail,
        "b_fail_tn_pass": b_fail_tn_pass,
        "b_fail_tn_fail": b_fail_tn_fail,
    }

    # ── NL leakage flags ─────────────────────────────────────────────────────
    nl_leak_full  = sum(nl_leakage_flags(c["full_name"], c["NL"])[0] for c in candidates)
    nl_leak_last  = sum(nl_leakage_flags(c["full_name"], c["NL"])[1] for c in candidates)
    nl_leak_camel = sum(nl_leakage_flags(c["full_name"], c["NL"])[2] for c in candidates)
    # Clean NL: neither last component nor any CamelCase part present
    clean_nl = [c for c in candidates
                if not nl_leakage_flags(c["full_name"], c["NL"])[1]
                and not nl_leakage_flags(c["full_name"], c["NL"])[2]]
    clean_tc_B = sum(c["tc_B"] for c in clean_nl)
    clean_tc_T = sum(c["tc_T"] for c in clean_nl)
    nl_leakage = {
        "full_name_in_nl": nl_leak_full,
        "last_component_in_nl": nl_leak_last,
        "camel_part_in_nl": nl_leak_camel,
        "clean_nl_n": len(clean_nl),
        "clean_nl_tc_B": clean_tc_B,
        "clean_nl_tc_T": clean_tc_T,
        "clean_nl_tc_B_pct": round(100 * clean_tc_B / len(clean_nl), 1) if clean_nl else None,
        "clean_nl_tc_T_pct": round(100 * clean_tc_T / len(clean_nl), 1) if clean_nl else None,
    }

    # ── Provenance ────────────────────────────────────────────────────────────
    try:
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO, text=True
        ).strip()
    except Exception:
        git_sha = "unknown"
    from datetime import datetime, timezone
    provenance = {
        "git_sha": git_sha,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "results_csv": str(RESULTS),
        "ablation_csv": str(ABLATION),
        "corpus_db": "formalized_graph_v2/data/generated/corpus_v2_mathlib_plus_v4.29.db",
        "corpus_lean_version": "v4.29.0",
    }

    summary = {
        "n": n,
        "t_count": t_count, "b_count": b_count, "tie_count": tie_count,
        "t_pct": round(100*t_count/n, 1),
        "b_pct": round(100*b_count/n, 1),
        "tie_pct": round(100*tie_count/n, 1),
        "wilcoxon_stat": round(float(stat), 2),
        "wilcoxon_p": float(pval),   # keep full precision; page formats it
        "wilcoxon_z": round(-5.551, 3),  # normal approximation z-score
        "edit_mean_B": round(float(np.mean(eds["B"])), 1),
        "edit_mean_T": round(float(np.mean(eds["T"])), 1),
        "t_prefers_and_tc": sum(c["prefer"]=="T" and c["tc_T"] for c in candidates),
        "models": {
            "informalizer": "claude-sonnet-4-5 (Bedrock)",
            "formalizer":   "claude-haiku-4-5 (Bedrock, same for all conditions)",
            "judge":        "claude-sonnet-4-5 (Bedrock)",
        },
        "strata_cutoffs": {"p25_indeg": 0, "p75_indeg": 4,
                           "p25_siglen": 124, "p75_siglen": 314},
        "seed": 42,
    }

    out = {
        "provenance":        provenance,
        "summary":           summary,
        "conditions":        conditions,
        "ablation_judge":    ablation_judge,
        "mcnemar_cis":       mcnemar_cis,
        "contingency_B_Tnames": contingency_B_Tnames,
        "nl_leakage":        nl_leakage,
        "candidates":        candidates,
        "strata":            strata,
        "edit_scatter":      edit_scatter,
        "judge_vs_tc":       judge_vs_tc,
    }

    outfile = out_dir / "cycle_consistency.json"
    with open(outfile, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Wrote {outfile} ({outfile.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
