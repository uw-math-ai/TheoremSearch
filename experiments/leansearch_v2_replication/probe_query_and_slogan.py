"""Two cheap pilots in one script: HyDE (query-side expansion) and slogan-regen
(decl-side improvement). Each samples the same 50 q3_nickname misses so the
results are directly comparable.

HyDE: per query, ask qwen3-235b to write a hypothetical Lean-decl description
that would semantically answer it; embed that pseudo-doc; compare cosine
against the existing gold slogan embedding (proxy: we recompute via the
distractor-vector approach but with the new query representation).

Slogan-regen: per gold decl, ask qwen3-235b to rewrite the slogan using
LSv2-style principles (kind-aware system msg, dep names included, JSON-ish
structure but plain text output for now); embed it; compare against the
existing query embedding.

Decision rules (per the strategy doc):
- HyDE: positive if ≥30% of misses flip (new query embed beats current
  distractor cosine to the same gold slogan).
- Slogan-regen: same threshold. If both above, run both as ablation rows.
  If neither, the easy fixes are exhausted and we lean on Phase A + hybrid.

Usage:
  python3 probe_query_and_slogan.py --variant hyde --n 50
  python3 probe_query_and_slogan.py --variant regen --n 50
  python3 probe_query_and_slogan.py --variant both --n 50   # runs both sequentially
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
LLM_MODEL = "Qwen/Qwen3-235B-A22B-Instruct-2507"   # matches our slogan_model qwen3-235b
QUERY_INSTRUCTION = "Given a math search query, retrieve theorems mathematically equivalent to the query.\n"
DOC_INSTRUCTION = "Represent the given math statement for retrieving related statements by natural language query.\n"


HYDE_SYSTEM = (
    "You are an expert in the Lean 4 mathematical library Mathlib. Given a "
    "short search query, write a concise 2-4 sentence plain-English description "
    "of what the most likely matching Lean declaration would say, in the style "
    "of a Mathlib doc comment. Use ASCII only, no LaTeX. Output only the "
    "description, no preamble."
)

REGEN_SYSTEM = (
    "You are a precise mathlib translator. Given a Lean declaration's name, kind, "
    "docstring, body, and the names of its dependencies, write a concise plain-English "
    "summary suitable as a natural-language search target.\n\n"
    "Principles (adapted from LeanSearch v2):\n"
    "- Lead with what the declaration says, not its name. The reader should be able "
    "to identify the concept from the summary alone.\n"
    "- For a class/structure: describe the mathematical object it represents and its "
    "defining data, not just the typeclass formalities.\n"
    "- For a theorem/lemma: state the result in informal English, including the "
    "hypotheses and conclusion in a single complete sentence when possible.\n"
    "- For a definition: describe what is being defined and what it computes/represents.\n"
    "- For an instance: say which typeclass is being witnessed and on which type, plus "
    "the operational content if non-trivial.\n"
    "- Use the dependency names to disambiguate when the decl name alone is ambiguous; "
    "do NOT just list dependencies.\n"
    "- ASCII only, no LaTeX, no Unicode math. 1-4 sentences. No preamble like "
    "'This declaration...'.\n"
    "- Output ONLY the summary text."
)


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


def embed(oai: OpenAI, text: str, instruction: str) -> list[float]:
    resp = oai.embeddings.create(model=EMBED_MODEL, input=instruction + text, encoding_format="float")
    v = resp.data[0].embedding
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n > 0 else v


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def llm_call(oai: OpenAI, system: str, user: str, max_tokens: int = 400) -> str:
    resp = oai.chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        max_tokens=max_tokens,
        temperature=0.0,
    )
    return resp.choices[0].message.content.strip()


def fetch_gold_context(conn, decl_name: str) -> dict | None:
    """Pull existing slogan + decl context for a gold decl in v427+v428."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT st.kind, fm.module, fm.docstring, st.body, st.statement_id, s.slogan
            FROM formal_metadata fm
            JOIN statement st ON st.statement_id = fm.statement_id
            JOIN paper p      ON p.paper_id     = st.paper_id
            JOIN slogan s     ON s.statement_id = fm.statement_id
            WHERE fm.decl_name = %s
              AND p.external_id IN ('Mathlib_v427','Mathlib_v428')
              AND s.model_name  = 'qwen3-235b'
              AND NOT s.insufficient_context
            ORDER BY s.created_at DESC LIMIT 1
        """, (decl_name,))
        row = cur.fetchone()
    if not row:
        return None
    return {"kind": row[0], "module": row[1], "docstring": row[2],
            "body": row[3], "statement_id": str(row[4]), "slogan": row[5]}


def fetch_top_deps(conn, statement_id: str, k: int = 8) -> list[str]:
    """Top-k formal_dependency parents' decl_names — used as regen context."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT fm.decl_name
            FROM formal_dependency fd
            JOIN formal_metadata fm ON fm.statement_id = fd.dep_id
            WHERE fd.src_id = %s::uuid AND fm.decl_name IS NOT NULL
            LIMIT %s
        """, (statement_id, k))
        return [r[0] for r in cur.fetchall()]


def fetch_gold_slogan_embedding(conn, statement_id: str) -> list[float] | None:
    """Pull existing qwen3-8b embedding of gold's slogan from RDS."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT e.embedding::text FROM embedding e
            JOIN slogan s ON s.slogan_id = e.slogan_id
            WHERE s.statement_id = %s::uuid
              AND s.model_name = 'qwen3-235b'
              AND e.model_name = 'qwen3-8b'
              AND NOT s.insufficient_context
            LIMIT 1
        """, (statement_id,))
        row = cur.fetchone()
    if not row:
        return None
    # pgvector returns "[0.1,0.2,...]" text — parse it
    return [float(x) for x in row[0].strip("[]").split(",")]


def fetch_distractor_embedding(conn, distractor_decl_name: str) -> list[float] | None:
    """Pull the qwen3-8b embedding of our recorded rank-1 distractor's slogan."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT e.embedding::text
            FROM formal_metadata fm
            JOIN statement st ON st.statement_id = fm.statement_id
            JOIN slogan s ON s.statement_id = fm.statement_id
            JOIN embedding e ON e.slogan_id = s.slogan_id
            JOIN paper p ON p.paper_id = st.paper_id
            WHERE fm.decl_name = %s
              AND p.external_id IN ('Mathlib_v427','Mathlib_v428','Mathlib_v429')
              AND s.model_name = 'qwen3-235b'
              AND e.model_name = 'qwen3-8b'
              AND NOT s.insufficient_context
            ORDER BY s.created_at DESC LIMIT 1
        """, (distractor_decl_name,))
        row = cur.fetchone()
    return [float(x) for x in row[0].strip("[]").split(",")] if row else None


def pick_misses(n: int) -> list[dict]:
    rows = [json.loads(l) for l in open(PER_QUERY)]
    pool = [r for r in rows
            if r["in_shared171"] and not r["hit_rank"] and r["style"] == "q3_nickname"]
    return pool[:n]


def run_hyde(misses, conn, oai) -> list[dict]:
    """For each miss: HyDE pseudo-doc → embed as doc → compare to gold slogan
    embedding and to current rank-1 distractor slogan embedding."""
    results = []
    for i, r in enumerate(misses, 1):
        ctx = fetch_gold_context(conn, r["full_name"])
        if not ctx:
            print(f"  [hyde {i:2d}] SKIP {r['full_name']} (no context)", file=sys.stderr)
            continue
        gold_vec = fetch_gold_slogan_embedding(conn, ctx["statement_id"])
        if not gold_vec:
            print(f"  [hyde {i:2d}] SKIP {r['full_name']} (no gold embedding)", file=sys.stderr)
            continue
        top1 = r["top10"][0] if r["top10"] else None
        dist_vec = fetch_distractor_embedding(conn, top1["decl_name"]) if top1 else None

        try:
            pseudo = llm_call(oai, HYDE_SYSTEM,
                              f"Query: {r['query']}\n\nWrite the matching decl's description:")
        except Exception as e:
            print(f"  [hyde {i:2d}] LLM error: {e}", file=sys.stderr)
            continue

        pseudo_vec = embed(oai, pseudo, DOC_INSTRUCTION)
        # Compare pseudo-doc-embed cosines: gold's existing slogan vs distractor's slogan
        sim_gold = cosine(pseudo_vec, gold_vec)
        sim_dist = cosine(pseudo_vec, dist_vec) if dist_vec else 0.0
        # Baseline: original query embed
        orig_top1 = top1["similarity"] if top1 else 0.0
        results.append({
            "full_name": r["full_name"], "query": r["query"],
            "pseudo_doc": pseudo[:300],
            "sim_pseudo_to_gold": sim_gold,
            "sim_pseudo_to_dist": sim_dist,
            "sim_orig_top1": orig_top1,
            "hyde_beats_dist": sim_gold > sim_dist,
            "hyde_beats_orig_top1": sim_gold > orig_top1,
            "top1_distractor": top1["decl_name"] if top1 else None,
        })
        if i % 10 == 0:
            print(f"  [hyde {i}/{len(misses)}]", file=sys.stderr)
    return results


def run_regen(misses, conn, oai) -> list[dict]:
    """For each miss: regenerate gold's slogan via LSv2-style prompt; embed it;
    compare to original query embedding and to distractor's existing embedding."""
    results = []
    for i, r in enumerate(misses, 1):
        ctx = fetch_gold_context(conn, r["full_name"])
        if not ctx:
            print(f"  [regen {i:2d}] SKIP {r['full_name']} (no context)", file=sys.stderr)
            continue
        deps = fetch_top_deps(conn, ctx["statement_id"], k=8)
        top1 = r["top10"][0] if r["top10"] else None

        user_msg_parts = [
            f"Name: {r['full_name']}",
            f"Kind: {ctx['kind']}",
            f"Module: {ctx['module'] or '(unknown)'}",
        ]
        if ctx["docstring"]:
            user_msg_parts.append(f"Docstring: {ctx['docstring'][:600]}")
        if ctx["body"]:
            user_msg_parts.append(f"Lean source: {ctx['body'][:600]}")
        if deps:
            user_msg_parts.append(f"Top dependencies: {', '.join(deps)}")
        user_msg_parts.append("\nWrite the summary:")

        try:
            new_slogan = llm_call(oai, REGEN_SYSTEM, "\n".join(user_msg_parts), max_tokens=200)
        except Exception as e:
            print(f"  [regen {i:2d}] LLM error: {e}", file=sys.stderr)
            continue

        # Embed new slogan with the doc-side instruction (mirrors what
        # corpus embeddings use).
        new_slogan_vec = embed(oai, new_slogan, DOC_INSTRUCTION)
        # Embed query with query instruction (unchanged from eval)
        q_vec = embed(oai, r["query"], QUERY_INSTRUCTION)

        sim_new = cosine(q_vec, new_slogan_vec)
        sim_dist_orig = top1["similarity"] if top1 else 0.0
        # Also re-fetch old slogan cosine for true A/B (the original gold
        # cosine is the eval baseline — we already know we missed, so old<top1)
        old_vec = fetch_gold_slogan_embedding(conn, ctx["statement_id"])
        sim_old = cosine(q_vec, old_vec) if old_vec else 0.0

        results.append({
            "full_name": r["full_name"], "query": r["query"],
            "old_slogan": (ctx["slogan"] or "")[:200],
            "new_slogan": new_slogan[:300],
            "sim_new_slogan_to_query": sim_new,
            "sim_old_slogan_to_query": sim_old,
            "sim_orig_top1_distractor": sim_dist_orig,
            "regen_beats_dist": sim_new > sim_dist_orig,
            "regen_beats_old": sim_new > sim_old,
            "delta_vs_old": sim_new - sim_old,
            "top1_distractor": top1["decl_name"] if top1 else None,
        })
        if i % 10 == 0:
            print(f"  [regen {i}/{len(misses)}]", file=sys.stderr)
    return results


def report_hyde(results, out_path):
    n = len(results)
    print(f"\n# HyDE probe — n={n} q3_nickname fair-810 misses\n")
    print(f"- HyDE pseudo-doc embed beats CURRENT rank-1 distractor (apples-to-apples gold cosine vs distractor cosine, both against pseudo-doc-embed):")
    print(f"  **{sum(1 for r in results if r['hyde_beats_dist'])}/{n} ({sum(1 for r in results if r['hyde_beats_dist'])/n:.1%})**")
    print(f"- HyDE pseudo-doc-to-gold cosine > original-query top1 distractor cosine:")
    print(f"  **{sum(1 for r in results if r['hyde_beats_orig_top1'])}/{n} ({sum(1 for r in results if r['hyde_beats_orig_top1'])/n:.1%})**")
    avg_g = sum(r['sim_pseudo_to_gold'] for r in results) / n if n else 0
    avg_d = sum(r['sim_pseudo_to_dist'] for r in results) / n if n else 0
    print(f"\nMean cosines: pseudo→gold={avg_g:.4f}  pseudo→distractor={avg_d:.4f}")
    print("\n## Sample (5 best flips)\n")
    flips = sorted(results, key=lambda r: r["sim_pseudo_to_gold"] - r["sim_pseudo_to_dist"], reverse=True)
    for r in flips[:5]:
        print(f"- **{r['full_name']}** | q={r['query']!r}")
        print(f"  pseudo→gold={r['sim_pseudo_to_gold']:.3f}  pseudo→dist({r['top1_distractor']})={r['sim_pseudo_to_dist']:.3f}")
        print(f"  pseudo_doc: {r['pseudo_doc'][:200]}")
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\nFull → {out_path}", file=sys.stderr)


def report_regen(results, out_path):
    n = len(results)
    print(f"\n# Slogan-regen probe — n={n} q3_nickname fair-810 misses\n")
    avg_delta = sum(r["delta_vs_old"] for r in results) / n if n else 0
    print(f"- New-slogan cosine > original distractor cosine: **{sum(1 for r in results if r['regen_beats_dist'])}/{n} ({sum(1 for r in results if r['regen_beats_dist'])/n:.1%})**")
    print(f"- New-slogan cosine > old-slogan cosine (controlled A/B): **{sum(1 for r in results if r['regen_beats_old'])}/{n} ({sum(1 for r in results if r['regen_beats_old'])/n:.1%})**")
    print(f"- Mean Δcosine (new - old) for the same gold decl: **{avg_delta:+.4f}**")
    print(f"  (positive = LSv2-style regen produces a slogan whose embedding is closer to the query)")
    print(f"\nMean: new→query={sum(r['sim_new_slogan_to_query'] for r in results)/n:.4f}  "
          f"old→query={sum(r['sim_old_slogan_to_query'] for r in results)/n:.4f}  "
          f"dist→query={sum(r['sim_orig_top1_distractor'] for r in results)/n:.4f}")
    print("\n## Sample (5 best deltas — slogan changes that move the needle most)\n")
    flips = sorted(results, key=lambda r: r["delta_vs_old"], reverse=True)
    for r in flips[:5]:
        print(f"- **{r['full_name']}** | q={r['query']!r}  Δ={r['delta_vs_old']:+.3f}")
        print(f"  OLD: {r['old_slogan']}")
        print(f"  NEW: {r['new_slogan']}")
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\nFull → {out_path}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=["hyde", "regen", "both"], default="both")
    ap.add_argument("--n", type=int, default=50)
    args = ap.parse_args()

    env = load_env()
    conn = db_connect(env)
    oai = OpenAI(base_url="https://api.studio.nebius.ai/v1/", api_key=env["NEBIUS_API_KEY"])

    misses = pick_misses(args.n)
    print(f"[probe] {len(misses)} q3_nickname misses sampled", file=sys.stderr)

    if args.variant in ("hyde", "both"):
        t0 = time.time()
        hyde_results = run_hyde(misses, conn, oai)
        report_hyde(hyde_results, DATA / f"probe_hyde_n{len(hyde_results)}.json")
        print(f"[probe] hyde took {time.time()-t0:.1f}s", file=sys.stderr)

    if args.variant in ("regen", "both"):
        t0 = time.time()
        regen_results = run_regen(misses, conn, oai)
        report_regen(regen_results, DATA / f"probe_regen_n{len(regen_results)}.json")
        print(f"[probe] regen took {time.time()-t0:.1f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
