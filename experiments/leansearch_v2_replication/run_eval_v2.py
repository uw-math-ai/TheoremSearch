"""Phase A harness: existing slogan embeddings + three retrieval-side levers.

Toggles (each independently ablatable):
  --dedupe          dedupe top-K by statement_id (one slot per decl, best slogan wins)
  --ann-k N         override binary HNSW shortlist size (default 200)
  --hybrid-trigram  add a trigram-on-decl_name score channel, RRF-fuse with cosine

All three layered = the "Phase A" row in the ablation table. They're
independently usable so each can be its own row too.

Output paths:
  data/per_query_v2_<tag>.jsonl
  data/summary_v2_<tag>.json

The <tag> is composed from the toggles: e.g. `dedupe_annk1000_trigram`.

Mathlib pin and benchmark loading match run_eval_rds.py — see that file's
docstring for context. The cosine SQL is unchanged from run_eval_rds.py
(session-temp-table approach for filtered HNSW).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional

import boto3
import psycopg2
from openai import OpenAI


REPO_ROOT = Path("/mmfs1/gscratch/amath/simku22/TheoremSearch")
BENCH_DIR = REPO_ROOT / "formalized_graph/docs/paper_writing/leansearch_v2_external/benchmark"
DATA_DIR = REPO_ROOT / "experiments/leansearch_v2_replication/data"

DEFAULT_EMBED_MODEL = "qwen3-8b"
EMBED_MODEL = DEFAULT_EMBED_MODEL  # overridden by --embed-model
SLOGAN_MODELS = ["qwen3-235b"]
QUERY_INSTRUCTION = "Given a math search query, retrieve theorems mathematically equivalent to the query.\n"
DOC_INSTRUCTION = "Represent the given math statement for retrieving related statements by natural language query.\n"
HYDE_LLM_MODEL = "Qwen/Qwen3-235B-A22B-Instruct-2507"
HYDE_SYSTEM = (
    "You are an expert in the Lean 4 mathematical library Mathlib. Given a "
    "short search query, write a concise 2-4 sentence plain-English description "
    "of what the most likely matching Lean declaration would say, in the style "
    "of a Mathlib doc comment. Use ASCII only, no LaTeX. Output only the "
    "description, no preamble."
)
SOURCES = ["Lean Repo"]
MATHLIB_EXTERNAL_IDS = ["Mathlib_v427", "Mathlib_v428"]
TOP_K = 10
DEFAULT_ANN_K = 200
EF_SEARCH = 500
STMT_TIMEOUT_MS = 120_000
RRF_K = 60
TRIGRAM_K = 200

STYLES = ("q1a_lean", "q1b_latex", "q1c_natural", "q2_slogan", "q3_nickname", "q4_special_case")


EMBEDDING_SQL = """
WITH ann AS (
    SELECT e.slogan_id, e.embedding
    FROM embedding e
    JOIN lean_slogan_ids ls ON ls.slogan_id = e.slogan_id
    WHERE e.model_name = %(model)s
    ORDER BY
        binary_quantize(e.embedding)::bit(4096)
        <~>
        binary_quantize(%(q)s::vector(4096))::bit(4096)
    LIMIT %(ann_k)s
)
SELECT
    s.slogan_id,
    st.statement_id,
    p.paper_id,
    p.external_id          AS paper_external_id,
    fm.decl_name,
    st.kind,
    1.0 - (ann.embedding <=> %(q)s::vector(4096)) AS similarity
FROM ann
JOIN slogan s     ON s.slogan_id = ann.slogan_id
JOIN statement st ON st.statement_id = s.statement_id
JOIN paper p      ON p.paper_id = st.paper_id
LEFT JOIN formal_metadata fm ON fm.statement_id = st.statement_id
ORDER BY ann.embedding <=> %(q)s::vector(4096)
LIMIT %(out_k)s;
"""

TEMP_TABLE_SQL = """
CREATE TEMP TABLE IF NOT EXISTS lean_slogan_ids AS
SELECT s.slogan_id
FROM slogan s
JOIN statement st ON st.statement_id = s.statement_id
JOIN paper p      ON p.paper_id     = st.paper_id
WHERE s.model_name = ANY(%(slogan_models)s)
  AND NOT s.insufficient_context
  AND p.source = ANY(%(sources)s)
  AND p.external_id = ANY(%(mathlib_ids)s)
"""

TRIGRAM_INDEX_SQL = """
CREATE TEMP TABLE IF NOT EXISTS mathlib_decl_names AS
SELECT DISTINCT fm.decl_name, st.statement_id, st.kind, p.paper_id
FROM formal_metadata fm
JOIN statement st ON st.statement_id = fm.statement_id
JOIN paper p      ON p.paper_id     = st.paper_id
WHERE p.external_id = ANY(%(mathlib_ids)s)
  AND fm.decl_name IS NOT NULL
"""

TRIGRAM_SQL = """
SELECT statement_id, paper_id, decl_name, kind,
       similarity(decl_name, %(q)s) AS trigram_sim
FROM mathlib_decl_names
WHERE decl_name %% %(q)s
  AND similarity(decl_name, %(q)s) >= %(min_sim)s
ORDER BY trigram_sim DESC
LIMIT %(k)s
"""

# Graph expansion: for each top-K cosine candidate, surface its formal_dependency
# parents (extends/field/sig edges) as additional candidates. Catches the
# "Functor.IsEquivalence retrieved at rank 1, but gold was Functor (its parent)"
# failure mode. Filters parents to the Mathlib pin so we don't surface community
# project decls.
GRAPH_EXPAND_SQL = """
SELECT DISTINCT
    fd.src_id::text                       AS child_id,
    parent.statement_id::text             AS parent_id,
    parent.paper_id                       AS parent_paper_id,
    parent_fm.decl_name                   AS parent_decl_name,
    parent.kind                           AS parent_kind
FROM formal_dependency fd
JOIN statement parent ON parent.statement_id = fd.dep_id
JOIN paper p ON p.paper_id = parent.paper_id
JOIN formal_metadata parent_fm ON parent_fm.statement_id = parent.statement_id
WHERE fd.src_id = ANY(%(child_ids)s::uuid[])
  AND fd.edge_type IN ('extends','field','sig')
  AND p.external_id = ANY(%(mathlib_ids)s)
  AND parent_fm.decl_name IS NOT NULL
"""


def query_is_name_like(query: str) -> bool:
    """Heuristic: only apply trigram retrieval when the query looks like a Lean
    decl name (short, few words, no LaTeX). For long descriptive queries the
    trigram channel pulls in spurious word-fragment matches that dilute RRF.

    Tuned on a 5-cell smoke test: q3_nickname (e.g. "lattice") was correctly
    elevated to rank 1; q1b_latex ("a poset with binary $\\sqcup$...") was
    polluted by `Set.biUnion_and'` (spurious "binary" match) and lost its
    cosine-side rank-7 hit. This gate prevents that.
    """
    q = query.strip()
    if len(q) > 40: return False
    if "$" in q or "\\" in q: return False
    if len(q.split()) > 4: return False
    return True


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
    host = os.environ.get("RDS_HOST", "localhost")
    port = int(os.environ.get("RDS_PORT", "5432"))
    conn = psycopg2.connect(host=host, port=port, dbname="v2",
        user=secret["username"], password=secret["password"], sslmode="require",
        options=f"-c statement_timeout={STMT_TIMEOUT_MS}")
    with conn.cursor() as cur:
        cur.execute("SELECT '[1]'::vector(1)"); cur.fetchone()
        cur.execute("SET hnsw.iterative_scan = relaxed_order")
        cur.execute(f"SET hnsw.ef_search = {EF_SEARCH}")
        # Use 0.2 trigram threshold (default is 0.3, lower catches more candidates)
        cur.execute("SET pg_trgm.similarity_threshold = 0.2")
    return conn


def build_temp_tables(conn, do_trigram: bool) -> tuple[int, int]:
    with conn.cursor() as cur:
        cur.execute(TEMP_TABLE_SQL, {
            "slogan_models": SLOGAN_MODELS,
            "sources": SOURCES,
            "mathlib_ids": MATHLIB_EXTERNAL_IDS,
        })
        cur.execute("CREATE INDEX IF NOT EXISTS lean_slogan_ids_pk ON lean_slogan_ids (slogan_id)")
        cur.execute("SELECT COUNT(*) FROM lean_slogan_ids")
        n_slogans = cur.fetchone()[0]
        n_names = 0
        if do_trigram:
            cur.execute(TRIGRAM_INDEX_SQL, {"mathlib_ids": MATHLIB_EXTERNAL_IDS})
            cur.execute("CREATE INDEX IF NOT EXISTS mathlib_decl_names_trgm "
                        "ON mathlib_decl_names USING gin (decl_name gin_trgm_ops)")
            cur.execute("ANALYZE mathlib_decl_names")
            cur.execute("SELECT COUNT(*) FROM mathlib_decl_names")
            n_names = cur.fetchone()[0]
        cur.execute("ANALYZE lean_slogan_ids")
    conn.commit()
    return n_slogans, n_names


def make_oai(env): return OpenAI(base_url="https://api.studio.nebius.ai/v1/", api_key=env["NEBIUS_API_KEY"])


def resolve_provider_model(conn) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT model FROM embedding_model WHERE name = %s", (EMBED_MODEL,))
        return cur.fetchone()[0]


def embed_query(oai, provider_model: str, query: str) -> list[float]:
    resp = oai.embeddings.create(model=provider_model, input=QUERY_INSTRUCTION + query, encoding_format="float")
    v = resp.data[0].embedding
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n > 0 else v


def embed_doc(oai, provider_model: str, text: str) -> list[float]:
    """Embed with the corpus-side (doc) instruction. Used for HyDE pseudo-docs."""
    resp = oai.embeddings.create(model=provider_model, input=DOC_INSTRUCTION + text, encoding_format="float")
    v = resp.data[0].embedding
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n > 0 else v


def hyde_expand(oai, query: str) -> str:
    """Generate a hypothetical Lean-decl description for the query."""
    resp = oai.chat.completions.create(
        model=HYDE_LLM_MODEL,
        messages=[
            {"role": "system", "content": HYDE_SYSTEM},
            {"role": "user", "content": f"Query: {query}\n\nWrite the matching decl's description:"},
        ],
        max_tokens=200,
        temperature=0.0,
    )
    return resp.choices[0].message.content.strip()


def vec_literal(v): return "[" + ",".join(f"{x:.7g}" for x in v) + "]"


def retrieve_cosine(conn, qvec_lit: str, ann_k: int, out_k: int) -> list[dict]:
    """Return up to out_k cosine-ranked candidates from the binary HNSW shortlist."""
    with conn.cursor() as cur:
        cur.execute(EMBEDDING_SQL, {"q": qvec_lit, "model": EMBED_MODEL,
                                    "ann_k": ann_k, "out_k": out_k})
        rows = cur.fetchall()
    return [{"slogan_id": str(r[0]), "statement_id": str(r[1]),
             "paper_id": str(r[2]), "paper_external_id": r[3],
             "decl_name": r[4], "kind": r[5], "similarity": float(r[6])}
            for r in rows]


def expand_graph_parents(conn, candidates: list[dict], max_children: int = 50) -> list[dict]:
    """For each candidate (up to max_children), look up its formal_dependency
    parents via extends/field/sig edges. Returns a flat list of parent dicts in
    candidate-result shape. Caller is responsible for fusing them back into the
    candidate ranking (e.g. via RRF).

    A parent's "rank" for fusion purposes is the rank of the child that
    surfaced it (so a parent of a top-1 candidate is treated as if it were at
    rank ~1 itself — that's the whole point of graph expansion).
    """
    if not candidates:
        return []
    child_ids = [c["statement_id"] for c in candidates[:max_children]]
    with conn.cursor() as cur:
        cur.execute(GRAPH_EXPAND_SQL, {"child_ids": child_ids,
                                        "mathlib_ids": MATHLIB_EXTERNAL_IDS})
        rows = cur.fetchall()
    # Map child_id -> child's rank in the cosine list
    rank_by_child = {c["statement_id"]: i for i, c in enumerate(candidates, 1)}
    # For each parent, take the BEST (lowest) rank of any child that surfaced it
    best_parent_rank = {}
    parent_info = {}
    for child_id, parent_id, parent_paper, parent_decl, parent_kind in rows:
        child_rank = rank_by_child.get(child_id, 999)
        if parent_id not in best_parent_rank or child_rank < best_parent_rank[parent_id]:
            best_parent_rank[parent_id] = child_rank
            parent_info[parent_id] = {
                "statement_id": parent_id,
                "paper_id": str(parent_paper),
                "decl_name": parent_decl,
                "kind": parent_kind,
                "via_graph_expand_from_rank": child_rank,
            }
    expansions = sorted(parent_info.values(), key=lambda x: x["via_graph_expand_from_rank"])
    return expansions


def retrieve_trigram(conn, query: str, k: int, min_sim: float = 0.5) -> list[dict]:
    """Returns up to k decls whose name has trigram-similarity ≥ min_sim with
    the query. Gated by min_sim=0.5 by default to filter coincidental word
    fragments (e.g. "binary" → biUnion); 0.5 keeps real lexical matches like
    "lattice"→Lattice (sim=1.0)."""
    with conn.cursor() as cur:
        cur.execute(TRIGRAM_SQL, {"q": query, "k": k, "min_sim": min_sim})
        rows = cur.fetchall()
    return [{"statement_id": str(r[0]), "paper_id": str(r[1]),
             "decl_name": r[2], "kind": r[3], "trigram_sim": float(r[4])}
            for r in rows]


def dedupe_by_decl(candidates: list[dict]) -> list[dict]:
    """Keep one row per statement_id — the highest-ranked occurrence.

    Candidates are assumed pre-sorted by rank (best first).
    """
    seen = set()
    out = []
    for c in candidates:
        sid = c["statement_id"]
        if sid in seen:
            continue
        seen.add(sid)
        out.append(c)
    return out


def rrf_fuse(list_a: list[dict], list_b: list[dict],
             tag_a: str = "a", tag_b: str = "b") -> list[dict]:
    """Reciprocal-rank fusion of two ranked candidate lists. Each contributes
    1/(RRF_K + rank). Output is sorted descending by summed RRF score and
    carries an `rrf_score` and per-channel rank fields named `{tag}_rank` so
    repeated fusions (e.g. cosine+hyde then +trigram) don't trample each
    other's metadata."""
    scores = defaultdict(float)
    info = {}
    for rank, c in enumerate(list_a, 1):
        sid = c["statement_id"]
        scores[sid] += 1.0 / (RRF_K + rank)
        info.setdefault(sid, dict(c))
        info[sid].setdefault(f"{tag_a}_rank", rank)
    for rank, c in enumerate(list_b, 1):
        sid = c["statement_id"]
        scores[sid] += 1.0 / (RRF_K + rank)
        info.setdefault(sid, dict(c))
        info[sid].setdefault(f"{tag_b}_rank", rank)
        # Optional: surface a per-channel similarity score if the candidate carries one.
        for k in ("trigram_sim", "similarity"):
            if k in c and k not in info[sid]:
                info[sid][k] = c[k]
    out = sorted(info.values(), key=lambda x: -scores[x["statement_id"]])
    for c in out:
        c["rrf_score"] = scores[c["statement_id"]]
    return out


def first_hit_rank(top10: list[dict], target_full_name: str, mathlib_paper_ids: set[str]) -> Optional[int]:
    for i, r in enumerate(top10, 1):
        if r.get("paper_id") in mathlib_paper_ids and r.get("decl_name") == target_full_name:
            return i
    return None


def metric(hit_rank): return (1.0, 1.0 / math.log2(hit_rank + 1)) if hit_rank else (0.0, 0.0)


def aggregate(rows: list[dict], filt=lambda r: True) -> dict:
    sub = [r for r in rows if filt(r)]
    if not sub: return {"n": 0, "recall@10": None, "ndcg@10": None}
    return {"n": len(sub),
            "recall@10": sum(r["recall@10"] for r in sub) / len(sub),
            "ndcg@10": sum(r["ndcg@10"] for r in sub) / len(sub)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dedupe", action="store_true")
    ap.add_argument("--ann-k", type=int, default=DEFAULT_ANN_K)
    ap.add_argument("--hybrid-trigram", action="store_true",
                    help="Add a trigram-on-decl_name score channel, RRF-fused with "
                         "cosine. Gated to name-like queries (short, no LaTeX) only.")
    ap.add_argument("--trigram-min-sim", type=float, default=0.5,
                    help="Trigram similarity threshold; 0.5 filters out coincidental "
                         "word-fragment matches like 'binary' → biUnion.")
    ap.add_argument("--hyde", choices=["off", "replace", "ensemble"], default="off",
                    help="off: bare query embedding. replace: HyDE pseudo-doc replaces "
                         "query embedding. ensemble: RRF-fuse cosine(query) + cosine(pseudo-doc).")
    ap.add_argument("--graph-expand", action="store_true",
                    help="After cosine retrieval, surface each top-K candidate's "
                         "formal_dependency parents (extends/field/sig) as additional "
                         "candidates. Fuses via RRF using the child's rank as the "
                         "parent's pseudo-rank. Addresses the 'namesake child crowds "
                         "out base concept' failure mode.")
    ap.add_argument("--graph-expand-max-children", type=int, default=50)
    ap.add_argument("--embed-model", default=DEFAULT_EMBED_MODEL,
                    help="embedding_model.name to query against (e.g. 'qwen3-8b' or "
                         "'qwen3-8b-augminimal' for the augmented-text re-embed).")
    ap.add_argument("--pilot", type=int, default=0,
                    help="Limit to first N populated cells (sanity test).")
    ap.add_argument("--tag", default=None,
                    help="Output filename tag. If omitted, derived from toggles.")
    args = ap.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    tag_parts = []
    if args.embed_model != DEFAULT_EMBED_MODEL:
        tag_parts.append(args.embed_model.replace("qwen3-8b-", ""))
    if args.dedupe: tag_parts.append("dedupe")
    if args.ann_k != DEFAULT_ANN_K: tag_parts.append(f"annk{args.ann_k}")
    if args.hybrid_trigram: tag_parts.append("trigram")
    if args.hyde != "off": tag_parts.append(f"hyde-{args.hyde}")
    if args.graph_expand: tag_parts.append("graph")
    if not tag_parts: tag_parts.append("baseline")
    tag = args.tag or "_".join(tag_parts)

    global EMBED_MODEL
    EMBED_MODEL = args.embed_model

    env = load_env()
    conn = db_connect(env)
    oai = make_oai(env)
    provider_model = resolve_provider_model(conn)
    t_init = time.time()
    n_slogans, n_names = build_temp_tables(conn, args.hybrid_trigram)
    print(f"[init] tag={tag} ann_k={args.ann_k} dedupe={args.dedupe} hybrid={args.hybrid_trigram}",
          file=sys.stderr, flush=True)
    print(f"[init] lean_slogan_ids={n_slogans} mathlib_decl_names={n_names} init={time.time()-t_init:.1f}s",
          file=sys.stderr, flush=True)

    bench = json.load(open(BENCH_DIR / "MathlibQR.json"))
    shared = json.load(open(BENCH_DIR / "MathlibQR_shared171.json"))
    shared171 = set(shared["shared_declarations"])

    with conn.cursor() as cur:
        cur.execute("SELECT paper_id FROM paper WHERE external_id = ANY(%s)", (MATHLIB_EXTERNAL_IDS,))
        mathlib_paper_ids = {str(r[0]) for r in cur.fetchall()}

    cells = []
    for r in bench:
        for s in STYLES:
            q = (r.get(s) or "").strip()
            if not q: continue
            cells.append({"decl_id": r["id"], "full_name": r["full_name"],
                          "file": r.get("file"), "difficulty": r.get("difficulty"),
                          "kind": r.get("kind"), "style": s, "query": q,
                          "in_shared171": r["full_name"] in shared171})
    print(f"[init] populated query cells: {len(cells)}", file=sys.stderr, flush=True)
    if args.pilot: cells = cells[: args.pilot]

    # When fusing trigram + cosine, fetch more cosine candidates to give RRF
    # something to fuse against. ann_k controls the binary-HNSW shortlist;
    # out_k controls how many we ask the cosine SQL to return.
    out_k = max(50, TOP_K * 5)

    jsonl_path = DATA_DIR / f"per_query_v2_{tag}.jsonl"
    sum_path   = DATA_DIR / f"summary_v2_{tag}.json"
    results = []
    t_start = time.time()

    # Resume support: if the JSONL already exists, skip cells whose
    # (decl_id, style) pair has been written. Append (not truncate) so
    # interrupted runs can pick back up.
    done_keys = set()
    if jsonl_path.exists() and jsonl_path.stat().st_size > 0:
        try:
            for line in open(jsonl_path):
                if not line.strip(): continue
                r = json.loads(line)
                done_keys.add((r["decl_id"], r["style"]))
                results.append(r)
            print(f"[init] resume: {len(done_keys)} cells already done in {jsonl_path}",
                  file=sys.stderr, flush=True)
        except (json.JSONDecodeError, KeyError) as e:
            print(f"[init] warning: could not parse existing JSONL ({e}); appending anyway",
                  file=sys.stderr)

    cells = [c for c in cells if (c["decl_id"], c["style"]) not in done_keys]
    print(f"[init] remaining cells to run: {len(cells)}", file=sys.stderr, flush=True)
    with open(jsonl_path, "a", buffering=1) as fout:
        for i, c in enumerate(cells, 1):
            t0 = time.time()
            try:
                pseudo_doc = None
                if args.hyde != "off":
                    pseudo_doc = hyde_expand(oai, c["query"])

                if args.hyde == "replace":
                    qvec = embed_doc(oai, provider_model, pseudo_doc)
                else:
                    qvec = embed_query(oai, provider_model, c["query"])
                cosine_hits = retrieve_cosine(conn, vec_literal(qvec), args.ann_k, out_k)

                if args.hyde == "ensemble":
                    pvec = embed_doc(oai, provider_model, pseudo_doc)
                    hyde_hits = retrieve_cosine(conn, vec_literal(pvec), args.ann_k, out_k)
                    cosine_hits = rrf_fuse(cosine_hits, hyde_hits, tag_a="cosine", tag_b="hyde")

                if args.graph_expand:
                    parents = expand_graph_parents(conn, cosine_hits,
                                                    max_children=args.graph_expand_max_children)
                    cosine_hits = rrf_fuse(cosine_hits, parents, tag_a="cosine", tag_b="graph")

                if args.hybrid_trigram and query_is_name_like(c["query"]):
                    trigram_hits = retrieve_trigram(conn, c["query"], TRIGRAM_K, min_sim=args.trigram_min_sim)
                    fused = rrf_fuse(cosine_hits, trigram_hits, tag_a="cosine", tag_b="trigram")
                else:
                    fused = cosine_hits
                if args.dedupe:
                    fused = dedupe_by_decl(fused)
                top10 = fused[:TOP_K]
                hit_rank = first_hit_rank(top10, c["full_name"], mathlib_paper_ids)
                recall, ndcg = metric(hit_rank)
                row = {**c, "hit_rank": hit_rank, "recall@10": recall,
                       "ndcg@10": ndcg, "top10": top10}
            except Exception as e:
                row = {**c, "hit_rank": None, "recall@10": 0.0,
                       "ndcg@10": 0.0, "top10": [], "error": repr(e)}
                conn.rollback()
            dt = time.time() - t0
            fout.write(json.dumps(row, ensure_ascii=False) + "\n")
            results.append(row)
            if i % 25 == 0 or i == len(cells):
                elapsed = time.time() - t_start
                rate = elapsed / i
                eta = rate * (len(cells) - i)
                hits = sum(1 for r in results if r["hit_rank"])
                print(f"[{i:4d}/{len(cells)}] {dt:.2f}s hits={hits} "
                      f"elapsed={elapsed:.0f}s eta={eta:.0f}s",
                      file=sys.stderr, flush=True)

    summary = {
        "tag": tag,
        "overall": {
            "full_946": aggregate(results),
            "fair_810": aggregate(results, lambda r: r["in_shared171"]),
        },
        "by_style": {
            "full_946": {s: aggregate(results, lambda r, s=s: r["style"] == s) for s in STYLES},
            "fair_810": {s: aggregate(results, lambda r, s=s: r["style"] == s and r["in_shared171"]) for s in STYLES},
        },
        "by_kind": {
            "fair_810": {k: aggregate(results, lambda r, k=k: r["kind"] == k and r["in_shared171"])
                          for k in sorted({r["kind"] for r in results})},
        },
        "config": {
            "dedupe": args.dedupe,
            "ann_k": args.ann_k,
            "hybrid_trigram": args.hybrid_trigram,
            "ef_search": EF_SEARCH,
            "top_k": TOP_K, "out_k": out_k, "rrf_k": RRF_K,
        },
    }
    sum_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"[done] per_query → {jsonl_path}", file=sys.stderr)
    print(f"[done] summary   → {sum_path}", file=sys.stderr)
    o = summary["overall"]
    print(f"[done] full_946: recall@10={o['full_946']['recall@10']:.4f} "
          f"ndcg@10={o['full_946']['ndcg@10']:.4f}", file=sys.stderr)
    print(f"[done] fair_810: recall@10={o['fair_810']['recall@10']:.4f} "
          f"ndcg@10={o['fair_810']['ndcg@10']:.4f}", file=sys.stderr)


if __name__ == "__main__":
    main()
