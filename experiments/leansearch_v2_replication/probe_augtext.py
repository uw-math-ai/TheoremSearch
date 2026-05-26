"""Cheap directional probe for the augmented-text hypothesis.

For each fair-810 miss (where our slogan-only retriever didn't surface the gold
decl in top-10), embed the gold's *LSv2-style augmented text* and compare
cosine to the query against the cosine of our recorded rank-1 distractor's
slogan embedding.

The bet: if augmented-text cosine(query, gold_aug) > original cosine(query,
distractor_slogan) for the majority of misses, then re-embedding the corpus
with augmented text would rank the gold above the distractor — and the full
337K re-embed is worth committing to.

If <50% of misses flip in our favor, the embed-text hypothesis is weaker than
the by-kind data suggested, and we should investigate further before spending
the GPU time.

Doesn't touch the corpus. Costs ~3 Nebius calls per probed miss (~1.2s/call).

Usage:
  python3 probe_augtext.py [--n 50] [--style q3_nickname] [--all-styles]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

import boto3
import psycopg2
from openai import OpenAI


REPO_ROOT = Path("/mmfs1/gscratch/amath/simku22/TheoremSearch")
DATA = Path(__file__).parent / "data"
PER_QUERY = DATA / "per_query.jsonl"

EMBED_MODEL = "Qwen/Qwen3-Embedding-8B"
QUERY_INSTRUCTION = "Given a math search query, retrieve theorems mathematically equivalent to the query.\n"

# Normalize the inconsistent kind vocab in v427+v428 so the [kind] header is
# stable across the corpus. Maps the shorter "lean-graph" variants to their
# canonical Lean elaborator names. Anything not in this map is passed through
# verbatim.
KIND_NORMALIZE = {
    "thm": "theorem",
    "def": "definition",
    "inst": "instance",
    "struct": "structure",
    "ctor": "constructor",
    "ind": "inductive",
}


def normalize_kind(k: str) -> str:
    return KIND_NORMALIZE.get(k, k)


def build_augtext_full(decl_name: str, kind: str, module: str | None,
                       docstring: str | None, body: str | None, slogan: str) -> str:
    """LSv2-template-inspired bundle adapted to our schema (verbose variant)."""
    nk = normalize_kind(kind)
    if nk == "theorem":
        header = "Represent the following mathematical theorem in lean repository for semantic search"
    elif nk == "definition":
        header = "Represent the following mathematical definition in lean repository for semantic search"
    elif nk == "instance":
        header = "Represent the following typeclass instance in lean repository for semantic search"
    else:
        header = "Represent the following lean content for semantic search"

    informal_lines = [f"[{nk}]: {slogan.strip()}"]
    if docstring and docstring.strip():
        informal_lines.append(f"Docstring: {docstring.strip()[:1000]}")

    formal_lines = [decl_name]
    if module:
        formal_lines.append(f"Module: {module}")
    if body and body.strip():
        formal_lines.append(body.strip()[:1500])
    else:
        formal_lines.append(":= by sorry")

    return (
        f"{header}:\n"
        f" Informal content:\n " + "\n ".join(informal_lines) + "\n"
        f" Formal content:\n " + "\n ".join(formal_lines)
    )


def build_augtext_minimal(decl_name: str, slogan: str) -> str:
    """Minimal augmentation: just the decl name then the slogan.

    Tests whether the LSv2-template dilution is from the boilerplate header
    rather than the decl_name addition itself. Single newline separator.
    """
    return f"{decl_name}\n{slogan.strip()}"


def build_augtext_name_only(decl_name: str) -> str:
    """Pure decl_name, no slogan. Tests how much signal the lexical anchor
    carries on its own (vs. how much the slogan brings)."""
    return decl_name


# default exposed alias for the verbose variant (back-compat with earlier probe runs)
def build_augtext(decl_name: str, kind: str, module: str | None,
                   docstring: str | None, body: str | None, slogan: str) -> str:
    return build_augtext_full(decl_name, kind, module, docstring, body, slogan)


def load_env() -> dict:
    env = {}
    with open(REPO_ROOT / ".env") as f:
        for line in f:
            if line.strip() and not line.startswith("#") and "=" in line:
                k, _, v = line.strip().partition("=")
                env[k] = v.strip("'\"")
    return env


def db_connect(env: dict) -> psycopg2.extensions.connection:
    sm = boto3.client("secretsmanager", region_name=env["AWS_REGION"],
                      aws_access_key_id=env["AWS_ACCESS_KEY_ID"],
                      aws_secret_access_key=env["AWS_SECRET_ACCESS_KEY"])
    secret = json.loads(sm.get_secret_value(SecretId=env["RDS_SECRET_ARN"])["SecretString"])
    return psycopg2.connect(host="localhost", port=5432, dbname="v2",
        user=secret["username"], password=secret["password"], sslmode="require",
        options="-c statement_timeout=60000")


def fetch_decl_fields(conn, decl_name: str) -> dict | None:
    """Pull kind, module, docstring, body for a decl_name in v427+v428."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT st.kind, fm.module, fm.docstring, st.body, st.statement_id
            FROM formal_metadata fm
            JOIN statement st ON st.statement_id = fm.statement_id
            JOIN paper p      ON p.paper_id     = st.paper_id
            WHERE fm.decl_name = %s
              AND p.external_id IN ('Mathlib_v427','Mathlib_v428')
            LIMIT 1
        """, (decl_name,))
        row = cur.fetchone()
    if row is None:
        return None
    return {"kind": row[0], "module": row[1], "docstring": row[2],
            "body": row[3], "statement_id": str(row[4])}


def fetch_slogan(conn, statement_id: str) -> str | None:
    """Pull the qwen3-235b slogan for a statement_id (first non-insufficient)."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT slogan FROM slogan
            WHERE statement_id = %s::uuid
              AND model_name = 'qwen3-235b'
              AND NOT insufficient_context
            ORDER BY created_at DESC LIMIT 1
        """, (statement_id,))
        row = cur.fetchone()
    return row[0] if row else None


def embed(oai: OpenAI, text: str, *, is_query: bool) -> list[float]:
    inp = (QUERY_INSTRUCTION + text) if is_query else text
    resp = oai.embeddings.create(model=EMBED_MODEL, input=inp, encoding_format="float")
    v = resp.data[0].embedding
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n > 0 else v


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def pick_misses(rows: list[dict], style: str | None, n: int) -> list[dict]:
    pool = [r for r in rows if r["in_shared171"] and not r["hit_rank"]]
    if style:
        pool = [r for r in pool if r["style"] == style]
    return pool[:n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=50, help="Misses to probe")
    ap.add_argument("--style", default="q3_nickname",
                    help="Style filter (q3_nickname is the cleanest test; "
                         "use --all-styles to drop filter)")
    ap.add_argument("--all-styles", action="store_true",
                    help="Probe across all styles, not just q3_nickname")
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(PER_QUERY)]
    style = None if args.all_styles else args.style
    misses = pick_misses(rows, style, args.n)
    print(f"[probe] probing {len(misses)} misses (style={style or 'ALL'})", file=sys.stderr)

    env = load_env()
    conn = db_connect(env)
    oai = OpenAI(base_url="https://api.studio.nebius.ai/v1/", api_key=env["NEBIUS_API_KEY"])

    results = []
    t0 = time.time()
    for i, r in enumerate(misses, 1):
        fields = fetch_decl_fields(conn, r["full_name"])
        if not fields:
            print(f"  [{i:3d}] SKIP {r['full_name']}  (not in v427+v428)", file=sys.stderr)
            continue
        slogan = fetch_slogan(conn, fields["statement_id"])
        if not slogan:
            print(f"  [{i:3d}] SKIP {r['full_name']}  (no slogan)", file=sys.stderr)
            continue

        aug_full = build_augtext_full(r["full_name"], fields["kind"], fields["module"],
                                      fields["docstring"], fields["body"], slogan)
        aug_min  = build_augtext_minimal(r["full_name"], slogan)
        aug_name = build_augtext_name_only(r["full_name"])

        q_vec = embed(oai, r["query"], is_query=True)
        sim_aug_full = cosine(q_vec, embed(oai, aug_full, is_query=False))
        sim_aug_min  = cosine(q_vec, embed(oai, aug_min,  is_query=False))
        sim_aug_name = cosine(q_vec, embed(oai, aug_name, is_query=False))
        sim_aug = sim_aug_full   # back-compat for downstream prints

        # Original distractor similarity is already in the per_query record.
        top1 = r["top10"][0] if r["top10"] else None
        sim_top1 = top1["similarity"] if top1 else 0.0
        # Also compare against our top-10 worst (rank 10), since that's the
        # cutoff: if aug-text gold > rank-10-sim, the gold makes top-10.
        sim_top10_min = min(t["similarity"] for t in r["top10"]) if r["top10"] else 0.0

        results.append({
            "full_name": r["full_name"],
            "style": r["style"],
            "query": r["query"],
            "kind": fields["kind"],
            "sim_aug_full": sim_aug_full,
            "sim_aug_min": sim_aug_min,
            "sim_aug_name": sim_aug_name,
            "sim_aug_gold": sim_aug_full,   # back-compat
            "sim_orig_top1_distractor": sim_top1,
            "sim_orig_top10_min": sim_top10_min,
            "full_beats_top1": sim_aug_full > sim_top1,
            "min_beats_top1":  sim_aug_min  > sim_top1,
            "name_beats_top1": sim_aug_name > sim_top1,
            "full_makes_top10": sim_aug_full > sim_top10_min,
            "min_makes_top10":  sim_aug_min  > sim_top10_min,
            "name_makes_top10": sim_aug_name > sim_top10_min,
            "aug_beats_top1": sim_aug_full > sim_top1,
            "aug_makes_top10": sim_aug_full > sim_top10_min,
            "top1_distractor": top1["decl_name"] if top1 else None,
        })
        if i % 10 == 0:
            print(f"  [{i:3d}/{len(misses)}] elapsed {time.time()-t0:.1f}s", file=sys.stderr)

    n = len(results)
    if n == 0:
        print("No probeable misses.", file=sys.stderr)
        return

    def avg(key): return sum(r[key] for r in results) / n
    def hit(key): return sum(1 for r in results if r[key])

    print()
    print(f"# Augmented-text probe — n={n} {style or 'ALL'} fair-810 misses")
    print()
    print("## Three augmentation variants vs original slogan-only baseline")
    print()
    print("| variant | mean cos | beats rank-1 distractor | makes top-10 |")
    print("|---|---:|---:|---:|")
    print(f"| full LSv2-style bundle   | {avg('sim_aug_full'):.4f} | "
          f"{hit('full_beats_top1')}/{n} ({hit('full_beats_top1')/n:.1%}) | "
          f"{hit('full_makes_top10')}/{n} ({hit('full_makes_top10')/n:.1%}) |")
    print(f"| minimal: decl_name+slogan | {avg('sim_aug_min'):.4f} | "
          f"{hit('min_beats_top1')}/{n} ({hit('min_beats_top1')/n:.1%}) | "
          f"{hit('min_makes_top10')}/{n} ({hit('min_makes_top10')/n:.1%}) |")
    print(f"| decl_name only (no slogan) | {avg('sim_aug_name'):.4f} | "
          f"{hit('name_beats_top1')}/{n} ({hit('name_beats_top1')/n:.1%}) | "
          f"{hit('name_makes_top10')}/{n} ({hit('name_makes_top10')/n:.1%}) |")
    print(f"| (baseline) rank-1 distractor | {avg('sim_orig_top1_distractor'):.4f} | — | — |")
    print(f"| (baseline) rank-10 cutoff   | {avg('sim_orig_top10_min'):.4f} | — | — |")
    print()
    print("## Sample (10 most successful flips)")
    print()
    print("| decl | query | aug sim | dist sim | beats? |")
    print("|---|---|---:|---:|---|")
    flips = sorted(results, key=lambda r: r["sim_aug_gold"] - r["sim_orig_top1_distractor"], reverse=True)
    for r in flips[:10]:
        print(f"| `{r['full_name'][:50]}` | {r['query'][:30]} | "
              f"{r['sim_aug_gold']:.3f} | {r['sim_orig_top1_distractor']:.3f} | "
              f"{'✓' if r['aug_beats_top1'] else '✗'} |")
    print()
    print("## Sample (10 cases where aug-text STILL didn't beat the distractor)")
    print()
    print("| decl | query | aug sim | dist sim | top1 distractor |")
    print("|---|---|---:|---:|---|")
    losses = [r for r in results if not r["aug_beats_top1"]][:10]
    for r in losses:
        print(f"| `{r['full_name'][:50]}` | {r['query'][:30]} | "
              f"{r['sim_aug_gold']:.3f} | {r['sim_orig_top1_distractor']:.3f} | "
              f"`{(r['top1_distractor'] or '')[:40]}` |")

    # Persist full results
    out = DATA / f"probe_{style or 'all'}_n{n}.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\n[probe] full results → {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
