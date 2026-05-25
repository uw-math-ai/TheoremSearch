"""Audit an arbitrary (informal_sid, formal_sid) pair list using the same
dual-rater protocol as gold_pair_audit.py.

Reads a CSV with `informal_sid`, `formal_sid` columns and runs each pair
through Claude Sonnet 4.5 + Claude Haiku 4.5 (Bedrock), reusing
`gold_pair_audit.PROMPT`, `hydrate_pair`, `invoke_bedrock`,
`cohens_kappa`, `LABELS`.

Originally written to audit the 45 non-gold mutual rank-1 pairs
(`data/mutual_rank1_nongold.csv` → `data/mutual_nongold_audit.{csv,json}`)
so the 88.8% mutual-NN precision claim stops being circular.

Reproduce:
    python -m experiments.nl_fl_matching.analysis.audit_pairs_from_csv \\
        --in experiments/nl_fl_matching/data/mutual_rank1_nongold.csv \\
        --out-csv experiments/nl_fl_matching/data/mutual_nongold_audit.csv \\
        --out-json experiments/nl_fl_matching/data/mutual_nongold_audit.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "rds"))

import boto3
from dotenv import load_dotenv

from utils.connect import get_rds_connection  # noqa: E402
from experiments.nl_fl_matching.analysis.gold_pair_audit import (  # noqa: E402
    PROMPT, hydrate_pair, invoke_bedrock, cohens_kappa, LABELS,
    PRIMARY_MODEL, SECONDARY_MODEL, _trim,
)

load_dotenv()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="input_csv", type=Path, required=True)
    p.add_argument("--out-csv", type=Path, required=True)
    p.add_argument("--out-json", type=Path, required=True)
    p.add_argument("--informal-col", default="informal_sid")
    p.add_argument("--formal-col",   default="formal_sid")
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args()

    with args.input_csv.open() as fh:
        pairs = []
        for r in csv.DictReader(fh):
            inf = r[args.informal_col]
            fml = r[args.formal_col]
            pairs.append((inf, fml))
    if args.limit:
        pairs = pairs[: args.limit]
    print(f"loaded {len(pairs)} pairs from {args.input_csv}", flush=True)

    conn = get_rds_connection("v2")
    bedrock = boto3.client("bedrock-runtime",
                           region_name=os.getenv("AWS_REGION", "us-west-2"))

    rows = []
    t0 = time.perf_counter()
    for i, (inf_sid, fml_sid) in enumerate(pairs, 1):
        ctx = hydrate_pair(conn, inf_sid, fml_sid)
        prompt = PROMPT.format(
            informal_ref     = ctx.informal_ref or "(none)",
            informal_paper   = ctx.informal_paper or "(none)",
            informal_slogan  = _trim(ctx.informal_slogan, 600),
            informal_body    = _trim(ctx.informal_body, 1500),
            formal_decl_name = ctx.formal_decl_name or "(none)",
            formal_module    = ctx.formal_module or "(none)",
            formal_slogan    = _trim(ctx.formal_slogan, 600),
            formal_body      = _trim(ctx.formal_body, 1500),
        )
        try:
            primary = invoke_bedrock(bedrock, PRIMARY_MODEL, prompt)
        except Exception as e:
            primary = {"label": "ambiguous", "reason": f"primary_err: {e}"}
        try:
            secondary = invoke_bedrock(bedrock, SECONDARY_MODEL, prompt)
        except Exception as e:
            secondary = {"label": "ambiguous", "reason": f"secondary_err: {e}"}

        rows.append({
            "i":                i,
            "informal_sid":     inf_sid,
            "formal_sid":       fml_sid,
            "informal_ref":     ctx.informal_ref,
            "informal_paper":   ctx.informal_paper,
            "formal_decl_name": ctx.formal_decl_name,
            "primary_label":    primary.get("label", "ambiguous"),
            "primary_reason":   primary.get("reason", ""),
            "secondary_label":  secondary.get("label", "ambiguous"),
            "secondary_reason": secondary.get("reason", ""),
        })
        if i % 5 == 0 or i == len(pairs):
            elapsed = time.perf_counter() - t0
            print(f"  [{i}/{len(pairs)}] {elapsed:.0f}s ({elapsed/i:.1f}s/pair)",
                  flush=True)
    conn.close()

    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.out_csv.open("w") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()),
                           quoting=csv.QUOTE_ALL)
        w.writeheader(); w.writerows(rows)
    print(f"\nwrote {len(rows)} rows → {args.out_csv}", flush=True)

    primary_labels   = [r["primary_label"]   for r in rows]
    secondary_labels = [r["secondary_label"] for r in rows]
    kappa, po, pe = cohens_kappa(primary_labels, secondary_labels, LABELS)
    p_dist = Counter(primary_labels)
    s_dist = Counter(secondary_labels)
    agree_correct = sum(1 for r in rows if r["primary_label"]=="correct"
                        and r["secondary_label"]=="correct")
    either_wrong  = sum(1 for r in rows if "wrong" in (r["primary_label"], r["secondary_label"]))
    both_partial_or_correct = sum(
        1 for r in rows
        if r["primary_label"]   in ("correct","partial")
        and r["secondary_label"] in ("correct","partial")
    )
    summary = {
        "n":                  len(rows),
        "input_csv":          str(args.input_csv),
        "kappa":              kappa,
        "observed_agreement": po,
        "expected_agreement": pe,
        "primary_label_distribution":   dict(p_dist),
        "secondary_label_distribution": dict(s_dist),
        "both_correct":             agree_correct,
        "either_wrong":             either_wrong,
        "both_correct_or_partial":  both_partial_or_correct,
        "primary_model":   PRIMARY_MODEL,
        "secondary_model": SECONDARY_MODEL,
    }
    args.out_json.write_text(json.dumps(summary, indent=2))
    print(f"wrote summary → {args.out_json}", flush=True)

    print(f"\n=== summary ===")
    print(f"n={len(rows)}, κ={kappa:.3f}, po={po:.3f}")
    print(f"primary:   {dict(p_dist)}")
    print(f"secondary: {dict(s_dist)}")
    print(f"both correct:                {agree_correct}  ({agree_correct/len(rows):.1%})")
    print(f"both correct or partial:     {both_partial_or_correct}  ({both_partial_or_correct/len(rows):.1%})")
    print(f"either wrong:                {either_wrong}  ({either_wrong/len(rows):.1%})")


if __name__ == "__main__":
    main()
