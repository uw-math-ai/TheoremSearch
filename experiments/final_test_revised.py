#%% ============================================================
# (For Qwen3 8B Theorem-Level Search)
# PGVECTOR THEOREM-LEVEL EVAL (exact match on (paper_id, name))
#
# Retrieval:
#   - Stage 1: binary_quantize ANN on embedding table ONLY (top DB_TOP_K slogan_ids)
#   - Stage 2: rerank those candidates by exact cosine distance
#   - Then JOIN only those slogan_ids to fetch (paper_id, name) via:
#         theorem_slogan (slogan_id -> theorem_id)
#         theorem        (theorem_id -> paper_id, name)
#   - (NO paper dedup; ranked list is theorem-level by (paper_id, name))
#
# Evaluation (theorem-level):
#   - Relevant iff retrieved.(paper_id, name) == target.(paper_id, name)
#   - Metrics: P@k, Hit@k, MRR@k, nDCG@k (binary relevance 1.0/0.0)
#
# Assumes validation_set.csv contains columns:
#   - query
#   - paper_id
#   - name
# ============================================================

import os
import re
import json
import numpy as np
import pandas as pd
import boto3
import psycopg2
import dotenv
from sentence_transformers import SentenceTransformer
from pathlib import Path
import torch

# -----------------------------
# CONFIG
# -----------------------------
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
PROJECT_ROOT = Path.cwd().parents[0]

VALS_CSV   = PROJECT_ROOT / "validation_set.csv"
QUERY_COL  = "query"
PAPER_COL  = "paper_id"
NAME_COL   = "name"   # theorem environment/name string in your dataset

MODEL_NAME = "Qwen/Qwen3-Embedding-8B"

TOP_K    = 20
DB_TOP_K = 200  # set > TOP_K so stage-1 recall doesn't bottleneck

# Tables / columns
PG_TABLE         = os.environ.get("PG_TABLE", "theorem_embedding_qwen8b")  # embedding table (has embedding + slogan_id)
PG_SLOGAN_TABLE  = os.environ.get("PG_SLOGAN_TABLE", "theorem_slogan")     # maps slogan_id -> theorem_id
PG_THEOREM_TABLE = os.environ.get("PG_THEOREM_TABLE", "theorem")           # maps theorem_id -> paper_id + name

PG_SLOGAN_ID_COL  = os.environ.get("PG_SLOGAN_ID_COL", "slogan_id")        # embedding table slogan id col (and slogan table key)
PG_THEOREM_ID_COL = os.environ.get("PG_THEOREM_ID_COL", "theorem_id")      # slogan table theorem_id col (and theorem table key)

PG_PAPER_COL = os.environ.get("PG_PAPER_COL", "paper_id")                  # on theorem table
PG_NAME_COL  = os.environ.get("PG_NAME_COL", "name")                       # on theorem table
PG_EMB_COL   = os.environ.get("PG_EMB_COL", "embedding")                   # on embedding table

BITS = 4096  # bit length for binary quantization


# -----------------------------
# DB connection (RDS Secrets Manager)
# -----------------------------
def pg_connect():
    dotenv.load_dotenv()

    secret_arn = os.environ["RDS_SECRET_ARN"]
    host = os.environ["RDS_HOST"]
    region = os.environ["AWS_REGION"]

    sm = boto3.client("secretsmanager", region_name=region)
    resp = sm.get_secret_value(SecretId=secret_arn)
    secret = json.loads(resp["SecretString"])

    user = secret.get("username", "postgres")
    password = secret["password"]
    dbname = secret.get("dbname", "postgres")
    port = int(secret.get("port", 5432))

    return psycopg2.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password,
        sslmode="require",
    )


def _validate_ident(x: str, what: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]+", x or ""):
        raise ValueError(f"Unsafe {what}: {x!r}")
    return x


def vec_to_pgvector_literal(vec):
    # pgvector accepts '[1,2,3]' for %s::vector
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"


# -----------------------------
# Two-stage ANN SQL (embedding table ONLY)
# Returns (slogan_id, score) where score = 1 - cosine_distance on reranked set
# -----------------------------
def make_pgvector_sql_two_stage_binary_then_cosine(
    emb_table: str,
    slogan_id_col: str,
    emb_col: str,
    bits: int = 4096,
):
    emb_table     = _validate_ident(emb_table, "emb_table")
    slogan_id_col = _validate_ident(slogan_id_col, "slogan_id_col")
    emb_col       = _validate_ident(emb_col, "emb_col")

    # Stage 1: binary recall distance (smaller is better)
    bin_dist = (
        f"(binary_quantize(e.{emb_col})::bit({bits}) "
        f"<~> binary_quantize(%s::vector)::bit({bits}))"
    )

    # Stage 2: exact cosine distance (smaller is better), scope is outer alias t
    cos_dist = f"(t.{emb_col} <=> %s::vector)"
    score_expr = f"(1 - {cos_dist})"

    sql = f"""
        SELECT
            t.{slogan_id_col}::text AS slogan_id,
            {score_expr}            AS score
        FROM (
            SELECT
                e.{slogan_id_col},
                e.{emb_col}
            FROM {emb_table} e
            ORDER BY {bin_dist} ASC
            LIMIT %s
        ) t
        ORDER BY (t.{emb_col} <=> %s::vector) ASC
        LIMIT %s
    """
    return sql


# -----------------------------
# Bulk fetch theorem identifiers for slogan_ids
# Returns dict: slogan_id -> (paper_id, name)
# -----------------------------
def fetch_theorem_ident_for_slogan_ids(conn, slogan_ids):
    if not slogan_ids:
        return {}

    slogan_table  = _validate_ident(PG_SLOGAN_TABLE, "slogan_table")
    theorem_table = _validate_ident(PG_THEOREM_TABLE, "theorem_table")

    slogan_id_col  = _validate_ident(PG_SLOGAN_ID_COL, "slogan_id_col")
    theorem_id_col = _validate_ident(PG_THEOREM_ID_COL, "theorem_id_col")
    paper_col      = _validate_ident(PG_PAPER_COL, "paper_col")
    name_col       = _validate_ident(PG_NAME_COL, "name_col")

    sql = f"""
        SELECT
            s.{slogan_id_col}::text AS slogan_id,
            t.{paper_col}::text     AS paper_id,
            t.{name_col}::text      AS name
        FROM {slogan_table} s
        JOIN {theorem_table} t
          ON s.{theorem_id_col} = t.{theorem_id_col}
        WHERE s.{slogan_id_col}::text = ANY(%s)
    """

    out = {}
    with conn.cursor() as cur:
        cur.execute(sql, (list(map(str, slogan_ids)),))
        for sid, pid, nm in cur.fetchall():
            out[str(sid)] = (str(pid), str(nm))
    return out


# -----------------------------
# Build ranked theorem list: entries are (paper_id, name) tuples
# Preserve slogan rank order. Optionally dedup exact duplicates.
# -----------------------------
def ranked_theorems_from_meta(slogan_ids, meta, limit_theorems):
    out = []
    seen = set()  # dedup identical (paper_id, name) if multiple slogans map to same theorem
    for sid in slogan_ids:
        if sid not in meta:
            continue
        pid, nm = meta[sid]
        key = (pid, nm)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
        if len(out) >= limit_theorems:
            break
    return out


# -----------------------------
# Theorem-level metrics
# ranked_docs entries are (paper_id, name) tuples
# relevance is exact (paper_id, name) match
# -----------------------------
def precision_at_k_theorem(ranked_docs, rel_targets, k):
    vals = []
    for q, docs in enumerate(ranked_docs):
        target = rel_targets[q]  # (paper_id, name)
        topk = docs[:k]
        num_rel = sum(1 for d in topk if d == target)
        vals.append(num_rel / k)
    return float(np.mean(vals))


def hit_at_k_theorem(ranked_docs, rel_targets, k):
    vals = []
    for q, docs in enumerate(ranked_docs):
        target = rel_targets[q]
        topk = docs[:k]
        vals.append(1.0 if target in topk else 0.0)
    return float(np.mean(vals))


def mrr_at_k_theorem(ranked_docs, rel_targets, k):
    vals = []
    for q, docs in enumerate(ranked_docs):
        target = rel_targets[q]
        rr = 0.0
        for i, d in enumerate(docs[:k], start=1):
            if d == target:
                rr = 1.0 / i
                break
        vals.append(rr)
    return float(np.mean(vals))


def _dcg(rels, gain="exp"):
    if len(rels) == 0:
        return 0.0
    rels = np.asarray(rels, dtype=float)
    if gain == "exp":
        gains = np.power(2.0, rels) - 1.0
    elif gain == "linear":
        gains = rels
    else:
        raise ValueError("gain must be 'exp' or 'linear'")
    discounts = 1.0 / np.log2(np.arange(2, rels.size + 2))
    return float(np.sum(gains * discounts))


def ndcg_at_k_theorem(ranked_docs, rel_targets, k, gain="exp"):
    vals = []
    for q, docs in enumerate(ranked_docs):
        target = rel_targets[q]
        rels = [1.0 if d == target else 0.0 for d in docs[:k]]
        dcg = _dcg(rels, gain=gain)

        ideal_rels = [1.0] + [0.0] * (k - 1)
        idcg = _dcg(ideal_rels, gain=gain)

        vals.append(0.0 if idcg == 0.0 else dcg / idcg)
    return float(np.mean(vals))


# -----------------------------
# Retrieval + evaluation
# -----------------------------
def evaluate_pgvector(model, q_texts, conn, rel_targets, top_k, db_top_k):
    sql = make_pgvector_sql_two_stage_binary_then_cosine(
        emb_table=PG_TABLE,
        slogan_id_col=PG_SLOGAN_ID_COL,
        emb_col=PG_EMB_COL,
        bits=BITS,
    )

    print(f"Encoding {len(q_texts)} queries with {MODEL_NAME} ...")
    q_emb = model.encode(
        q_texts,
        batch_size=8,
        show_progress_bar=True,
        normalize_embeddings=False,
        prompt="Instruct: Given a math search query, retrieve theorems mathematically equivalent to the query. \nQuery:",
    )

    ranked_docs = []

    print(f"Retrieving top-{db_top_k} slogan_ids per query via pgvector (binary->cosine rerank) ...")
    with conn.cursor() as cur:
        for i in range(len(q_texts)):
            if i % 25 == 0:
                print(f"  query {i}/{len(q_texts)}")

            qvec_str = vec_to_pgvector_literal(q_emb[i].tolist())

            # two-stage SQL expects 5 params:
            # 1) query for binary
            # 2) query for score expr (cosine)
            # 3) inner LIMIT
            # 4) query for final ORDER BY (cosine)
            # 5) outer LIMIT
            cur.execute(sql, (qvec_str, qvec_str, db_top_k, qvec_str, db_top_k))
            rows = cur.fetchall()  # (slogan_id, score) in reranked order

            slogan_ids = [str(sid) for (sid, _score) in rows]

            # Join only this small candidate set to get theorem identifier (paper_id, name)
            meta = fetch_theorem_ident_for_slogan_ids(conn, slogan_ids)

            # Preserve slogan rank, output theorem-level ids (paper_id, name)
            docs = ranked_theorems_from_meta(slogan_ids, meta, limit_theorems=top_k)
            ranked_docs.append(docs)

    print("=" * 60)
    print(f"Results @ {top_k}  (Exact = (paper_id, name) match)")
    print(f"P@1     : {precision_at_k_theorem(ranked_docs, rel_targets, 1)}")
    print(f"Hit@10  : {hit_at_k_theorem(ranked_docs, rel_targets, 10)}")
    print(f"Hit@20  : {hit_at_k_theorem(ranked_docs, rel_targets, 20)}")
    print(f"MRR@20  : {mrr_at_k_theorem(ranked_docs, rel_targets, 20)}")
    print(f"nDCG@20 : {ndcg_at_k_theorem(ranked_docs, rel_targets, 20, gain='exp')}")
    print("=" * 60)

    return ranked_docs


# -----------------------------
# MAIN
# -----------------------------
def main():
    vals = pd.read_csv(VALS_CSV, header=0, index_col=0, dtype={PAPER_COL: str})

    for c in [QUERY_COL, PAPER_COL, NAME_COL]:
        if c not in vals.columns:
            raise ValueError(f"{VALS_CSV} missing column {c!r}. Found: {list(vals.columns)}")

    q_texts = vals[QUERY_COL].astype(str).tolist()
    rel_targets = list(zip(vals[PAPER_COL].astype(str).tolist(), vals[NAME_COL].astype(str).tolist()))

    print("Model:", MODEL_NAME)
    print("Embedding table:", PG_TABLE)
    print("Slogan table:", PG_SLOGAN_TABLE)
    print("Theorem table:", PG_THEOREM_TABLE)
    print("Relevance: exact (paper_id, name) match")
    print("TOP_K:", TOP_K, "DB_TOP_K:", DB_TOP_K)
    print("BITS:", BITS)
    print("CSV columns:", list(vals.columns))

    model = SentenceTransformer(
        MODEL_NAME,
        trust_remote_code=True,
        model_kwargs={"dtype": torch.bfloat16, "low_cpu_mem_usage": True},
    )

    conn = pg_connect()
    try:
        print("Queries:", len(vals))
        evaluate_pgvector(
            model=model,
            q_texts=q_texts,
            conn=conn,
            rel_targets=rel_targets,
            top_k=TOP_K,
            db_top_k=DB_TOP_K,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()


#%% ============================================================
# (For Qwen3 8B Paper-Level Search)
# PGVECTOR PAPER-LEVEL EVAL (paper_id exact match)
#
# Retrieval:
#   - Stage 1: binary_quantize ANN on embedding table ONLY (top DB_TOP_K slogan_ids)
#   - Stage 2: rerank those candidates by exact cosine distance
#   - Then JOIN only those slogan_ids to fetch paper_id (+ optional name)
#   - Deduplicate results by paper_id while preserving rank order (Google-like)
#
# Evaluation (paper-level):
#   - Relevant iff retrieved.paper_id == target.paper_id
#   - Metrics: P@k, Hit@k, MRR@k, nDCG@k (binary relevance 1.0/0.0)
# ============================================================

import os
import re
import json
import numpy as np
import pandas as pd
import boto3
import psycopg2
import dotenv
from sentence_transformers import SentenceTransformer
from pathlib import Path
import torch

# -----------------------------
# CONFIG
# -----------------------------
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
PROJECT_ROOT = Path.cwd().parents[0]

VALS_CSV   = PROJECT_ROOT / "validation_set.csv"
QUERY_COL  = "query"
PAPER_COL  = "paper_id"
NAME_COL   = "name"   # read for compatibility; NOT used for judging

MODEL_NAME = "Qwen/Qwen3-Embedding-8B"

TOP_K    = 20
DB_TOP_K = 200  # IMPORTANT: set > TOP_K so paper-dedup still leaves >= TOP_K

# Tables / columns
PG_TABLE         = os.environ.get("PG_TABLE", "theorem_embedding_qwen8b")  # embedding table (has embedding + slogan_id)
PG_SLOGAN_TABLE  = os.environ.get("PG_SLOGAN_TABLE", "theorem_slogan")     # slogan table (maps slogan_id -> theorem_id)
PG_THEOREM_TABLE = os.environ.get("PG_THEOREM_TABLE", "theorem")           # theorem table (maps theorem_id -> paper_id + name)

PG_SLOGAN_ID_COL  = os.environ.get("PG_SLOGAN_ID_COL", "slogan_id")        # embedding table slogan id col (and slogan table key)
PG_THEOREM_ID_COL = os.environ.get("PG_THEOREM_ID_COL", "theorem_id")      # slogan table theorem_id col (and theorem table key)

PG_PAPER_COL = os.environ.get("PG_PAPER_COL", "paper_id")                  # on theorem table
PG_NAME_COL  = os.environ.get("PG_NAME_COL", "name")                       # on theorem table
PG_EMB_COL   = os.environ.get("PG_EMB_COL", "embedding")                   # on embedding table

BITS = 4096  # bit length for binary quantization


# -----------------------------
# DB connection (RDS Secrets Manager)
# -----------------------------
def pg_connect():
    dotenv.load_dotenv()

    secret_arn = os.environ["RDS_SECRET_ARN"]
    host = os.environ["RDS_HOST"]
    region = os.environ["AWS_REGION"]

    sm = boto3.client("secretsmanager", region_name=region)
    resp = sm.get_secret_value(SecretId=secret_arn)
    secret = json.loads(resp["SecretString"])

    user = secret.get("username", "postgres")
    password = secret["password"]
    dbname = secret.get("dbname", "postgres")
    port = int(secret.get("port", 5432))

    return psycopg2.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password,
        sslmode="require",
    )


def _validate_ident(x: str, what: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]+", x or ""):
        raise ValueError(f"Unsafe {what}: {x!r}")
    return x


def vec_to_pgvector_literal(vec):
    # pgvector accepts '[1,2,3]' for %s::vector
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"


# -----------------------------
# Two-stage ANN SQL (embedding table ONLY)
# Returns (slogan_id, score) where score = 1 - cosine_distance on reranked set
#
# Equivalent shape to:
#   SELECT * FROM (
#     SELECT * FROM emb_table
#     ORDER BY binary_quantize(embedding)::bit(BITS) <~> binary_quantize(query)
#     LIMIT DB_TOP_K
#   ) t
#   ORDER BY t.embedding <=> query
#   LIMIT DB_TOP_K;
# -----------------------------
def make_pgvector_sql_two_stage_binary_then_cosine(
    emb_table: str,
    slogan_id_col: str,
    emb_col: str,
    bits: int = 4096,
):
    emb_table     = _validate_ident(emb_table, "emb_table")
    slogan_id_col = _validate_ident(slogan_id_col, "slogan_id_col")
    emb_col       = _validate_ident(emb_col, "emb_col")

    # Stage 1: binary recall distance (smaller is better)
    bin_dist = (
        f"(binary_quantize(e.{emb_col})::bit({bits}) "
        f"<~> binary_quantize(%s::vector)::bit({bits}))"
    )

    # Stage 2: exact cosine distance (smaller is better), scope is outer alias t
    cos_dist = f"(t.{emb_col} <=> %s::vector)"
    score_expr = f"(1 - {cos_dist})"

    sql = f"""
        SELECT
            t.{slogan_id_col}::text AS slogan_id,
            {score_expr}            AS score
        FROM (
            SELECT
                e.{slogan_id_col},
                e.{emb_col}
            FROM {emb_table} e
            ORDER BY {bin_dist} ASC
            LIMIT %s
        ) t
        ORDER BY (t.{emb_col} <=> %s::vector) ASC
        LIMIT %s
    """
    return sql


# -----------------------------
# Bulk fetch metadata for slogan_ids
# Returns dict: slogan_id -> (paper_id, name)
# -----------------------------
def fetch_metadata_for_slogan_ids(conn, slogan_ids):
    if not slogan_ids:
        return {}

    slogan_table  = _validate_ident(PG_SLOGAN_TABLE, "slogan_table")
    theorem_table = _validate_ident(PG_THEOREM_TABLE, "theorem_table")

    slogan_id_col  = _validate_ident(PG_SLOGAN_ID_COL, "slogan_id_col")
    theorem_id_col = _validate_ident(PG_THEOREM_ID_COL, "theorem_id_col")
    paper_col      = _validate_ident(PG_PAPER_COL, "paper_col")
    name_col       = _validate_ident(PG_NAME_COL, "name_col")

    sql = f"""
        SELECT
            s.{slogan_id_col}::text AS slogan_id,
            t.{paper_col}::text     AS paper_id,
            t.{name_col}::text      AS name
        FROM {slogan_table} s
        JOIN {theorem_table} t
          ON s.{theorem_id_col} = t.{theorem_id_col}
        WHERE s.{slogan_id_col}::text = ANY(%s)
    """

    out = {}
    with conn.cursor() as cur:
        cur.execute(sql, (list(map(str, slogan_ids)),))
        for sid, pid, nm in cur.fetchall():
            out[str(sid)] = (str(pid), str(nm))
    return out


# -----------------------------
# Deduplicate by paper_id while preserving rank order
# -----------------------------
def dedup_ranked_by_paper_from_meta(slogan_ids, meta, limit_papers):
    seen = set()
    out = []
    for sid in slogan_ids:
        if sid not in meta:
            continue
        pid, nm = meta[sid]
        if pid in seen:
            continue
        seen.add(pid)
        out.append((pid, nm))
        if len(out) >= limit_papers:
            break
    return out


# -----------------------------
# Paper-level metrics
# ranked_docs entries are (paper_id, name) tuples
# relevance is exact paper_id match
# -----------------------------
def precision_at_k_paper(ranked_docs, rel_paper_ids, k):
    vals = []
    for q, docs in enumerate(ranked_docs):
        target = rel_paper_ids[q]
        topk = docs[:k]
        num_rel = sum(1 for (pid, _nm) in topk if pid == target)
        vals.append(num_rel / k)
    return float(np.mean(vals))


def hit_at_k_paper(ranked_docs, rel_paper_ids, k):
    vals = []
    for q, docs in enumerate(ranked_docs):
        target = rel_paper_ids[q]
        topk = docs[:k]
        vals.append(1.0 if any(pid == target for (pid, _nm) in topk) else 0.0)
    return float(np.mean(vals))


def mrr_at_k_paper(ranked_docs, rel_paper_ids, k):
    vals = []
    for q, docs in enumerate(ranked_docs):
        target = rel_paper_ids[q]
        rr = 0.0
        for i, (pid, _nm) in enumerate(docs[:k], start=1):
            if pid == target:
                rr = 1.0 / i
                break
        vals.append(rr)
    return float(np.mean(vals))


def _dcg(rels, gain="exp"):
    if len(rels) == 0:
        return 0.0
    rels = np.asarray(rels, dtype=float)
    if gain == "exp":
        gains = np.power(2.0, rels) - 1.0
    elif gain == "linear":
        gains = rels
    else:
        raise ValueError("gain must be 'exp' or 'linear'")
    discounts = 1.0 / np.log2(np.arange(2, rels.size + 2))
    return float(np.sum(gains * discounts))


def ndcg_at_k_paper(ranked_docs, rel_paper_ids, k, gain="exp"):
    vals = []
    for q, docs in enumerate(ranked_docs):
        target = rel_paper_ids[q]
        rels = [1.0 if pid == target else 0.0 for (pid, _nm) in docs[:k]]
        dcg = _dcg(rels, gain=gain)

        ideal_rels = [1.0] + [0.0] * (k - 1)
        idcg = _dcg(ideal_rels, gain=gain)

        vals.append(0.0 if idcg == 0.0 else dcg / idcg)
    return float(np.mean(vals))


# -----------------------------
# Retrieval + evaluation
# -----------------------------
def evaluate_pgvector(model, queries, conn, rel_paper_ids, top_k, db_top_k):
    sql = make_pgvector_sql_two_stage_binary_then_cosine(
        emb_table=PG_TABLE,
        slogan_id_col=PG_SLOGAN_ID_COL,
        emb_col=PG_EMB_COL,
        bits=BITS,
    )

    q_texts = [q[0] if isinstance(q, (tuple, list)) else q for q in queries]
    print(f"Encoding {len(q_texts)} queries with {MODEL_NAME} ...")
    q_emb = model.encode(
        q_texts,
        batch_size=8,
        show_progress_bar=True,
        normalize_embeddings=False,
        prompt="Instruct: Given a math search query, retrieve theorems mathematically equivalent to the query. \nQuery:",
    )

    ranked_docs = []

    print(f"Retrieving top-{db_top_k} slogan_ids per query via pgvector (binary->cosine rerank) ...")
    with conn.cursor() as cur:
        for i in range(len(q_texts)):
            print(f"retrieving query {i}")
            qvec_str = vec_to_pgvector_literal(q_emb[i].tolist())

            # two-stage SQL expects 5 params:
            # 1) query for binary
            # 2) query for score expr (cosine)
            # 3) inner LIMIT
            # 4) query for final ORDER BY (cosine)
            # 5) outer LIMIT
            cur.execute(sql, (qvec_str, qvec_str, db_top_k, qvec_str, db_top_k))
            rows = cur.fetchall()  # (slogan_id, score) in reranked order

            slogan_ids = [str(sid) for (sid, _score) in rows]

            # Join only this small candidate set to get (paper_id, name)
            meta = fetch_metadata_for_slogan_ids(conn, slogan_ids)

            # Dedup by paper_id (Google-like), preserve rank
            docs = dedup_ranked_by_paper_from_meta(slogan_ids, meta, limit_papers=top_k)
            ranked_docs.append(docs)

    print("=" * 60)
    print(f"Results @ {top_k}  (Exact = paper_id match, papers deduped)")
    print(f"P@{1}    : {precision_at_k_paper(ranked_docs, rel_paper_ids, 1)}")
    print(f"Hit@{10}  : {hit_at_k_paper(ranked_docs, rel_paper_ids, 10)}")
    print(f"Hit@{20}  : {hit_at_k_paper(ranked_docs, rel_paper_ids, 20)}")
    print(f"MRR@{20}  : {mrr_at_k_paper(ranked_docs, rel_paper_ids, 20)}")
    print(f"nDCG@{20} : {ndcg_at_k_paper(ranked_docs, rel_paper_ids, 20, gain='exp')}")
    print("=" * 60)

    return ranked_docs


# -----------------------------
# MAIN
# -----------------------------
def main():
    vals = pd.read_csv(VALS_CSV, header=0, index_col=0, dtype={PAPER_COL: str})

    for c in [QUERY_COL, PAPER_COL]:
        if c not in vals.columns:
            raise ValueError(f"{VALS_CSV} missing column {c!r}. Found: {list(vals.columns)}")

    queries = list(zip(vals[QUERY_COL].astype(str).tolist(), vals[PAPER_COL].astype(str).tolist()))
    rel_paper_ids = vals[PAPER_COL].astype(str).tolist()

    print("Model:", MODEL_NAME)
    print("Embedding table:", PG_TABLE)
    print("Slogan table:", PG_SLOGAN_TABLE)
    print("Theorem table:", PG_THEOREM_TABLE)
    print("Relevance: paper_id match => exact (1.0)")
    print("TOP_K:", TOP_K, "DB_TOP_K:", DB_TOP_K)
    print("Dedup: per-query unique paper_id, rank preserved")
    print("BITS:", BITS)

    model = SentenceTransformer(
        MODEL_NAME,
        trust_remote_code=True,
        model_kwargs={"dtype": torch.bfloat16, "low_cpu_mem_usage": True},
    )

    conn = pg_connect()
    try:
        print("Queries:", len(vals))
        evaluate_pgvector(
            model=model,
            queries=queries,
            conn=conn,
            rel_paper_ids=rel_paper_ids,
            top_k=TOP_K,
            db_top_k=DB_TOP_K,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()


#%% ============================================================
# (For Qwen3 8B Paper-Level Search + Qwen3-Reranker-8B)
# PGVECTOR PAPER-LEVEL EVAL (paper_id exact match)
#
# Retrieval:
#   - Stage 1: binary_quantize ANN on embedding table ONLY (top DB_TOP_K slogan_ids)
#   - Stage 2: rerank those candidates by exact cosine distance (SQL)
#   - Stage 3: rerank candidates by Qwen/Qwen3-Reranker-8B on (query, Document)
#   - Then JOIN only those slogan_ids to fetch paper_id (+ optional name)
#   - Deduplicate results by paper_id while preserving rank order (Google-like)
#
# Evaluation (paper-level):
#   - Relevant iff retrieved.paper_id == target.paper_id
#   - Metrics: P@k, Hit@k, MRR@k, nDCG@k (binary relevance 1.0/0.0)
# ============================================================

import os
import re
import gc
import json
import numpy as np
import pandas as pd
import boto3
import psycopg2
import dotenv
from sentence_transformers import SentenceTransformer
from pathlib import Path
import torch

# NEW: reranker deps
import torch.nn.functional as F
from transformers import AutoTokenizer, AutoModelForCausalLM

# -----------------------------
# CONFIG
# -----------------------------
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
PROJECT_ROOT = Path.cwd().parents[0]

VALS_CSV   = PROJECT_ROOT / "validation_set.csv"
QUERY_COL  = "query"
PAPER_COL  = "paper_id"
NAME_COL   = "name"   # read for compatibility; NOT used for judging

# Stage-1 embedder
MODEL_NAME = "Qwen/Qwen3-Embedding-8B"

# Stage-3 reranker
RERANKER_NAME = os.environ.get("RERANKER_NAME", "Qwen/Qwen3-Reranker-8B")
RERANK_INSTRUCTION = (
    "Given a math query, decide if the Document contains a theorem/proposition "
    "that directly answers or matches the query."
)

TOP_K    = 20
DB_TOP_K = 200  # IMPORTANT: set > TOP_K so paper-dedup still leaves >= TOP_K
RERANK_TOP_N = int(os.environ.get("RERANK_TOP_N", "20"))  # rerank only top-N cosine candidates per query
RERANK_BATCH_SIZE = int(os.environ.get("RERANK_BATCH_SIZE", "4"))
RERANK_MAX_LENGTH = int(os.environ.get("RERANK_MAX_LENGTH", "8192"))

# Tables / columns
PG_TABLE         = os.environ.get("PG_TABLE", "theorem_embedding_qwen8b")  # embedding table (has embedding + slogan_id)
PG_SLOGAN_TABLE  = os.environ.get("PG_SLOGAN_TABLE", "theorem_slogan")     # slogan table (maps slogan_id -> theorem_id + text)
PG_THEOREM_TABLE = os.environ.get("PG_THEOREM_TABLE", "theorem")           # theorem table (maps theorem_id -> paper_id + name)

PG_SLOGAN_ID_COL  = os.environ.get("PG_SLOGAN_ID_COL", "slogan_id")        # embedding table slogan id col (and slogan table key)
PG_THEOREM_ID_COL = os.environ.get("PG_THEOREM_ID_COL", "theorem_id")      # slogan table theorem_id col (and theorem table key)

PG_PAPER_COL = os.environ.get("PG_PAPER_COL", "paper_id")                  # on theorem table
PG_NAME_COL  = os.environ.get("PG_NAME_COL", "name")                       # on theorem table
PG_EMB_COL   = os.environ.get("PG_EMB_COL", "embedding")                   # on embedding table

# NEW: doc text column on slogan table for reranking
# Change via env var if your schema differs, e.g. PG_DOC_COL=statement or PG_DOC_COL=tex
PG_DOC_COL  = os.environ.get("PG_DOC_COL", "slogan")

BITS = 4096  # bit length for binary quantization


# -----------------------------
# DB connection (RDS Secrets Manager)
# -----------------------------
def pg_connect():
    dotenv.load_dotenv()

    secret_arn = os.environ["RDS_SECRET_ARN"]
    host = os.environ["RDS_HOST"]
    region = os.environ["AWS_REGION"]

    sm = boto3.client("secretsmanager", region_name=region)
    resp = sm.get_secret_value(SecretId=secret_arn)
    secret = json.loads(resp["SecretString"])

    user = secret.get("username", "postgres")
    password = secret["password"]
    dbname = secret.get("dbname", "postgres")
    port = int(secret.get("port", 5432))

    return psycopg2.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password,
        sslmode="require",
    )


def _validate_ident(x: str, what: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]+", x or ""):
        raise ValueError(f"Unsafe {what}: {x!r}")
    return x


def vec_to_pgvector_literal(vec):
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"


# -----------------------------
# Two-stage ANN SQL (embedding table ONLY)
# -----------------------------
def make_pgvector_sql_two_stage_binary_then_cosine(
    emb_table: str,
    slogan_id_col: str,
    emb_col: str,
    bits: int = 4096,
):
    emb_table     = _validate_ident(emb_table, "emb_table")
    slogan_id_col = _validate_ident(slogan_id_col, "slogan_id_col")
    emb_col       = _validate_ident(emb_col, "emb_col")

    bin_dist = (
        f"(binary_quantize(e.{emb_col})::bit({bits}) "
        f"<~> binary_quantize(%s::vector)::bit({bits}))"
    )

    cos_dist = f"(t.{emb_col} <=> %s::vector)"
    score_expr = f"(1 - {cos_dist})"

    sql = f"""
        SELECT
            t.{slogan_id_col}::text AS slogan_id,
            {score_expr}            AS score
        FROM (
            SELECT
                e.{slogan_id_col},
                e.{emb_col}
            FROM {emb_table} e
            ORDER BY {bin_dist} ASC
            LIMIT %s
        ) t
        ORDER BY (t.{emb_col} <=> %s::vector) ASC
        LIMIT %s
    """
    return sql


# -----------------------------
# Bulk fetch metadata + document text for slogan_ids
# Returns dict: slogan_id -> (paper_id, name, doc_text)
# -----------------------------
def fetch_metadata_for_slogan_ids(conn, slogan_ids):
    if not slogan_ids:
        return {}

    slogan_table  = _validate_ident(PG_SLOGAN_TABLE, "slogan_table")
    theorem_table = _validate_ident(PG_THEOREM_TABLE, "theorem_table")

    slogan_id_col  = _validate_ident(PG_SLOGAN_ID_COL, "slogan_id_col")
    theorem_id_col = _validate_ident(PG_THEOREM_ID_COL, "theorem_id_col")
    paper_col      = _validate_ident(PG_PAPER_COL, "paper_col")
    name_col       = _validate_ident(PG_NAME_COL, "name_col")

    doc_col        = _validate_ident(PG_DOC_COL, "doc_col")

    sql = f"""
        SELECT
            s.{slogan_id_col}::text AS slogan_id,
            t.{paper_col}::text     AS paper_id,
            t.{name_col}::text      AS name,
            s.{doc_col}::text       AS doc_text
        FROM {slogan_table} s
        JOIN {theorem_table} t
          ON s.{theorem_id_col} = t.{theorem_id_col}
        WHERE s.{slogan_id_col}::text = ANY(%s)
    """

    out = {}
    with conn.cursor() as cur:
        cur.execute(sql, (list(map(str, slogan_ids)),))
        for sid, pid, nm, doc_text in cur.fetchall():
            out[str(sid)] = (str(pid), str(nm), (doc_text or ""))
    return out


# -----------------------------
# Deduplicate by paper_id while preserving rank order
# slogan_ids should already be in desired rank order
# -----------------------------
def dedup_ranked_by_paper_from_meta(slogan_ids, meta, limit_papers):
    seen = set()
    out = []
    for sid in slogan_ids:
        if sid not in meta:
            continue
        pid, nm, _doc = meta[sid]
        if pid in seen:
            continue
        seen.add(pid)
        out.append((pid, nm))
        if len(out) >= limit_papers:
            break
    return out


# ============================================================
# QWEN3 RERANKER (yes/no probability)
# ============================================================
def load_qwen3_reranker(model_name: str = RERANKER_NAME, use_flash_attention_2: bool = False):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda":
        dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    else:
        dtype = torch.float32

    tok = AutoTokenizer.from_pretrained(model_name, padding_side="left", trust_remote_code=True)

    kwargs = dict(
        torch_dtype=dtype,
        trust_remote_code=True,
        device_map="auto" if device == "cuda" else None,
    )
    if use_flash_attention_2:
        kwargs["attn_implementation"] = "flash_attention_2"

    mdl = AutoModelForCausalLM.from_pretrained(model_name, **kwargs)
    mdl.eval()
    return tok, mdl


def _single_token_id(tokenizer, s: str) -> int:
    ids = tokenizer.encode(s, add_special_tokens=False)
    if len(ids) != 1:
        raise ValueError(f'"{s}" does not encode to a single token: {ids}')
    return ids[0]


@torch.inference_mode()
def rerank_with_qwen3_reranker(tokenizer, model, query: str, docs: list[str],
                              instruction: str = RERANK_INSTRUCTION,
                              batch_size: int = RERANK_BATCH_SIZE,
                              max_length: int = RERANK_MAX_LENGTH):
    """
    Returns list of scores aligned with docs, score = P("yes") among {"yes","no"}.
    """
    if not docs:
        return []

    prefix_tokens = tokenizer.encode(
        "<|im_start|>system\nYou are a helpful assistant.\n<|im_end|>\n"
        "<|im_start|>user\n",
        add_special_tokens=False,
    )
    suffix_tokens = tokenizer.encode(
        "<|im_end|>\n<|im_start|>assistant\n",
        add_special_tokens=False,
    )

    # Resolve yes/no single-token IDs (try common variants)
    yes_id = no_id = None
    for s in [" yes", "yes", " Yes", "Yes"]:
        try:
            yes_id = _single_token_id(tokenizer, s)
            break
        except ValueError:
            pass
    for s in [" no", "no", " No", "No"]:
        try:
            no_id = _single_token_id(tokenizer, s)
            break
        except ValueError:
            pass
    if yes_id is None or no_id is None:
        raise RuntimeError("Could not find single-token ids for 'yes'/'no'.")

    pairs = [
        f"<Instruct>: {instruction}\n<Query>: {query}\n<Document>: {doc}"
        for doc in docs
    ]

    enc = tokenizer(
        pairs,
        padding=True,
        truncation=True,
        max_length=max_length - len(prefix_tokens) - len(suffix_tokens),
        return_tensors="pt",
        add_special_tokens=False,
    )

    input_ids = enc["input_ids"]
    attention_mask = enc["attention_mask"]

    prefix = torch.tensor(prefix_tokens, dtype=torch.long).unsqueeze(0)
    suffix = torch.tensor(suffix_tokens, dtype=torch.long).unsqueeze(0)

    full_ids = []
    full_masks = []
    for i in range(input_ids.size(0)):
        ids_i = torch.cat([prefix[0], input_ids[i], suffix[0]], dim=0)
        mask_i = torch.ones_like(ids_i)
        full_ids.append(ids_i)
        full_masks.append(mask_i)

    padded = tokenizer.pad(
        {"input_ids": full_ids, "attention_mask": full_masks},
        padding=True,
        return_tensors="pt",
    )
    input_ids = padded["input_ids"]
    attention_mask = padded["attention_mask"]

    model_device = next(model.parameters()).device
    input_ids = input_ids.to(model_device)
    attention_mask = attention_mask.to(model_device)

    scores = [0.0] * len(docs)
    n = input_ids.size(0)

    for start in range(0, n, batch_size):
        end = min(start + batch_size, n)

        logits = model(
            input_ids=input_ids[start:end],
            attention_mask=attention_mask[start:end],
        ).logits

        last_pos = attention_mask[start:end].sum(dim=1) - 1
        batch_idx = torch.arange(end - start, device=model_device)

        last_logits = logits[batch_idx, last_pos, :]  # [B, vocab]

        yn_logits = torch.stack([last_logits[:, yes_id], last_logits[:, no_id]], dim=1)
        yn_prob = F.softmax(yn_logits, dim=1)[:, 0]  # p(yes)

        for j, p in enumerate(yn_prob.tolist()):
            scores[start + j] = float(p)

    return scores


# -----------------------------
# Paper-level metrics
# -----------------------------
def precision_at_k_paper(ranked_docs, rel_paper_ids, k):
    vals = []
    for q, docs in enumerate(ranked_docs):
        target = rel_paper_ids[q]
        topk = docs[:k]
        num_rel = sum(1 for (pid, _nm) in topk if pid == target)
        vals.append(num_rel / k)
    return float(np.mean(vals))


def hit_at_k_paper(ranked_docs, rel_paper_ids, k):
    vals = []
    for q, docs in enumerate(ranked_docs):
        target = rel_paper_ids[q]
        topk = docs[:k]
        vals.append(1.0 if any(pid == target for (pid, _nm) in topk) else 0.0)
    return float(np.mean(vals))


def mrr_at_k_paper(ranked_docs, rel_paper_ids, k):
    vals = []
    for q, docs in enumerate(ranked_docs):
        target = rel_paper_ids[q]
        rr = 0.0
        for i, (pid, _nm) in enumerate(docs[:k], start=1):
            if pid == target:
                rr = 1.0 / i
                break
        vals.append(rr)
    return float(np.mean(vals))


def _dcg(rels, gain="exp"):
    if len(rels) == 0:
        return 0.0
    rels = np.asarray(rels, dtype=float)
    if gain == "exp":
        gains = np.power(2.0, rels) - 1.0
    elif gain == "linear":
        gains = rels
    else:
        raise ValueError("gain must be 'exp' or 'linear'")
    discounts = 1.0 / np.log2(np.arange(2, rels.size + 2))
    return float(np.sum(gains * discounts))


def ndcg_at_k_paper(ranked_docs, rel_paper_ids, k, gain="exp"):
    vals = []
    for q, docs in enumerate(ranked_docs):
        target = rel_paper_ids[q]
        rels = [1.0 if pid == target else 0.0 for (pid, _nm) in docs[:k]]
        dcg = _dcg(rels, gain=gain)

        ideal_rels = [1.0] + [0.0] * (k - 1)
        idcg = _dcg(ideal_rels, gain=gain)

        vals.append(0.0 if idcg == 0.0 else dcg / idcg)
    return float(np.mean(vals))


# -----------------------------
# Retrieval + evaluation
# -----------------------------
def evaluate_pgvector(emb_model, queries, conn, rel_paper_ids, top_k, db_top_k):
    sql = make_pgvector_sql_two_stage_binary_then_cosine(
        emb_table=PG_TABLE,
        slogan_id_col=PG_SLOGAN_ID_COL,
        emb_col=PG_EMB_COL,
        bits=BITS,
    )

    q_texts = [q[0] if isinstance(q, (tuple, list)) else q for q in queries]
    print(f"Encoding {len(q_texts)} queries with {MODEL_NAME} ...")
    q_emb = emb_model.encode(
        q_texts,
        batch_size=8,
        show_progress_bar=True,
        normalize_embeddings=False,
        prompt="Instruct: Given a math search query, retrieve theorems mathematically equivalent to the query. \nQuery:",
    )

    # IMPORTANT: free embedder before loading reranker (memory)
    print("Freeing embedding model to make room for reranker ...")
    try:
        del emb_model
        from time import sleep
        sleep(10)
    except Exception:
        pass
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    print(f"Loading reranker: {RERANKER_NAME} ...")
    rerank_tok, rerank_model = load_qwen3_reranker(use_flash_attention_2=False)

    ranked_docs = []

    print(f"Retrieving top-{db_top_k} slogan_ids per query via pgvector (binary->cosine), then reranking with Qwen3-Reranker ...")
    with conn.cursor() as cur:
        for i in range(len(q_texts)):
            print(f"retrieving query {i}")
            qvec_str = vec_to_pgvector_literal(q_emb[i].tolist())

            cur.execute(sql, (qvec_str, qvec_str, db_top_k, qvec_str, db_top_k))
            rows = cur.fetchall()  # (slogan_id, score) cosine-reranked order
            slogan_ids = [str(sid) for (sid, _score) in rows]

            # Only rerank a smaller prefix for cost/memory
            cand_ids = slogan_ids[:min(len(slogan_ids), RERANK_TOP_N)]

            # Fetch meta + doc_text for those candidates
            meta = fetch_metadata_for_slogan_ids(conn, cand_ids)

            # Build aligned doc list for reranker
            docs = []
            aligned_ids = []
            for sid in cand_ids:
                if sid in meta:
                    _pid, _nm, doc_text = meta[sid]
                    docs.append(doc_text if doc_text is not None else "")
                    aligned_ids.append(sid)

            # Rerank by Qwen3-Reranker (score = P(yes))
            scores = rerank_with_qwen3_reranker(
                rerank_tok,
                rerank_model,
                query=q_texts[i],
                docs=docs,
                instruction=RERANK_INSTRUCTION,
                batch_size=RERANK_BATCH_SIZE,
                max_length=RERANK_MAX_LENGTH,
            )

            # Sort slogan_ids by reranker score desc
            reranked = sorted(
                zip(aligned_ids, scores),
                key=lambda x: x[1],
                reverse=True,
            )
            reranked_ids = [sid for (sid, _s) in reranked]

            # Dedup by paper_id using reranker rank order, take TOP_K papers
            paper_ranked = dedup_ranked_by_paper_from_meta(reranked_ids, meta, limit_papers=top_k)
            ranked_docs.append(paper_ranked)

    # Free reranker at end too
    try:
        del rerank_model
        del rerank_tok
    except Exception:
        pass
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    print("=" * 60)
    print(f"Results @ {top_k}  (Exact = paper_id match, papers deduped)")
    print(f"P@{1}    : {precision_at_k_paper(ranked_docs, rel_paper_ids, 1)}")
    print(f"Hit@{10}  : {hit_at_k_paper(ranked_docs, rel_paper_ids, 10)}")
    print(f"Hit@{20}  : {hit_at_k_paper(ranked_docs, rel_paper_ids, 20)}")
    print(f"MRR@{20}  : {mrr_at_k_paper(ranked_docs, rel_paper_ids, 20)}")
    print(f"nDCG@{20} : {ndcg_at_k_paper(ranked_docs, rel_paper_ids, 20, gain='exp')}")
    print("=" * 60)

    return ranked_docs


# -----------------------------
# MAIN
# -----------------------------
def main():
    vals = pd.read_csv(VALS_CSV, header=0, index_col=0, dtype={PAPER_COL: str})

    for c in [QUERY_COL, PAPER_COL]:
        if c not in vals.columns:
            raise ValueError(f"{VALS_CSV} missing column {c!r}. Found: {list(vals.columns)}")

    queries = list(zip(vals[QUERY_COL].astype(str).tolist(), vals[PAPER_COL].astype(str).tolist()))
    rel_paper_ids = vals[PAPER_COL].astype(str).tolist()

    print("Embedder:", MODEL_NAME)
    print("Reranker:", RERANKER_NAME)
    print("Embedding table:", PG_TABLE)
    print("Slogan table:", PG_SLOGAN_TABLE)
    print("Theorem table:", PG_THEOREM_TABLE)
    print("Doc text column (for reranker):", PG_DOC_COL)
    print("Relevance: paper_id match => exact (1.0)")
    print("TOP_K:", TOP_K, "DB_TOP_K:", DB_TOP_K, "RERANK_TOP_N:", RERANK_TOP_N)
    print("Dedup: per-query unique paper_id, rank preserved")
    print("BITS:", BITS)

    emb_model = SentenceTransformer(
        MODEL_NAME,
        trust_remote_code=True,
        model_kwargs={"dtype": torch.bfloat16, "low_cpu_mem_usage": True},
    )

    conn = pg_connect()
    try:
        print("Queries:", len(vals))
        evaluate_pgvector(
            emb_model=emb_model,
            queries=queries,
            conn=conn,
            rel_paper_ids=rel_paper_ids,
            top_k=TOP_K,
            db_top_k=DB_TOP_K,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
# %%
