"""Expand the "neither"-bucket failure-mode taxonomy from n=15 to n=50,
with dual-rater Bedrock labels and inter-rater κ.

The original taxonomy (n=15, one-author) in bidirectional_matching.md
identified 9 failure modes. This script:
  1. Samples 50 random pairs from the 619-pair "neither" bucket.
  2. Hydrates each with the gold pair + top-5 candidates per direction
     (same as neither_cases.py).
  3. Asks Claude Sonnet 4.5 + Claude Haiku 4.5 via Bedrock to assign
     ONE of the 9 existing failure-mode labels (or 'other').
  4. Computes Cohen's κ and per-mode counts.

Labels (matching bidirectional_matching.md table):
  sibling_lemma_adjacency
  equation_vs_definition
  to_additive_or_fun_value_twin
  multiple_correct_formalizations
  terminology_drift
  compound_statement_dilution
  bad_blueprint_annotation
  generalization_gap
  lexical_hijack
  other

Reproduce:
    python -m experiments.nl_fl_matching.analysis.failure_modes_n50 --n 50

Outputs:
  data/neither_failure_modes_n50.csv
  data/neither_failure_modes_n50.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
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
from experiments.nl_fl_matching import gold  # noqa: E402
from experiments.nl_fl_matching.analysis.eval import fetch_rows  # noqa: E402
from experiments.nl_fl_matching.analysis.agreement import bucket_pairs  # noqa: E402
from experiments.nl_fl_matching.analysis.neither_cases import (  # noqa: E402
    hydrate, _short,
)
from experiments.nl_fl_matching.analysis.gold_pair_audit import (  # noqa: E402
    invoke_bedrock, cohens_kappa,
    PRIMARY_MODEL, SECONDARY_MODEL,
)

load_dotenv()

LABELS = [
    "sibling_lemma_adjacency",
    "equation_vs_definition",
    "to_additive_or_fun_value_twin",
    "multiple_correct_formalizations",
    "terminology_drift",
    "compound_statement_dilution",
    "bad_blueprint_annotation",
    "generalization_gap",
    "lexical_hijack",
    "other",
]

LABEL_DEFS = """
- sibling_lemma_adjacency:        same paper has many near-identical statements; the rank-1 result is a sibling lemma in the SAME paper as the gold formal
- equation_vs_definition:         rank-1 is a *_eq / *_iff / property-of-X form when the gold is the bare definition of X (or vice versa)
- to_additive_or_fun_value_twin:  rank-1 is the additive/multiplicative twin (`MonoidAlgebra` ↔ `AddMonoidAlgebra`) or function-vs-value-at-identity sibling
- multiple_correct_formalizations:  multiple decls in the corpus formalize the same theorem; the embedding favors a different one than the blueprint pointed to (e.g. canonical/concise form preferred over a verbose Submodule construction)
- terminology_drift:              blueprint uses one term ("cubes") but the formalization uses another ("tiles") for the same object
- compound_statement_dilution:    informal is a long multi-clause statement; embedding gets distracted by surface-level terms
- bad_blueprint_annotation:       the `\\lean{...}` annotation is just wrong / points at an unrelated decl (the formal slogan and informal slogan disagree on what theorem is being stated)
- generalization_gap:             informal is a project-specific instance, formal is a more general Mathlib lemma — the gold-pointed formal is the wrong abstraction level
- lexical_hijack:                 rank-1 is dominated by surface-level lexical triggers (e.g. "successor order") with no semantic match
- other:                          doesn't fit any of the above
"""

PROMPT = """You are classifying a failure mode of an NL↔FL embedding retriever. The retriever was given an informal statement (or a formal Lean declaration) as a query and was asked to find the matching counterpart from a corpus. The "gold partner" (from a Lean blueprint `\\lean{{...}}` annotation) was NOT recovered at rank 1 in either direction. Your job is to label *why*.

INPUT FOR THIS CASE:

GOLD INFORMAL ({informal_paper}, ref {informal_ref}):
  slogan: {informal_slogan}

GOLD FORMAL ({formal_paper}, decl {formal_decl}):
  slogan: {formal_slogan}

f→i top-5 (the gold informal is NOT in this list, OR is below rank 1):
{f2i_top5}

i→f top-5 (the gold formal is NOT in this list, OR is below rank 1):
{i2f_top5}

LABELS:
{label_defs}

Choose ONE label that best characterizes the failure. Output JSON only:
{{"label": "<label>", "reason": "<one sentence>"}}
"""


def render_top5(top5):
    lines = []
    for rank, info in top5:
        slogan = (info.get("slogan") or "").replace("\n", " ")
        if len(slogan) > 220: slogan = slogan[:220] + "…"
        name = info.get("decl_name") or info.get("ref") or "?"
        lines.append(f"  rank {rank}: [{info.get('formality') or '?'}] {name} — {slogan}")
    return "\n".join(lines) if lines else "  (none)"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=50)
    p.add_argument("--seed", type=int, default=20260525)
    p.add_argument("--out-csv", type=Path,
                   default=REPO_ROOT / "experiments/nl_fl_matching/data/neither_failure_modes_n50.csv")
    p.add_argument("--out-json", type=Path,
                   default=REPO_ROOT / "experiments/nl_fl_matching/data/neither_failure_modes_n50.json")
    args = p.parse_args()

    rng = random.Random(args.seed)
    conn = get_rds_connection("v2")
    print("loading gold + ranks...", flush=True)
    g = gold.load_gold(conn, embedding_model="qwen3-8b")
    f2i = fetch_rows(conn, "f2i", "qwen3-8b",
                     pool_descriptor="gold_subset_f2i", exclusion="statement")
    i2f = fetch_rows(conn, "i2f", "qwen3-8b",
                     pool_descriptor="gold_subset_i2f", exclusion="statement")
    b = bucket_pairs(g.pairs, f2i, i2f,
                     g.formal_to_gold_informals, g.informal_to_gold_formals)
    print(f"  neither bucket size: {len(b.neither)}", flush=True)
    sample = rng.sample(b.neither, min(args.n, len(b.neither)))
    print(f"  sampling {len(sample)} pairs (seed={args.seed})", flush=True)

    # Hydrate gold + top-5 from each direction.
    all_sids = set()
    triples = []  # (inf_sid, fml_sid, f2i_top5_sids, i2f_top5_sids)
    for inf_sid, fml_sid in sample:
        f2i_top5 = [(r, cid) for r, cid, _ in f2i.get(fml_sid, []) if r <= 5]
        i2f_top5 = [(r, cid) for r, cid, _ in i2f.get(inf_sid, []) if r <= 5]
        all_sids.update([inf_sid, fml_sid])
        all_sids.update(c for _, c in f2i_top5)
        all_sids.update(c for _, c in i2f_top5)
        triples.append((inf_sid, fml_sid, f2i_top5, i2f_top5))
    print(f"hydrating {len(all_sids):,} sids...", flush=True)
    info = hydrate(conn, all_sids)

    bedrock = boto3.client("bedrock-runtime",
                           region_name=os.getenv("AWS_REGION", "us-west-2"))

    rows = []
    t0 = time.perf_counter()
    for i, (inf_sid, fml_sid, f2i_top5, i2f_top5) in enumerate(triples, 1):
        inf = info.get(inf_sid, {})
        fml = info.get(fml_sid, {})
        f2i_top5_render = render_top5([(r, info.get(c, {})) for r, c in f2i_top5])
        i2f_top5_render = render_top5([(r, info.get(c, {})) for r, c in i2f_top5])
        prompt = PROMPT.format(
            informal_paper=inf.get("paper_external_id") or "(none)",
            informal_ref=inf.get("ref") or "(none)",
            informal_slogan=_short(inf.get("slogan"), 400),
            formal_paper=fml.get("paper_external_id") or "(none)",
            formal_decl=fml.get("decl_name") or "(none)",
            formal_slogan=_short(fml.get("slogan"), 400),
            f2i_top5=f2i_top5_render,
            i2f_top5=i2f_top5_render,
            label_defs=LABEL_DEFS.strip(),
        )
        try:
            primary = invoke_bedrock(bedrock, PRIMARY_MODEL, prompt)
        except Exception as e:
            primary = {"label": "other", "reason": f"primary_err: {e}"}
        try:
            secondary = invoke_bedrock(bedrock, SECONDARY_MODEL, prompt)
        except Exception as e:
            secondary = {"label": "other", "reason": f"secondary_err: {e}"}
        # Coerce labels into the LABELS set; else 'other'.
        def coerce(lbl):
            return lbl if lbl in LABELS else "other"
        rows.append({
            "i": i,
            "informal_sid": inf_sid,
            "formal_sid":   fml_sid,
            "informal_ref": inf.get("ref"),
            "informal_paper": inf.get("paper_external_id"),
            "formal_decl_name": fml.get("decl_name"),
            "primary_label":   coerce(primary.get("label", "other")),
            "primary_reason":  primary.get("reason", ""),
            "secondary_label": coerce(secondary.get("label", "other")),
            "secondary_reason": secondary.get("reason", ""),
        })
        if i % 5 == 0 or i == len(triples):
            print(f"  [{i}/{len(triples)}] {time.perf_counter()-t0:.0f}s", flush=True)
    conn.close()

    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.out_csv.open("w") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()),
                           quoting=csv.QUOTE_ALL)
        w.writeheader(); w.writerows(rows)
    print(f"\nwrote {args.out_csv}", flush=True)

    primary_lbls   = [r["primary_label"]   for r in rows]
    secondary_lbls = [r["secondary_label"] for r in rows]
    kappa, po, pe = cohens_kappa(primary_lbls, secondary_lbls, LABELS)
    p_dist = Counter(primary_lbls)
    s_dist = Counter(secondary_lbls)
    agree_label = Counter()
    for r in rows:
        if r["primary_label"] == r["secondary_label"]:
            agree_label[r["primary_label"]] += 1
    summary = {
        "n":      len(rows),
        "kappa":  kappa,
        "observed_agreement": po,
        "expected_agreement": pe,
        "primary_distribution":   dict(p_dist),
        "secondary_distribution": dict(s_dist),
        "agreement_distribution": dict(agree_label),
        "primary_model":   PRIMARY_MODEL,
        "secondary_model": SECONDARY_MODEL,
        "seed":            args.seed,
    }
    args.out_json.write_text(json.dumps(summary, indent=2))
    print(f"wrote {args.out_json}\n", flush=True)

    print(f"=== n={len(rows)}, κ={kappa:.3f}, po={po:.3f} ===")
    print("\nPrimary distribution:")
    for lbl in LABELS:
        n = p_dist.get(lbl, 0)
        if n: print(f"  {lbl:<35} {n:>3}")
    print("\nSecondary distribution:")
    for lbl in LABELS:
        n = s_dist.get(lbl, 0)
        if n: print(f"  {lbl:<35} {n:>3}")
    print("\nBoth raters agreed on label (per-mode counts):")
    for lbl in LABELS:
        n = agree_label.get(lbl, 0)
        if n: print(f"  {lbl:<35} {n:>3}")


if __name__ == "__main__":
    main()
