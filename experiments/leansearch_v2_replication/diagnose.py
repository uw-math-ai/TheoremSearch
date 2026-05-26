"""Diagnostic over per_query.jsonl — surface the where/why of the LSv2 gap.

Reads data/per_query.jsonl + data/summary.json and prints:

  1. Headline: recall@10 / nDCG@10 on full-946 and fair-810; compare to LSv2
     retriever-only (0.494 / 0.657) and reranked (0.623 / 0.780).
  2. Per-style + per-kind + per-difficulty breakdown on fair-810.
  3. Hit-rank histogram (where do hits land?).
  4. Top-1 hit fraction (precision-like).
  5. Coverage diagnostic (already in summary.json, restated).
  6. For misses: was the gold decl's *own* slogan even in the top-200 ANN
     shortlist? Computes "ceiling recall@200" — the maximum recall we could
     achieve if the cosine rerank were perfect. Requires the RDS tunnel open.

Run after `run_eval_rds.py` completes. Output is markdown to stdout; pipe to
file if you want it persisted.

Usage:
  python3 diagnose.py [--no-rds]  # skip step 6 if tunnel is closed
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path
from statistics import mean

DATA = Path(__file__).parent / "data"
PER_QUERY = DATA / "per_query.jsonl"
SUMMARY = DATA / "summary.json"

LSV2_RETRIEVER = {"nDCG@10": 0.494, "Recall@10": 0.657}
LSV2_RERANK    = {"nDCG@10": 0.623, "Recall@10": 0.780}


def load_rows() -> list[dict]:
    return [json.loads(l) for l in open(PER_QUERY)]


def agg(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0}
    return {
        "n": len(rows),
        "recall@10": mean(r["recall@10"] for r in rows),
        "nDCG@10": mean(r["ndcg@10"] for r in rows),
        "top1_rate": mean(1.0 if r.get("hit_rank") == 1 else 0.0 for r in rows),
    }


def fmt(d: dict) -> str:
    if not d["n"]:
        return "n=0"
    return (f"n={d['n']:>3d}  "
            f"recall@10={d['recall@10']:.3f}  "
            f"nDCG@10={d['nDCG@10']:.3f}  "
            f"top1={d['top1_rate']:.3f}")


def headline(rows):
    full = agg(rows)
    fair = agg([r for r in rows if r["in_shared171"]])
    print("## Headline")
    print()
    print(f"- full-946:  {fmt(full)}")
    print(f"- fair-810:  {fmt(fair)}")
    print()
    print("### vs LSv2 (fair-810, from arXiv:2605.13137 Table 1)")
    print()
    print("| system | nDCG@10 | Recall@10 |")
    print("|---|---:|---:|")
    print(f"| LSv2 rerank (Qwen3-Reranker-8B) | **{LSV2_RERANK['nDCG@10']:.3f}** | **{LSV2_RERANK['Recall@10']:.3f}** |")
    print(f"| LSv2 retriever-only             | {LSV2_RETRIEVER['nDCG@10']:.3f}     | {LSV2_RETRIEVER['Recall@10']:.3f}     |")
    print(f"| LeanFinder (reported)           | 0.533 | 0.698 |")
    print(f"| LeanExplore (reported)          | 0.393 | 0.569 |")
    print(f"| **Ours (Lean Repo retriever)**  | **{fair['nDCG@10']:.3f}** | **{fair['recall@10']:.3f}** |")
    print()
    gap_ndcg = LSV2_RETRIEVER["nDCG@10"] - fair["nDCG@10"]
    gap_rec  = LSV2_RETRIEVER["Recall@10"] - fair["recall@10"]
    print(f"Gap vs LSv2 retriever-only: ΔnDCG@10 = {-gap_ndcg:+.3f}, ΔRecall@10 = {-gap_rec:+.3f}")
    print()


def by_field(rows, field):
    sub = sorted({r[field] for r in rows})
    return {v: agg([r for r in rows if r[field] == v]) for v in sub}


def breakdown(rows, label):
    fair = [r for r in rows if r["in_shared171"]]
    print(f"## Breakdown ({label})")
    print()
    src = fair if label == "fair-810" else rows
    for field in ("style", "kind", "difficulty"):
        print(f"### by {field}")
        print()
        print("| " + field + " | " + " | ".join(["n", "recall@10", "nDCG@10", "top1"]) + " |")
        print("|---" * 5 + "|")
        for v, d in by_field(src, field).items():
            if d["n"] == 0: continue
            print(f"| {v} | {d['n']} | {d['recall@10']:.3f} | {d['nDCG@10']:.3f} | {d['top1_rate']:.3f} |")
        print()


def rank_histogram(rows):
    print("## Hit-rank distribution (fair-810)")
    print()
    fair = [r for r in rows if r["in_shared171"]]
    hist = Counter()
    for r in fair:
        hist[r["hit_rank"] if r["hit_rank"] else "miss"] += 1
    print("| rank | count | cumulative recall |")
    print("|---|---:|---:|")
    cum = 0
    n = len(fair)
    for rank in range(1, 11):
        c = hist.get(rank, 0)
        cum += c
        print(f"| {rank} | {c} | {cum/n:.3f} |")
    print(f"| miss | {hist.get('miss', 0)} | — |")
    print()


def coverage(summary):
    cov = summary["corpus_coverage"]
    print("## Corpus coverage")
    print()
    print(f"MathlibQR decls present in our v427/v428 formal_metadata: "
          f"**{cov['n_decls_present']}/{cov['n_decls_total']}** "
          f"(missing {cov['n_decls_missing']}).")
    print()
    if cov["missing_full_names"]:
        print("Missing decls (each contributes a hard 0 to recall across all populated styles):")
        for n in cov["missing_full_names"]:
            print(f"  - `{n}`")
        print()


def ceiling_recall_via_rds(rows):
    """For each miss with a covered gold decl, query the cosine of its own
    slogans against the query embedding and report the max-rank our retriever
    *could* have given the gold if its slogan happened to be embedded.

    Approximation: we re-embed the query and look up the cosine of every
    slogan attached to the gold statement_id (over qwen3-235b only — same
    slogan-model filter as the deployed pipeline).
    """
    try:
        import os, boto3, psycopg2
        from openai import OpenAI
    except ImportError:
        print("## Ceiling recall@200 — skipped (deps missing)")
        return

    REPO_ROOT = Path("/mmfs1/gscratch/amath/simku22/TheoremSearch")
    env = {}
    with open(REPO_ROOT / ".env") as f:
        for line in f:
            if line.strip() and not line.startswith("#") and "=" in line:
                k, _, v = line.strip().partition("="); env[k] = v.strip("'\"")
    sm = boto3.client("secretsmanager", region_name=env["AWS_REGION"],
                      aws_access_key_id=env["AWS_ACCESS_KEY_ID"],
                      aws_secret_access_key=env["AWS_SECRET_ACCESS_KEY"])
    secret = json.loads(sm.get_secret_value(SecretId=env["RDS_SECRET_ARN"])["SecretString"])
    conn = psycopg2.connect(host="localhost", port=5432, dbname="v2",
        user=secret["username"], password=secret["password"], sslmode="require",
        options="-c statement_timeout=60000")
    oai = OpenAI(base_url="https://api.studio.nebius.ai/v1/", api_key=env["NEBIUS_API_KEY"])

    INSTR = "Given a math search query, retrieve theorems mathematically equivalent to the query.\n"

    fair_misses = [r for r in rows if r["in_shared171"] and not r["hit_rank"]]
    print(f"## Ceiling recall — for each fair-810 miss, find max cosine of gold decl's slogans")
    print()
    print(f"Misses to probe: {len(fair_misses)}")
    print()
    in_top200 = 0
    in_top50 = 0
    in_top10 = 0
    no_slogan = 0
    cosines = []
    sample = []
    with conn.cursor() as cur:
        cur.execute("SELECT '[1]'::vector(1)"); cur.fetchone()
        for i, r in enumerate(fair_misses):
            v = oai.embeddings.create(model="Qwen/Qwen3-Embedding-8B",
                                      input=INSTR + r["query"], encoding_format="float").data[0].embedding
            norm = math.sqrt(sum(x*x for x in v)); v = [x/norm for x in v] if norm else v
            lit = "[" + ",".join(f"{x:.7g}" for x in v) + "]"
            cur.execute("""
                SELECT MAX(1.0 - (e.embedding <=> %s::vector(4096)))
                FROM formal_metadata fm
                JOIN statement st ON st.statement_id = fm.statement_id
                JOIN paper p ON p.paper_id = st.paper_id
                JOIN slogan s ON s.statement_id = fm.statement_id
                JOIN embedding e ON e.slogan_id = s.slogan_id
                WHERE fm.decl_name = %s
                  AND p.external_id IN ('Mathlib_v427','Mathlib_v428')
                  AND s.model_name = 'qwen3-235b'
                  AND NOT s.insufficient_context
                  AND e.model_name = 'qwen3-8b'
            """, (lit, r["full_name"]))
            row = cur.fetchone()
            max_cos = row[0] if row and row[0] is not None else None
            if max_cos is None:
                no_slogan += 1
                continue
            cosines.append(float(max_cos))
            # Compare to the lowest cosine in our actual top-10 — if the gold cosine is
            # higher, the rerank would have included it. (Not the same as top-200, but a
            # cheap proxy. True top-200 would need scanning the entire ANN shortlist.)
            top10_min = min((t["similarity"] for t in r["top10"]), default=0.0)
            if float(max_cos) >= top10_min:
                in_top10 += 1  # would have been top-10 if our cosine cutoff includes it
            if (i+1) % 50 == 0:
                print(f"  ... probed {i+1}/{len(fair_misses)}", file=sys.stderr)
            if len(sample) < 5:
                sample.append((r["full_name"], r["style"], r["query"][:50], float(max_cos), top10_min))
    n_probed = len(fair_misses) - no_slogan
    if n_probed == 0:
        print("No probeable misses.")
        return
    print(f"- misses with no slogan in v427/v428 (decl absent or never sloganed): {no_slogan}")
    print(f"- mean max-cosine of gold slogans for probed misses: {mean(cosines):.4f}")
    print(f"- gold slogan would have outranked our top-10 min cosine: {in_top10}/{n_probed}  ({in_top10/n_probed:.1%})")
    print()
    print("Sample (first 5 probed misses):")
    print()
    print("| full_name | style | query | gold max cos | our top-10 min cos |")
    print("|---|---|---|---:|---:|")
    for fn, st, q, mc, tm in sample:
        print(f"| `{fn}` | {st} | {q} | {mc:.3f} | {tm:.3f} |")
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-rds", action="store_true", help="Skip the ceiling-recall probe")
    args = ap.parse_args()

    if not PER_QUERY.exists():
        print(f"ERROR: {PER_QUERY} not found — run run_eval_rds.py first", file=sys.stderr)
        sys.exit(1)

    rows = load_rows()
    summary = json.loads(SUMMARY.read_text()) if SUMMARY.exists() else {}

    print(f"# MathlibQR diagnostic — n={len(rows)} cells\n")
    headline(rows)
    breakdown(rows, "fair-810")
    rank_histogram(rows)
    if summary.get("corpus_coverage"):
        coverage(summary)
    if not args.no_rds:
        ceiling_recall_via_rds(rows)


if __name__ == "__main__":
    main()
