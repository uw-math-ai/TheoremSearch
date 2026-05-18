#!/usr/bin/env python3
"""
Ablation on a non-Mathlib project's pilot results.

Reads results_{project}.csv (produced by run_extension.py), reuses the
same 60 candidates and NLs, runs T-names and T-random formalizations,
judges each against T. Writes ablation_results_{project}.csv.

Usage:
    python3 run_extension_ablation.py --project combinatorial-games [--dry-run]
"""

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
import anthropic

sys.path.insert(0, str(Path(__file__).parent))
from run_ablation import (
    get_conn, get_module, get_dep_names_only_context, get_random_module_context,
    formalize_names_only, formalize_random, run_judged_pair,
    token_levenshtein, FORMALIZER_MODEL, JUDGE_MODEL,
)

REPO = Path(__file__).resolve().parents[2]
OUT  = Path(__file__).parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(REPO / ".env")
    if args.dry_run:
        client = None
        print("[DRY RUN]")
    else:
        client = anthropic.AnthropicBedrock(
            aws_region=os.environ.get("AWS_REGION", "us-west-2"),
            aws_access_key=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        )

    pilot_csv = OUT / f"results_{args.project}.csv"
    pilot_rows = list(csv.DictReader(open(pilot_csv)))
    print(f"Loaded {len(pilot_rows)} candidates from {pilot_csv.name}")

    conn = get_conn()
    results = []
    judge_map = {}
    t0 = time.time()

    for i, pr in enumerate(pilot_rows):
        nid    = int(pr["node_id"])
        fname  = pr["full_name"]
        fsig   = pr["F_signature"]
        nl     = pr["NL"]
        f_t    = pr["F_T"]
        dep_count = int(pr["dep_count"])

        print(f"[{i+1}/{len(pilot_rows)}] {fname[:70]}")

        names_ctx, names_cnt, names_trunc = get_dep_names_only_context(conn, nid)
        module = get_module(conn, nid)
        rand_ctx, rand_cnt, rand_trunc = get_random_module_context(conn, nid, dep_count, module)

        try:
            f_tnames, _ = formalize_names_only(client, nl, names_ctx, dry_run=args.dry_run)
        except Exception as e:
            print(f"  SKIP T-names: {e}"); continue

        try:
            f_trandom, _ = formalize_random(client, nl, rand_ctx, dry_run=args.dry_run)
        except Exception as e:
            print(f"  SKIP T-random: {e}"); continue

        try:
            pref_tnames, notes_tn, vac_t1, vac_tnames, a_is_t1 = run_judged_pair(
                client, fsig, f_t, f_tnames, dry_run=args.dry_run)
        except Exception as e:
            print(f"  SKIP judge T-vs-Tnames: {e}"); continue
        prefer_tnames_label = "T" if pref_tnames == "X" else ("Tnames" if pref_tnames == "Y" else "tie")

        try:
            pref_trandom, notes_tr, vac_t2, vac_trandom, a_is_t2 = run_judged_pair(
                client, fsig, f_t, f_trandom, dry_run=args.dry_run)
        except Exception as e:
            print(f"  SKIP judge T-vs-Trandom: {e}"); continue
        prefer_trandom_label = "T" if pref_trandom == "X" else ("Trandom" if pref_trandom == "Y" else "tie")

        judge_map[nid] = {"T_vs_Tnames_a_is_T": a_is_t1, "T_vs_Trandom_a_is_T": a_is_t2}

        results.append({
            "node_id":      nid,
            "full_name":    fname,
            "F_signature":  fsig,
            "NL":           nl,
            "F_T":          f_t,
            "dep_count":    dep_count,
            "F_Tnames":     f_tnames,
            "dep_names_count": names_cnt,
            "judge_T_vs_Tnames":       prefer_tnames_label,
            "judge_T_vs_Tnames_notes": notes_tn,
            "vacuous_Tnames":          vac_tnames,
            "edit_dist_Tnames":        token_levenshtein(fsig, f_tnames),
            "F_Trandom":    f_trandom,
            "rand_count":   rand_cnt,
            "judge_T_vs_Trandom":       prefer_trandom_label,
            "judge_T_vs_Trandom_notes": notes_tr,
            "vacuous_Trandom":          vac_trandom,
            "edit_dist_Trandom":        token_levenshtein(fsig, f_trandom),
        })

    out_csv = OUT / f"ablation_results_{args.project}.csv"
    if results:
        with open(out_csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
            w.writeheader()
            w.writerows(results)
    (OUT / f"ablation_judge_label_map_{args.project}.json").write_text(json.dumps(judge_map, indent=2))

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.0f}s. {len(results)}/{len(pilot_rows)} candidates.")
    from collections import Counter
    print(f"T vs T-names:  {Counter(r['judge_T_vs_Tnames'] for r in results)}")
    print(f"T vs T-random: {Counter(r['judge_T_vs_Trandom'] for r in results)}")


if __name__ == "__main__":
    main()
