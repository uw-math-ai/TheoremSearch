"""Generic GPU embedding worker for our experiments.

Embeds slogans matching a filter (prompt_name + slogan_model + paper scope)
using sentence-transformers + Qwen3-Embedding-8B on local GPU. Writes
embeddings to the `embedding` table under a configurable target model_name.

Supports two embedding modes:
  --text-mode raw         embed the slogan text as-is (with doc instruction)
  --text-mode decl_aug    embed `<decl_name>\n<slogan>` (the augminimal recipe)

Usage:
  python3 embed_slogans.py \\
      --source-prompt lsv2-style \\
      --source-model qwen3-235b \\
      --target-embed-model qwen3-8b-lsv2slogan \\
      --text-mode raw \\
      --shard 0 --n-shards 8
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
import psycopg2.extras


REPO_ROOT = Path("/mmfs1/gscratch/amath/simku22/TheoremSearch")
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
    host = os.environ.get("RDS_HOST", "localhost")
    port = int(os.environ.get("RDS_PORT", "5432"))
    return psycopg2.connect(host=host, port=port, dbname="v2",
        user=secret["username"], password=secret["password"], sslmode="require")


def ensure_model_registered(conn, name: str, instruction: str) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM embedding_model WHERE name = %s", (name,))
        if cur.fetchone():
            return
        cur.execute(
            "INSERT INTO embedding_model (name, model, instruction, dim, normalized) "
            "VALUES (%s, %s, %s, %s, %s)",
            (name, PROVIDER_MODEL, instruction, 4096, True),
        )
    conn.commit()
    print(f"[init] registered embedding_model.name = {name!r}", file=sys.stderr)


def fetch_work(conn, source_prompt: str, source_model: str,
               target_embed_model: str, shard: int, n_shards: int) -> list[tuple]:
    """Returns [(slogan_id, decl_name, slogan_text), ...] for v427+v428 slogans
    matching the source filter that aren't yet embedded under the target."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT s.slogan_id::text,
                   fm.decl_name,
                   s.slogan
            FROM slogan s
            JOIN statement st ON st.statement_id = s.statement_id
            JOIN paper p      ON p.paper_id     = st.paper_id
            JOIN formal_metadata fm ON fm.statement_id = s.statement_id
            LEFT JOIN embedding e
              ON e.slogan_id = s.slogan_id
             AND e.model_name = %s
            WHERE s.prompt_name = %s
              AND s.model_name  = %s
              AND NOT s.insufficient_context
              AND p.external_id IN ('Mathlib_v427','Mathlib_v428')
              AND fm.decl_name IS NOT NULL
              AND e.embedding_id IS NULL
              AND (abs(('x' || substr(md5(s.slogan_id::text), 1, 8))::bit(32)::int::bigint) %% %s) = %s
            ORDER BY s.slogan_id
        """, (target_embed_model, source_prompt, source_model, n_shards, shard))
        return list(cur.fetchall())


def build_text(text_mode: str, decl_name: str, slogan: str) -> str:
    if text_mode == "raw":
        return (slogan or "").strip()
    elif text_mode == "decl_aug":
        return f"{decl_name}\n{(slogan or '').strip()}"
    else:
        raise ValueError(f"unknown --text-mode {text_mode!r}")


def insert_embeddings_lit(conn, target_embed_model: str, batch: list[tuple],
                          vectors: list[list[float]]) -> int:
    """Insert embeddings using pgvector text-literal format. Works on any
    psycopg2 install without needing pgvector's binary adapter."""
    rows = []
    for (sid, *_), v in zip(batch, vectors):
        lit = "[" + ",".join(f"{x:.7g}" for x in v) + "]"
        rows.append((sid, target_embed_model, lit))
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO embedding (slogan_id, model_name, embedding) VALUES %s "
            "ON CONFLICT (slogan_id, model_name) DO NOTHING",
            rows,
            template="(%s::uuid, %s, %s::vector)",
            page_size=200,
        )
    conn.commit()
    return len(rows)


def encode_batch_nebius(oai, texts: list[str], batch_size: int = 32) -> list[list[float]]:
    """Nebius API path — no torch needed. Embeddings are L2-normalized to
    match what sentence-transformers' `normalize_embeddings=True` would do."""
    out = []
    for i in range(0, len(texts), batch_size):
        chunk = [DOC_INSTRUCTION + t for t in texts[i:i+batch_size]]
        resp = oai.embeddings.create(model=PROVIDER_MODEL, input=chunk,
                                      encoding_format="float")
        for item in resp.data:
            v = item.embedding
            n = math.sqrt(sum(x * x for x in v))
            out.append([x / n for x in v] if n > 0 else v)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-prompt", required=True)
    ap.add_argument("--source-model", default="qwen3-235b")
    ap.add_argument("--target-embed-model", required=True)
    ap.add_argument("--text-mode", choices=["raw", "decl_aug"], default="raw")
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--n-shards", type=int, default=1)
    ap.add_argument("--batch-size", type=int, default=64,
                    help="For nebius: inputs per API call (32-128).")
    ap.add_argument("--device", choices=["gpu", "cpu", "nebius"], default="nebius",
                    help="nebius: hosted API (no torch needed). gpu/cpu: local sentence-transformers.")
    ap.add_argument("--parallel", type=int, default=4,
                    help="Parallel workers for the Nebius path (one OpenAI client + DB conn each).")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    env = load_env()
    conn = db_connect(env)
    ensure_model_registered(conn, args.target_embed_model, DOC_INSTRUCTION)

    t0 = time.time()
    work = fetch_work(conn, args.source_prompt, args.source_model,
                      args.target_embed_model, args.shard, args.n_shards)
    print(f"[shard {args.shard}/{args.n_shards}] {len(work)} slogans to embed "
          f"into {args.target_embed_model!r} ({time.time()-t0:.1f}s fetch)",
          file=sys.stderr)
    if args.limit: work = work[: args.limit]
    if not work:
        print(f"[shard {args.shard}] nothing to do", file=sys.stderr)
        return

    if args.device == "nebius":
        from openai import OpenAI
        from concurrent.futures import ThreadPoolExecutor
        import threading
        print(f"[shard {args.shard}] using Nebius API ({args.parallel} workers, "
              f"batch_size={args.batch_size})", file=sys.stderr)
        run_nebius_parallel(work, env, args.shard, args.parallel, args.batch_size,
                            args.target_embed_model, args.text_mode)
        return

    import torch
    from sentence_transformers import SentenceTransformer
    dev = "cuda" if args.device == "gpu" and torch.cuda.is_available() else "cpu"
    print(f"[shard {args.shard}] loading {PROVIDER_MODEL} on {dev}",
          file=sys.stderr)
    kwargs = {"device": dev}
    if dev == "cuda":
        kwargs["model_kwargs"] = {"torch_dtype": torch.float16}
    model = SentenceTransformer(PROVIDER_MODEL, **kwargs)

    t_run = time.time()
    inserted = 0
    page_size = max(args.batch_size * 8, 256)
    for start in range(0, len(work), page_size):
        page = work[start : start + page_size]
        texts = [build_text(args.text_mode, dn, sl) for (_, dn, sl) in page]
        vecs = model.encode(
            texts, prompt=DOC_INSTRUCTION, batch_size=args.batch_size,
            show_progress_bar=False, convert_to_numpy=True, normalize_embeddings=True,
        )
        n_ins = insert_embeddings_lit(conn, args.target_embed_model, page, vecs.tolist())
        inserted += n_ins
        elapsed = time.time() - t_run
        rate = inserted / max(1, elapsed)
        eta = (len(work) - inserted) / max(1, rate)
        print(f"[shard {args.shard}] {inserted}/{len(work)} ({rate:.0f}/s, "
              f"eta {eta:.0f}s)", file=sys.stderr, flush=True)

    print(f"[shard {args.shard}] DONE  inserted={inserted}  "
          f"elapsed={time.time()-t_run:.0f}s", file=sys.stderr)


def run_nebius_parallel(work, env, shard, n_workers, batch_size,
                        target_embed_model, text_mode):
    """Split this shard's work across n_workers; each worker has its own
    OpenAI client and DB connection. Aggregates progress."""
    from openai import OpenAI
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading

    chunks = [work[i::n_workers] for i in range(n_workers)]
    progress_lock = threading.Lock()
    progress = {"inserted": 0, "errors": 0}
    t_run = time.time()

    def worker(worker_id, chunk):
        oai = OpenAI(base_url="https://api.studio.nebius.ai/v1/", api_key=env["NEBIUS_API_KEY"])
        wconn = db_connect(env)
        page_size = batch_size * 4
        wcount = 0
        for start in range(0, len(chunk), page_size):
            page = chunk[start:start+page_size]
            texts = [build_text(text_mode, dn, sl) for (_, dn, sl) in page]
            try:
                vecs = encode_batch_nebius(oai, texts, batch_size=batch_size)
                n = insert_embeddings_lit(wconn, target_embed_model, page, vecs)
            except Exception as e:
                with progress_lock:
                    progress["errors"] += 1
                print(f"  [w{worker_id}] err: {type(e).__name__}: {e}", file=sys.stderr)
                continue
            wcount += n
            with progress_lock:
                progress["inserted"] += n
                if progress["inserted"] % (batch_size * 4 * 4) < page_size:
                    el = time.time() - t_run
                    rate = progress["inserted"] / max(1, el)
                    eta = (len(work) - progress["inserted"]) / max(1, rate)
                    print(f"[shard {shard}] {progress['inserted']}/{len(work)} "
                          f"({rate:.0f}/s, eta {eta:.0f}s) errs={progress['errors']}",
                          file=sys.stderr, flush=True)

    with ThreadPoolExecutor(max_workers=n_workers) as ex:
        futures = [ex.submit(worker, i, c) for i, c in enumerate(chunks)]
        for f in as_completed(futures):
            f.result()

    print(f"[shard {shard}] DONE  inserted={progress['inserted']}  "
          f"errors={progress['errors']}  elapsed={time.time()-t_run:.0f}s",
          file=sys.stderr)


if __name__ == "__main__":
    main()
