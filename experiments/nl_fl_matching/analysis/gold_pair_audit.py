"""Audit a random sample of blueprint gold pairs for annotation correctness.

The gold set comes from `informal_metadata.lean` (the blueprint `\\lean{...}`
macro). We found ≥2/15 in the "neither" sample to be wrong. This script
quantifies that noise rate on a larger random sample using two LLM judges
(Claude Sonnet 4.5 + Claude Haiku 4.5 via Bedrock) — Cohen's κ on the labels
gives an inter-rater agreement floor; majority/agreement label gives the
working "fraction of gold that is correct."

Categories per pair:
  correct    : the formal decl is a faithful formalization of the informal
  partial    : same theorem but with mismatched generality (different typeclass
               constraints, more/less general, etc.); arguably correct
  wrong      : the formal decl does NOT correspond to the informal — annotation
               is broken
  ambiguous  : informal text or formal slogan is too vague to judge

Reproduce:
    python -m experiments.nl_fl_matching.analysis.gold_pair_audit --n 150 --seed 42

Output:
  data/gold_pair_audit.csv     # per-pair labels from both raters
  data/gold_pair_audit.json    # summary with κ, label distribution
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "rds"))

import boto3
from dotenv import load_dotenv

from utils.connect import get_rds_connection  # noqa: E402
from experiments.nl_fl_matching import gold  # noqa: E402

load_dotenv()

PRIMARY_MODEL   = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
SECONDARY_MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

LABELS = ["correct", "partial", "wrong", "ambiguous"]

PROMPT = """You are auditing a (informal statement, formal Lean declaration) pair from a Lean blueprint. Decide whether the formal declaration is a faithful formalization of the informal statement.

INFORMAL (from blueprint or arxiv):
  Reference: {informal_ref}
  Paper:     {informal_paper}
  Slogan:    {informal_slogan}
  LaTeX body:
{informal_body}

FORMAL (Lean):
  decl_name: {formal_decl_name}
  module:    {formal_module}
  Slogan:    {formal_slogan}
  Lean signature/body:
{formal_body}

Pick exactly one label:
  correct    — the formal decl is a faithful formalization of the informal statement
  partial    — same theorem but mismatched generality (typeclass strength, scope) — close but not exact
  wrong      — the formal decl is NOT what the informal statement says (annotation is broken)
  ambiguous  — informal or formal text is too vague to judge

Output JSON only, no prose:
{{"label": "<one of: correct, partial, wrong, ambiguous>", "reason": "<one sentence>"}}
"""


@dataclass
class PairContext:
    informal_sid:        str
    formal_sid:          str
    informal_ref:        Optional[str]
    informal_paper:      Optional[str]
    informal_slogan:     Optional[str]
    informal_body:       Optional[str]
    formal_decl_name:    Optional[str]
    formal_module:       Optional[str]
    formal_slogan:       Optional[str]
    formal_body:         Optional[str]


_HYDRATE_SQL = """
WITH ipair AS (SELECT UNNEST(%(infs)s::uuid[]) AS sid),
     fpair AS (SELECT UNNEST(%(fmls)s::uuid[]) AS sid),
     islogan AS (
        SELECT DISTINCT ON (sl.statement_id) sl.statement_id, sl.slogan
          FROM slogan sl WHERE sl.statement_id = ANY(%(infs)s::uuid[])
            AND sl.model_name='qwen3-235b' AND NOT sl.insufficient_context
         ORDER BY sl.statement_id, sl.created_at
     ),
     fslogan AS (
        SELECT DISTINCT ON (sl.statement_id) sl.statement_id, sl.slogan
          FROM slogan sl WHERE sl.statement_id = ANY(%(fmls)s::uuid[])
            AND sl.model_name='qwen3-235b' AND NOT sl.insufficient_context
         ORDER BY sl.statement_id, sl.created_at
     )
SELECT
    i.sid::text   AS informal_sid,
    f.sid::text   AS formal_sid,
    im.ref        AS informal_ref,
    ip.external_id AS informal_paper,
    isl.slogan    AS informal_slogan,
    ist.body      AS informal_body,
    fm.decl_name  AS formal_decl_name,
    fm.module     AS formal_module,
    fsl.slogan    AS formal_slogan,
    fst.body      AS formal_body
  FROM ipair i CROSS JOIN fpair f
  LEFT JOIN informal_metadata im ON im.statement_id = i.sid
  LEFT JOIN statement ist ON ist.statement_id = i.sid
  LEFT JOIN paper ip ON ip.paper_id = ist.paper_id
  LEFT JOIN islogan isl ON isl.statement_id = i.sid
  LEFT JOIN formal_metadata fm ON fm.statement_id = f.sid
  LEFT JOIN statement fst ON fst.statement_id = f.sid
  LEFT JOIN fslogan fsl ON fsl.statement_id = f.sid
 WHERE i.sid = %(target_inf)s::uuid AND f.sid = %(target_fml)s::uuid
"""


def hydrate_pair(conn, inf_sid: str, fml_sid: str) -> PairContext:
    with conn.cursor() as cur:
        cur.execute(_HYDRATE_SQL, {
            "infs": [inf_sid], "fmls": [fml_sid],
            "target_inf": inf_sid, "target_fml": fml_sid,
        })
        row = cur.fetchone()
    if row is None:
        return PairContext(inf_sid, fml_sid, *[None]*8)
    return PairContext(*row)


def _trim(s, n=1500):
    if not isinstance(s, str):
        return "(missing)"
    s = s.strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def invoke_bedrock(client, model_id: str, prompt: str,
                   max_retries: int = 4) -> dict:
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 400,
        "temperature": 0,
        "messages": [{"role": "user", "content": prompt}],
    }
    last_err = None
    for attempt in range(max_retries):
        try:
            resp = client.invoke_model(modelId=model_id, body=json.dumps(body))
            body_obj = json.loads(resp["body"].read())
            text = body_obj["content"][0]["text"].strip()
            # Tolerate ```json fences
            if text.startswith("```"):
                text = text.strip("`").split("\n", 1)[1].rsplit("```", 1)[0]
                if text.startswith("json\n"): text = text[5:]
            # Extract first {...} block (some models append prose after JSON).
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                start = text.find("{")
                if start < 0:
                    raise
                depth = 0
                for j in range(start, len(text)):
                    if text[j] == "{": depth += 1
                    elif text[j] == "}":
                        depth -= 1
                        if depth == 0:
                            return json.loads(text[start:j+1])
                raise
        except Exception as e:
            last_err = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"bedrock failed after {max_retries} retries: {last_err}")


def cohens_kappa(labels_a, labels_b, label_set):
    """Standard Cohen's κ for categorical labels."""
    assert len(labels_a) == len(labels_b)
    n = len(labels_a)
    if n == 0:
        return float("nan"), 0.0, 0.0
    agree = sum(1 for a, b in zip(labels_a, labels_b) if a == b)
    po = agree / n
    pe = 0.0
    for L in label_set:
        pa = sum(1 for x in labels_a if x == L) / n
        pb = sum(1 for x in labels_b if x == L) / n
        pe += pa * pb
    kappa = (po - pe) / (1 - pe) if pe != 1 else 1.0
    return kappa, po, pe


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=150)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out-csv", type=Path,
                   default=REPO_ROOT / "experiments/nl_fl_matching/data/gold_pair_audit.csv")
    p.add_argument("--out-json", type=Path,
                   default=REPO_ROOT / "experiments/nl_fl_matching/data/gold_pair_audit.json")
    p.add_argument("--limit", type=int, default=None,
                   help="cap for smoke testing")
    args = p.parse_args()

    conn = get_rds_connection("v2")
    print("loading gold pairs...", flush=True)
    g = gold.load_gold(conn, embedding_model="qwen3-8b")
    pair_list = list(g.pairs)
    print(f"  {len(pair_list)} gold pairs total", flush=True)

    rng = random.Random(args.seed)
    rng.shuffle(pair_list)
    sample = pair_list[: args.limit or args.n]
    print(f"  sampling {len(sample)} pairs (seed={args.seed})", flush=True)

    bedrock = boto3.client("bedrock-runtime",
                           region_name=os.getenv("AWS_REGION", "us-west-2"))

    rows = []
    t0 = time.perf_counter()
    for i, (inf_sid, fml_sid) in enumerate(sample, 1):
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

        if i % 10 == 0 or i == len(sample):
            elapsed = time.perf_counter() - t0
            print(f"  [{i}/{len(sample)}] {elapsed:.0f}s "
                  f"({elapsed/i:.1f}s/pair)", flush=True)

    conn.close()

    # Persist CSV.
    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.out_csv.open("w") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()), quoting=csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {len(rows)} rows → {args.out_csv}", flush=True)

    # Stats.
    primary_labels   = [r["primary_label"]   for r in rows]
    secondary_labels = [r["secondary_label"] for r in rows]
    kappa, po, pe = cohens_kappa(primary_labels, secondary_labels, LABELS)

    from collections import Counter
    p_dist = Counter(primary_labels)
    s_dist = Counter(secondary_labels)
    # Majority/agreement label: 'correct' if BOTH say correct, otherwise downgrade.
    agree_correct  = sum(1 for r in rows if r["primary_label"]=="correct" and r["secondary_label"]=="correct")
    either_wrong   = sum(1 for r in rows if "wrong" in (r["primary_label"], r["secondary_label"]))
    summary = {
        "n":              len(rows),
        "kappa":          kappa,
        "observed_agreement": po,
        "expected_agreement": pe,
        "primary_label_distribution":   dict(p_dist),
        "secondary_label_distribution": dict(s_dist),
        "both_correct":   agree_correct,
        "either_wrong":   either_wrong,
        "primary_model":   PRIMARY_MODEL,
        "secondary_model": SECONDARY_MODEL,
        "seed":            args.seed,
    }
    args.out_json.write_text(json.dumps(summary, indent=2))
    print(f"wrote summary → {args.out_json}", flush=True)

    print(f"\n=== summary ===")
    print(f"n={len(rows)}, κ={kappa:.3f}, po={po:.3f}")
    print(f"primary distribution:   {dict(p_dist)}")
    print(f"secondary distribution: {dict(s_dist)}")
    print(f"both 'correct': {agree_correct} ({agree_correct/len(rows):.1%})")
    print(f"either 'wrong': {either_wrong}  ({either_wrong/len(rows):.1%})")


if __name__ == "__main__":
    main()
