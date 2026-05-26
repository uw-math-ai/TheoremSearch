"""Re-embed Mathlib v427+v428 slogans with minimal augmented text.

For each (statement_id, slogan, decl_name) in Mathlib v427+v428 where the
slogan model is qwen3-235b and the slogan is not insufficient_context,
construct `<decl_name>\\n<slogan>` and embed via local GPU
(sentence-transformers + Qwen3-Embedding-8B).

Writes embeddings into the `embedding` table with model_name
'qwen3-8b-augminimal' (registered in `embedding_model` first time). Existing
'qwen3-8b' rows untouched.

Designed for SLURM array: --shard N --n-shards M splits the work; each task
processes its slice independently. Resumes safely: skips slogan_ids that
already have an embedding row under model_name 'qwen3-8b-augminimal'.

Usage:
  python3 reembed_augminimal.py --shard $SLURM_ARRAY_TASK_ID --n-shards 8 \\
                                --batch-size 64 --device gpu
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
import numpy as np
import psycopg2
from pgvector.psycopg2 import register_vector


REPO_ROOT = Path("/mmfs1/gscratch/amath/simku22/TheoremSearch")
NEW_MODEL_NAME = "qwen3-8b-augminimal"
PROVIDER_MODEL = "Qwen/Qwen3-Embedding-8B"
DOC_INSTRUCTION = "Represent the given math statement for retrieving related statements by natural language query.\n"


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
    # OS env overrides .env file (the .env points at a stale RDS hostname; SLURM
    # tasks need to talk through their own per-shard tunnel port on localhost).
    host = os.environ.get("RDS_HOST", env.get("RDS_HOST", "localhost"))
    port = int(os.environ.get("RDS_PORT", env.get("RDS_PORT", "5432")))
    conn = psycopg2.connect(host=host, port=port, dbname="v2",
        user=secret["username"], password=secret["password"], sslmode="require")
    register_vector(conn)
    return conn


def ensure_model_registered(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM embedding_model WHERE name = %s", (NEW_MODEL_NAME,))
        if cur.fetchone():
            return
        cur.execute(
            "INSERT INTO embedding_model (name, model, instruction, dim, normalized) "
            "VALUES (%s, %s, %s, %s, %s)",
            (NEW_MODEL_NAME, PROVIDER_MODEL, DOC_INSTRUCTION, 4096, True),
        )
    conn.commit()
    print(f"[init] registered embedding_model.name = {NEW_MODEL_NAME!r}", file=sys.stderr)


def fetch_work(conn, shard: int, n_shards: int) -> list[tuple]:
    """Return list of (slogan_id, statement_id, decl_name, slogan_text) for
    Mathlib v427+v428 slogans not yet embedded under NEW_MODEL_NAME, sharded
    by hashing slogan_id::text → mod n_shards."""
    with conn.cursor(name="reembed_cur") as cur:
        cur.itersize = 4096
        cur.execute("""
            SELECT s.slogan_id::text,
                   s.statement_id::text,
                   fm.decl_name,
                   s.slogan
            FROM slogan s
            JOIN statement st ON st.statement_id = s.statement_id
            JOIN paper p      ON p.paper_id     = st.paper_id
            JOIN formal_metadata fm ON fm.statement_id = s.statement_id
            LEFT JOIN embedding e
              ON e.slogan_id = s.slogan_id
             AND e.model_name = %s
            WHERE s.model_name = 'qwen3-235b'
              AND NOT s.insufficient_context
              AND p.external_id IN ('Mathlib_v427','Mathlib_v428')
              AND fm.decl_name IS NOT NULL
              AND e.embedding_id IS NULL
              AND (('x' || substr(md5(s.slogan_id::text), 1, 8))::bit(32)::int %% %s) = %s
            ORDER BY s.slogan_id
        """, (NEW_MODEL_NAME, n_shards, shard))
        return list(cur)


def build_aug_text(decl_name: str, slogan: str) -> str:
    """Minimal augmentation. The probe showed verbose templates dilute the
    embedding; just prepend the decl_name on its own line."""
    return f"{decl_name}\n{(slogan or '').strip()}"


def encode_batch_local(model, texts: list[str], batch_size: int) -> list[list[float]]:
    """sentence-transformers local-GPU path (requires torch, sentence-transformers)."""
    arr = model.encode(
        texts, prompt=DOC_INSTRUCTION, batch_size=batch_size,
        show_progress_bar=False, convert_to_numpy=True, normalize_embeddings=True,
    )
    return arr.tolist()


def encode_batch_nebius(oai, texts: list[str], batch_size: int = 32) -> list[list[float]]:
    """Nebius API path. Sends up to `batch_size` inputs per request. Each text
    is prefixed with DOC_INSTRUCTION (per the qwen3-8b embedding_model.instruction
    registered for our corpus)."""
    out = []
    for i in range(0, len(texts), batch_size):
        chunk = [DOC_INSTRUCTION + t for t in texts[i:i+batch_size]]
        resp = oai.embeddings.create(
            model=PROVIDER_MODEL, input=chunk, encoding_format="float",
        )
        for item in resp.data:
            v = item.embedding
            n = math.sqrt(sum(x * x for x in v))
            out.append([x / n for x in v] if n > 0 else v)
    return out


def insert_embeddings(conn, batch: list[tuple], vectors: list[list[float]]) -> int:
    """Bulk INSERT via pgvector's binary protocol (register_vector). Uses
    psycopg2.extras.execute_values for one INSERT per batch (vs N round-trips
    in executemany). ON CONFLICT lets us safely resume."""
    from psycopg2.extras import execute_values
    rows = [(sid, NEW_MODEL_NAME, np.asarray(v, dtype=np.float32))
            for (sid, *_), v in zip(batch, vectors)]
    with conn.cursor() as cur:
        execute_values(
            cur,
            "INSERT INTO embedding (slogan_id, model_name, embedding) VALUES %s "
            "ON CONFLICT (slogan_id, model_name) DO NOTHING",
            rows,
            template="(%s, %s, %s)",
            page_size=len(rows),
        )
    conn.commit()
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--n-shards", type=int, default=1)
    ap.add_argument("--batch-size", type=int, default=64,
                    help="Batch size: for GPU, sentence-transformers inner batch. "
                         "For Nebius, inputs per API call.")
    ap.add_argument("--device", choices=["gpu", "cpu", "nebius"], default="nebius",
                    help="nebius: API path (no torch needed). gpu: local sentence-transformers.")
    ap.add_argument("--parallel", type=int, default=4,
                    help="Parallel workers for the Nebius path (one OpenAI client each). "
                         "Each worker processes a disjoint slice of this shard.")
    ap.add_argument("--limit", type=int, default=0,
                    help="Cap rows processed (for smoke tests).")
    args = ap.parse_args()

    env = load_env()
    conn = db_connect(env)
    ensure_model_registered(conn)

    t0 = time.time()
    work = fetch_work(conn, args.shard, args.n_shards)
    print(f"[shard {args.shard}/{args.n_shards}] {len(work)} rows to embed "
          f"(fetched in {time.time()-t0:.1f}s)", file=sys.stderr)
    if args.limit:
        work = work[: args.limit]

    if not work:
        print(f"[shard {args.shard}] nothing to do (resume case)", file=sys.stderr)
        return

    if args.device in ("gpu", "cpu"):
        import torch
        from sentence_transformers import SentenceTransformer
        dev = "cuda" if args.device == "gpu" and torch.cuda.is_available() else "cpu"
        print(f"[shard {args.shard}] loading {PROVIDER_MODEL} on {dev}", file=sys.stderr)
        kwargs = {"device": dev}
        if dev == "cuda":
            kwargs["model_kwargs"] = {"torch_dtype": torch.float16}
        model = SentenceTransformer(PROVIDER_MODEL, **kwargs)
        encode = lambda texts: encode_batch_local(model, texts, args.batch_size)
        run_serial(conn, work, encode, args.shard, args.batch_size)
    else:
        from openai import OpenAI
        from concurrent.futures import ThreadPoolExecutor
        print(f"[shard {args.shard}] using Nebius API ({args.parallel} workers, "
              f"batch_size={args.batch_size})", file=sys.stderr)
        run_nebius_parallel(conn, work, env, args.shard, args.parallel, args.batch_size)


def run_serial(conn, work, encode, shard, batch_size):
    t_run = time.time()
    inserted = 0
    page_size = max(batch_size * 8, 256)
    for start in range(0, len(work), page_size):
        page = work[start : start + page_size]
        texts = [build_aug_text(dn, sl) for (_, _, dn, sl) in page]
        vecs = encode(texts)
        n_ins = insert_embeddings(conn, page, vecs)
        inserted += n_ins
        elapsed = time.time() - t_run
        rate = inserted / max(1, elapsed)
        eta = (len(work) - inserted) / max(1, rate)
        print(f"[shard {shard}] {inserted}/{len(work)} ({rate:.0f}/s, eta {eta:.0f}s)",
              file=sys.stderr, flush=True)
    print(f"[shard {shard}] DONE  inserted={inserted}  elapsed={time.time()-t_run:.0f}s",
          file=sys.stderr)


def run_nebius_parallel(conn, work, env, shard, n_workers, batch_size):
    """Split this shard's work across n_workers; each worker has its own
    OpenAI client and DB connection (psycopg2 not thread-safe). Reports
    aggregate progress every N inserted rows."""
    from openai import OpenAI
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading

    # Split work into n_workers chunks
    chunks = [work[i::n_workers] for i in range(n_workers)]
    progress_lock = threading.Lock()
    progress = {"inserted": 0, "errors": 0}
    t_run = time.time()

    def worker(worker_id, chunk):
        oai = OpenAI(base_url="https://api.studio.nebius.ai/v1/", api_key=env["NEBIUS_API_KEY"])
        wconn = db_connect(env)
        page_size = batch_size * 4
        for start in range(0, len(chunk), page_size):
            page = chunk[start : start + page_size]
            texts = [build_aug_text(dn, sl) for (_, _, dn, sl) in page]
            try:
                vecs = encode_batch_nebius(oai, texts, batch_size=batch_size)
                n_ins = insert_embeddings(wconn, page, vecs)
            except Exception as e:
                with progress_lock:
                    progress["errors"] += 1
                print(f"  [shard {shard} w{worker_id}] error: {e}", file=sys.stderr)
                continue
            with progress_lock:
                progress["inserted"] += n_ins
                ins = progress["inserted"]
            if ins % 1000 < page_size:   # log roughly every 1000
                elapsed = time.time() - t_run
                rate = ins / max(1, elapsed)
                eta = (len(work) - ins) / max(1, rate)
                print(f"  [shard {shard}] {ins}/{len(work)} ({rate:.0f}/s, eta {eta:.0f}s)",
                      file=sys.stderr, flush=True)
        wconn.close()

    with ThreadPoolExecutor(max_workers=n_workers) as ex:
        futures = [ex.submit(worker, i, chunks[i]) for i in range(n_workers)]
        for f in as_completed(futures):
            f.result()

    print(f"[shard {shard}] DONE  inserted={progress['inserted']}  errors={progress['errors']}  "
          f"elapsed={time.time()-t_run:.0f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
