"""MathlibMPR evaluation — premise retrieval benchmark.

For each of the 69 main results in MathlibMPR.json, embed the
NL_main_result as the query and retrieve top-K candidates from the
Mathlib v427+v428 slogan corpus. A "hit" on a premise group means at
least one member of the group appears in the top-K decl_names.

Metrics (matching LSv2 Table 2):
  group_recall@K  -- fraction of groups with >=1 hit, averaged over entries
  covered@K       -- fraction of entries where ALL groups are covered

Uses the same retrieval infrastructure as run_eval_v2.py.

Usage:
  python3 eval_mpr.py --dedupe --ann-k 1000 --hybrid-trigram --hyde ensemble --graph-expand
  python3 eval_mpr.py  # baseline (no levers)
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

import boto3
import psycopg2
from openai import OpenAI


REPO_ROOT = Path("/mmfs1/gscratch/amath/simku22/TheoremSearch")
BENCH_DIR = REPO_ROOT / "formalized_graph/docs/paper_writing/leansearch_v2_external/benchmark"
DATA_DIR = REPO_ROOT / "experiments/leansearch_v2_replication/data"

DEFAULT_EMBED_MODEL = "qwen3-8b"
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
MATHLIB_EXTERNAL_IDS = ["Mathlib_v427", "Mathlib_v428"]
TOP_K = 10
DEFAULT_ANN_K = 200
EF_SEARCH = 500
STMT_TIMEOUT_MS = 120_000
RRF_K = 60
TRIGRAM_K = 200

EMBED_MODEL = DEFAULT_EMBED_MODEL

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


def load_env():
    env = {}
    with open(REPO_ROOT / ".env") as f:
        for line in f:
            if line.strip() and not line.startswith("#") and "=" in line:
                k, _, v = line.strip().partition("=")
                env[k] = v.strip("'\"")
    return env


def db_connect(env):
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
        cur.execute("SET pg_trgm.similarity_threshold = 0.2")
    return conn


def build_temp_tables(conn, do_trigram):
    with conn.cursor() as cur:
        cur.execute(TEMP_TABLE_SQL, {"slogan_models": SLOGAN_MODELS,
                                     "mathlib_ids": MATHLIB_EXTERNAL_IDS})
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


def make_oai(env):
    return OpenAI(base_url="https://api.studio.nebius.ai/v1/", api_key=env["NEBIUS_API_KEY"])


def resolve_provider_model(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT model FROM embedding_model WHERE name = %s", (EMBED_MODEL,))
        return cur.fetchone()[0]


def embed_query(oai, provider_model, query):
    resp = oai.embeddings.create(model=provider_model,
                                 input=QUERY_INSTRUCTION + query, encoding_format="float")
    v = resp.data[0].embedding
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n > 0 else v


def embed_doc(oai, provider_model, text):
    resp = oai.embeddings.create(model=provider_model,
                                 input=DOC_INSTRUCTION + text, encoding_format="float")
    v = resp.data[0].embedding
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n > 0 else v


def hyde_expand(oai, query):
    resp = oai.chat.completions.create(
        model=HYDE_LLM_MODEL,
        messages=[
            {"role": "system", "content": HYDE_SYSTEM},
            {"role": "user", "content": f"Query: {query}\n\nWrite the matching decl's description:"},
        ],
        max_tokens=200, temperature=0.0,
    )
    return resp.choices[0].message.content.strip()


def vec_literal(v):
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"


def retrieve_cosine(conn, qvec_lit, ann_k, out_k):
    with conn.cursor() as cur:
        cur.execute(EMBEDDING_SQL, {"q": qvec_lit, "model": EMBED_MODEL,
                                    "ann_k": ann_k, "out_k": out_k})
        rows = cur.fetchall()
    return [{"slogan_id": str(r[0]), "statement_id": str(r[1]),
             "paper_id": str(r[2]), "decl_name": r[3],
             "kind": r[4], "similarity": float(r[5])} for r in rows]


def retrieve_trigram(conn, query, k, min_sim=0.5):
    with conn.cursor() as cur:
        cur.execute(TRIGRAM_SQL, {"q": query, "k": k, "min_sim": min_sim})
        rows = cur.fetchall()
    return [{"statement_id": str(r[0]), "paper_id": str(r[1]),
             "decl_name": r[2], "kind": r[3], "trigram_sim": float(r[4])} for r in rows]


def expand_graph_parents(conn, candidates, max_children=50):
    if not candidates:
        return []
    child_ids = [c["statement_id"] for c in candidates[:max_children]]
    with conn.cursor() as cur:
        cur.execute(GRAPH_EXPAND_SQL, {"child_ids": child_ids,
                                       "mathlib_ids": MATHLIB_EXTERNAL_IDS})
        rows = cur.fetchall()
    rank_by_child = {c["statement_id"]: i for i, c in enumerate(candidates, 1)}
    best_parent_rank, parent_info = {}, {}
    for child_id, parent_id, parent_paper, parent_decl, parent_kind in rows:
        child_rank = rank_by_child.get(child_id, 999)
        if parent_id not in best_parent_rank or child_rank < best_parent_rank[parent_id]:
            best_parent_rank[parent_id] = child_rank
            parent_info[parent_id] = {"statement_id": parent_id, "paper_id": str(parent_paper),
                                      "decl_name": parent_decl, "kind": parent_kind,
                                      "via_graph_expand_from_rank": child_rank}
    return sorted(parent_info.values(), key=lambda x: x["via_graph_expand_from_rank"])


def rrf_fuse(list_a, list_b):
    scores = defaultdict(float)
    info = {}
    for rank, c in enumerate(list_a, 1):
        sid = c["statement_id"]
        scores[sid] += 1.0 / (RRF_K + rank)
        info.setdefault(sid, dict(c))
    for rank, c in enumerate(list_b, 1):
        sid = c["statement_id"]
        scores[sid] += 1.0 / (RRF_K + rank)
        info.setdefault(sid, dict(c))
    out = sorted(info.values(), key=lambda x: -scores[x["statement_id"]])
    for c in out:
        c["rrf_score"] = scores[c["statement_id"]]
    return out


def dedupe_by_decl(candidates):
    seen, out = set(), []
    for c in candidates:
        if c["statement_id"] not in seen:
            seen.add(c["statement_id"])
            out.append(c)
    return out


def query_is_name_like(query):
    q = query.strip()
    return len(q) <= 40 and "$" not in q and "\\" not in q and len(q.split()) <= 4


def eval_groups(top_decls, groups, k=10):
    top_set = set(top_decls[:k])
    group_hits = []
    for g in groups:
        hit = any(d in top_set for d in g["docs"])
        group_hits.append({"kind": g["kind"], "docs": g["docs"], "hit": hit})
    n_hit = sum(1 for h in group_hits if h["hit"])
    group_recall = n_hit / len(group_hits) if group_hits else 0.0
    covered = all(h["hit"] for h in group_hits)
    return group_hits, group_recall, covered


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dedupe", action="store_true")
    ap.add_argument("--ann-k", type=int, default=DEFAULT_ANN_K)
    ap.add_argument("--hybrid-trigram", action="store_true")
    ap.add_argument("--hyde", choices=["off", "replace", "ensemble"], default="off")
    ap.add_argument("--graph-expand", action="store_true")
    ap.add_argument("--graph-expand-max-children", type=int, default=50)
    ap.add_argument("--top-k", type=int, default=TOP_K)
    ap.add_argument("--tag", default=None)
    args = ap.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    tag_parts = ["mpr"]
    if args.dedupe: tag_parts.append("dedupe")
    if args.ann_k != DEFAULT_ANN_K: tag_parts.append(f"annk{args.ann_k}")
    if args.hybrid_trigram: tag_parts.append("trigram")
    if args.hyde != "off": tag_parts.append(f"hyde-{args.hyde}")
    if args.graph_expand: tag_parts.append("graph")
    if len(tag_parts) == 1: tag_parts.append("baseline")
    tag = args.tag or "_".join(tag_parts)

    global EMBED_MODEL

    env = load_env()
    conn = db_connect(env)
    oai = make_oai(env)
    provider_model = resolve_provider_model(conn)

    t_init = time.time()
    n_slogans, n_names = build_temp_tables(conn, args.hybrid_trigram)
    print(f"[init] tag={tag}  lean_slogan_ids={n_slogans}  init={time.time()-t_init:.1f}s",
          file=sys.stderr)

    data = json.load(open(BENCH_DIR / "MathlibMPR.json"))
    print(f"[init] MathlibMPR: {len(data)} entries, "
          f"{sum(len(e['premise_group']) for e in data)} groups", file=sys.stderr)

    out_k = max(50, args.top_k * 5)
    jsonl_path = DATA_DIR / f"per_query_{tag}.jsonl"
    sum_path   = DATA_DIR / f"summary_{tag}.json"

    done_ids, results = set(), []
    if jsonl_path.exists() and jsonl_path.stat().st_size > 0:
        for line in open(jsonl_path):
            if line.strip():
                r = json.loads(line)
                done_ids.add(r["id"])
                results.append(r)
        print(f"[init] resume: {len(done_ids)} done", file=sys.stderr)

    todo = [e for e in data if e["id"] not in done_ids]
    print(f"[init] remaining: {len(todo)}", file=sys.stderr)

    t_start = time.time()
    gr_k = f"group_recall@{args.top_k}"
    cov_k = f"covered@{args.top_k}"

    with open(jsonl_path, "a", buffering=1) as fout:
        for i, entry in enumerate(todo, 1):
            t0 = time.time()
            query = entry["NL_main_result"].strip()
            try:
                pseudo_doc = None
                if args.hyde != "off":
                    pseudo_doc = hyde_expand(oai, query)

                if args.hyde == "replace":
                    qvec = embed_doc(oai, provider_model, pseudo_doc)
                else:
                    qvec = embed_query(oai, provider_model, query)
                cosine_hits = retrieve_cosine(conn, vec_literal(qvec), args.ann_k, out_k)

                if args.hyde == "ensemble":
                    pvec = embed_doc(oai, provider_model, pseudo_doc)
                    hyde_hits = retrieve_cosine(conn, vec_literal(pvec), args.ann_k, out_k)
                    cosine_hits = rrf_fuse(cosine_hits, hyde_hits)

                if args.graph_expand:
                    parents = expand_graph_parents(conn, cosine_hits, args.graph_expand_max_children)
                    cosine_hits = rrf_fuse(cosine_hits, parents)

                if args.hybrid_trigram and query_is_name_like(query):
                    trigram_hits = retrieve_trigram(conn, query, TRIGRAM_K)
                    fused = rrf_fuse(cosine_hits, trigram_hits)
                else:
                    fused = cosine_hits

                if args.dedupe:
                    fused = dedupe_by_decl(fused)

                top_decls = [c["decl_name"] for c in fused if c.get("decl_name")]
                group_hits, group_recall, covered = eval_groups(
                    top_decls, entry["premise_group"], k=args.top_k)

                row = {"id": entry["id"],
                       "formal_main_result": entry["formal_main_result"],
                       "NL_main_result": query,
                       "n_groups": len(entry["premise_group"]),
                       "group_hits": group_hits,
                       gr_k: group_recall,
                       cov_k: covered,
                       "top_decls": top_decls[:args.top_k]}
            except Exception as e:
                row = {"id": entry["id"], "formal_main_result": entry["formal_main_result"],
                       "NL_main_result": query, "n_groups": len(entry["premise_group"]),
                       gr_k: 0.0, cov_k: False, "group_hits": [], "top_decls": [],
                       "error": repr(e)}
                conn.rollback()

            fout.write(json.dumps(row, ensure_ascii=False) + "\n")
            results.append(row)

            if i % 10 == 0 or i == len(todo):
                elapsed = time.time() - t_start
                eta = elapsed / i * (len(todo) - i)
                mean_gr = sum(r[gr_k] for r in results) / len(results)
                n_cov = sum(1 for r in results if r[cov_k])
                print(f"[{i:3d}/{len(todo)}] {time.time()-t0:.1f}s  "
                      f"{gr_k}={mean_gr:.3f}  covered={n_cov}/{len(results)}  "
                      f"eta={eta:.0f}s", file=sys.stderr, flush=True)

    all_groups  = [h for r in results for h in r.get("group_hits", [])]
    orig_groups = [h for h in all_groups if h.get("kind") == "original"]
    alt_groups  = [h for h in all_groups if h.get("kind") == "alternative"]

    summary = {
        "tag": tag,
        "n_entries": len(results),
        "top_k": args.top_k,
        gr_k: sum(r[gr_k] for r in results) / len(results) if results else 0,
        cov_k: sum(1 for r in results if r[cov_k]) / len(results) if results else 0,
        "group_level": {
            "total": len(all_groups),
            "hit": sum(1 for h in all_groups if h["hit"]),
            "rate": sum(1 for h in all_groups if h["hit"]) / len(all_groups) if all_groups else 0,
            "original": {"n": len(orig_groups),
                         "hit": sum(1 for h in orig_groups if h["hit"]),
                         "rate": sum(1 for h in orig_groups if h["hit"]) / len(orig_groups) if orig_groups else 0},
            "alternative": {"n": len(alt_groups),
                            "hit": sum(1 for h in alt_groups if h["hit"]),
                            "rate": sum(1 for h in alt_groups if h["hit"]) / len(alt_groups) if alt_groups else 0},
        },
        "lsv2_baselines": {"lsv2_reasoning": 0.461, "diver": 0.380,
                           "leanstatesearch": 0.093, "lsv2_covered@10": 0.304},
        "config": {"dedupe": args.dedupe, "ann_k": args.ann_k,
                   "hybrid_trigram": args.hybrid_trigram, "hyde": args.hyde,
                   "graph_expand": args.graph_expand},
    }
    sum_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"[done] {jsonl_path.name}", file=sys.stderr)
    print(f"[done] {gr_k}={summary[gr_k]:.3f}  {cov_k}={summary[cov_k]:.3f}", file=sys.stderr)
    print(f"       LSv2 reasoning: group_recall=0.461 covered=0.304 | DIVER: 0.380", file=sys.stderr)


if __name__ == "__main__":
    main()
