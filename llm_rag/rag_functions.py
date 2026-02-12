# theorem_search_tool.py
import os
import json
import ssl
import asyncio
from typing import Any, Optional, List, Dict

import boto3
import asyncpg
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

# Load env once at import time (safe in VSCode/Claude tool usage)
load_dotenv()

# ---------- Config ----------
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
RDS_SECRET_ARN = os.environ["RDS_SECRET_ARN"]
RDS_HOST = os.environ["RDS_HOST"]
RDS_PORT = int(os.environ.get("RDS_PORT", "5432"))
RDS_DBNAME = os.environ.get("RDS_DBNAME", "postgres")

# Embedding model
ST_MODEL_NAME = os.environ.get("ST_MODEL_NAME", "Qwen/Qwen3-Embedding-0.6B")

# Tables/columns
EMB_TABLE = os.environ.get("EMB_TABLE", "theorem_search_qwen")   # has embedding, theorem_id, slogan_id
EMB_COL = os.environ.get("EMB_COL", "embedding")
THEOREM_TABLE = os.environ.get("THEOREM_TABLE", "theorem")       # has theorem_id, body
SLOGAN_TABLE = os.environ.get("SLOGAN_TABLE", "theorem_slogan")  # has slogan_id, slogan text column

SLOGAN_TEXT_COL_CANDIDATES = ["slogan", "body", "text", "description"]

# ---------- Caches ----------
_secret_cache: Optional[dict] = None
_pool: Optional[asyncpg.Pool] = None
_st_model: Optional[SentenceTransformer] = None


# =========================
# Main method #1: get_pool
# =========================
async def get_pool() -> asyncpg.Pool:
    """
    Establishes and caches an asyncpg pool to your RDS instance (sslmode=require behavior).
    Safe to call repeatedly; only creates the pool once.
    """
    global _pool
    if _pool is not None:
        return _pool

    # (Re)load env in case caller sets env vars at runtime
    load_dotenv()

    secret = _load_rds_secret()
    user = secret.get("username", "postgres")
    password = secret["password"]
    dbname = secret.get("dbname") or RDS_DBNAME
    port = int(secret.get("port", RDS_PORT))

    # Match sslmode=require (but with hostname verification disabled like your original)
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    host = "".join(RDS_HOST.split())  # remove accidental whitespace

    print("Connecting to:", {"host": host, "port": port, "database": dbname, "user": user})

    _pool = await asyncpg.create_pool(
        host=host,
        port=port,
        user=user,
        password=password,
        database=dbname,
        ssl=ssl_ctx,
        min_size=1,
        max_size=5,
        command_timeout=3.0,
    )
    return _pool


async def close_pool() -> None:
    """Optional cleanup helper."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


# ===========================
# Main method #2: semantic_search
# ===========================
async def semantic_search(query: str, k: int = 10, include_body: bool = False) -> List[Dict[str, Any]]:
    """
    semantic_search(query) -> list of results

    Each result:
      {
        "theorem_id": int,
        "theorem_name": str | None,
        "paper_id": str | None,
        "slogan_id": int,
        "cosine_sim": float | None,
        "slogan": str | dict | None,
        "body": str | None,
      }
    """
    print(f"[semantic_search] query={query!r} k={k} include_body={include_body}")

    k = max(1, min(int(k), 50))
    qvec = _embed_query(query)
    print(f"[semantic_search] embedded dim={len(qvec)}")

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("SET statement_timeout = 2000;")  # ms

        slogan_col = await _detect_slogan_text_col(conn)

        if slogan_col:
            select_slogan = f"s.{slogan_col} AS slogan"
        else:
            select_slogan = "to_jsonb(s) AS slogan_row"

        select_body = "t.body AS body" if include_body else "NULL::text AS body"

        sql = f"""
            SELECT
                e.theorem_id,
                e.slogan_id,
                1 - (e.{EMB_COL} <=> ($1::vector)) AS cosine_sim,
                {select_slogan},
                {select_body},
                t.name AS theorem_name,
                t.paper_id
            FROM {EMB_TABLE} e
            LEFT JOIN {SLOGAN_TABLE} s ON s.slogan_id = e.slogan_id
            LEFT JOIN {THEOREM_TABLE} t ON t.theorem_id = e.theorem_id
            ORDER BY e.{EMB_COL} <=> ($1::vector)
            LIMIT $2;
        """

        qvec_str = _to_pgvector_literal(qvec)
        rows = await conn.fetch(sql, qvec_str, k)
        print(f"[semantic_search] fetched rows={len(rows)}")

    results: List[Dict[str, Any]] = []
    for r in rows:
        body = r.get("body") if include_body else None
        if isinstance(body, str) and len(body) > 1200:
            body = body[:1200] + "…"

        # slogan could be either a string (slogan_col found) or a jsonb row
        slogan = r.get("slogan", None)
        if slogan is None and "slogan_row" in r:
            slogan = r["slogan_row"]

        if isinstance(slogan, str) and len(slogan) > 400:
            slogan = slogan[:400] + "…"

        results.append(
            {
                "theorem_id": int(r["theorem_id"]) if r["theorem_id"] is not None else None,
                "theorem_name": r.get("theorem_name"),
                "paper_id": r.get("paper_id"),
                "slogan_id": int(r["slogan_id"]) if r["slogan_id"] is not None else None,
                "cosine_sim": float(r["cosine_sim"]) if r["cosine_sim"] is not None else None,
                "slogan": slogan,
                "body": body,
            }
        )

    return results


# ---------- Internal helpers ----------
def _load_rds_secret() -> dict:
    global _secret_cache
    if _secret_cache is None:
        sm = boto3.client("secretsmanager", region_name=AWS_REGION)
        resp = sm.get_secret_value(SecretId=RDS_SECRET_ARN)
        _secret_cache = json.loads(resp["SecretString"])
    return _secret_cache


def _get_st_model() -> SentenceTransformer:
    global _st_model
    if _st_model is None:
        # Expensive: load once
        _st_model = SentenceTransformer(ST_MODEL_NAME)
    return _st_model


def _embed_query(text: str) -> List[float]:
    model = _get_st_model()
    vec = model.encode(text, normalize_embeddings=True)
    return vec.tolist()


def _to_pgvector_literal(vec: List[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"


async def _detect_slogan_text_col(conn: asyncpg.Connection) -> str:
    rows = await conn.fetch(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = $1
        """,
        SLOGAN_TABLE,
    )
    cols = {r["column_name"] for r in rows}
    for c in SLOGAN_TEXT_COL_CANDIDATES:
        if c in cols:
            return c
    return ""


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Search theorem database semantically",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python rag_functions.py "Gerbe for connected reductive group is banded"
  python rag_functions.py "fundamental theorem of calculus" --k 5
  python rag_functions.py "Stokes theorem" --k 10 --include-body
        """
    )
    parser.add_argument("query", help="The search query")
    parser.add_argument("-k", "--num-results", type=int, default=10,
                       help="Number of results to return (default: 10, max: 50)")
    parser.add_argument("-b", "--include-body", action="store_true",
                       help="Include theorem body in results")
    parser.add_argument("--json", action="store_true",
                       help="Output results as JSON")

    args = parser.parse_args()

    async def run_search():
        results = await semantic_search(
            query=args.query,
            k=args.num_results,
            include_body=args.include_body
        )

        if args.json:
            import json
            print(json.dumps(results, indent=2))
        else:
            print(f"\nSearch: {args.query}")
            print("=" * 80)
            for i, result in enumerate(results, 1):
                print(f"\n[{i}] Theorem ID: {result['theorem_id']} | "
                      f"Similarity: {result['cosine_sim']:.4f}")
                if result['theorem_name']:
                    print(f"Name: {result['theorem_name']}")
                if result['paper_id']:
                    print(f"Paper ID: {result['paper_id']}")
                print(f"Slogan: {result['slogan']}")
                if result['body']:
                    print(f"Body: {result['body']}")
                print("-" * 80)

        await close_pool()

    asyncio.run(run_search())