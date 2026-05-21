import io
import sys
import time
from argparse import ArgumentParser
from datetime import datetime, timezone
from typing import List, Optional

import numpy as np
from pgvector.psycopg2 import register_vector
from tqdm import tqdm

from rds.utils.connect import get_rds_connection
from rds.utils.query import build_query
from ..printing import print_script_header
from ..generate_slogans.prompt_utils import condition_joins
from .embed_utils import load_model_config, make_encoder, register_model


_STAGE_TABLE = "_emb_stage"


def _init_stage(conn) -> None:
    """Create a session-local staging table for COPY-based bulk upsert.
    Lives until the connection closes; we TRUNCATE between batches."""
    with conn.cursor() as cur:
        cur.execute(f"""
            CREATE TEMP TABLE IF NOT EXISTS {_STAGE_TABLE} (
                slogan_id  UUID,
                model_name TEXT,
                embedding  vector,
                created_at TIMESTAMPTZ
            )
        """)


def _bulk_upsert(conn, slogan_ids, model_name, vectors, created_at) -> None:
    """COPY rows into the staging table, then merge into `embedding`."""
    buf = io.StringIO()
    iso = created_at.isoformat()
    for sid, vec in zip(slogan_ids, vectors):
        # pgvector text format: "[v1,v2,...]". .9g preserves fp32 roundtrip.
        vec_str = "[" + ",".join(f"{float(x):.9g}" for x in np.asarray(vec).ravel()) + "]"
        buf.write(f"{sid}\t{model_name}\t{vec_str}\t{iso}\n")
    buf.seek(0)
    with conn.cursor() as cur:
        cur.copy_expert(
            f"COPY {_STAGE_TABLE} (slogan_id, model_name, embedding, created_at) FROM STDIN",
            buf,
        )
        cur.execute(f"""
            INSERT INTO embedding (slogan_id, model_name, embedding, created_at)
            SELECT slogan_id, model_name, embedding, created_at FROM {_STAGE_TABLE}
            ON CONFLICT (slogan_id, model_name) DO UPDATE
                SET embedding = EXCLUDED.embedding
        """)
        cur.execute(f"TRUNCATE {_STAGE_TABLE}")


def _err(msg: str):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(2)


def generate_embeddings(
    model_name: str,
    condition: Optional[str],
    condition_params: List[str],
    overwrite: bool,
    batch_size: int,
    encode_batch_size: int,
    shard: int,
    n_shards: int,
    device: str,
):
    model_config = load_model_config(model_name)

    print_script_header(
        action="Generating embeddings",
        params={
            "model":              model_name,
            "device":             device,
            "condition?":         condition,
            "condition params?":  condition_params,
            "overwrite":          overwrite,
            "DB page size":       batch_size,
            "encode batch size":  encode_batch_size,
            "shard?":             f"{shard}/{n_shards}" if n_shards > 1 else None,
        },
    )

    # Always join slogan → statement so -c conditions on statement/paper/apm work via condition_joins.
    base_query = (
        "SELECT slogan.slogan_id, slogan.slogan "
        "FROM slogan "
        "JOIN statement ON statement.statement_id = slogan.statement_id"
        + condition_joins(condition)
    )

    conn = get_rds_connection("v2")

    where_clauses = [
        {
            "if": True,
            "condition": "NOT slogan.insufficient_context",
            "params": [],
        },
        {
            "if": not overwrite,
            "condition": """
                NOT EXISTS (
                    SELECT 1 FROM embedding
                    WHERE embedding.slogan_id = slogan.slogan_id
                      AND embedding.model_name = %s
                )
            """,
            "params": [model_name],
        },
        {
            "if": bool(condition),
            "condition": condition or "",
            "params": condition_params,
        },
        {
            "if": n_shards > 1,
            "condition": "ABS(hashtext(slogan.slogan_id::text)) %% %s = %s",
            "params": [n_shards, shard],
        },
    ]
    query, params = build_query(base_query=base_query, where_clauses=where_clauses)

    register_model(conn, model_name, model_config)
    register_vector(conn)
    _init_stage(conn)

    print(f"Loading {model_config['model']} via {device} ...")
    encoder = make_encoder(model_config, device=device)
    instruction = model_config.get("instruction")
    normalize = bool(model_config.get("normalized", True))

    # One-shot candidate fetch. Replaces the previous (a) get_query_count
    # full-scan + (b) paginate_query's per-page filter re-execution — both
    # of which re-ran the NOT EXISTS / -c condition chain repeatedly. Now
    # the planner executes the WHERE chain exactly once, streams the result
    # over the wire, and we iterate in Python.
    print("Selecting slogans to embed ...", flush=True)
    t0 = time.perf_counter()
    with conn.cursor() as cur:
        cur.execute(f"{query} ORDER BY slogan.slogan_id", params)
        rows_all = cur.fetchall()
    print(f"  {len(rows_all):,} slogans selected in {time.perf_counter() - t0:.1f}s",
          flush=True)
    if not rows_all:
        print("No slogans to embed.")
        return

    status_counts = {"success": 0, "failed": 0}
    cum_enc = cum_ups = cum_com = 0.0

    with tqdm(total=len(rows_all), dynamic_ncols=True) as pbar:
        for start in range(0, len(rows_all), batch_size):
            page = rows_all[start:start + batch_size]
            slogan_ids = [str(r[0]) for r in page]
            texts      = [r[1]      for r in page]

            try:
                t0 = time.perf_counter()
                vectors = encoder.encode(
                    texts,
                    instruction=instruction,
                    batch_size=encode_batch_size,
                    normalize=normalize,
                )
                cum_enc += time.perf_counter() - t0
            except Exception as e:
                status_counts["failed"] += len(page)
                pbar.update(len(page))
                print(f"\n[error] encode failed for page of {len(page)}: {e}")
                continue

            now = datetime.now(timezone.utc)
            t0 = time.perf_counter()
            _bulk_upsert(conn, slogan_ids, model_name, vectors, now)
            cum_ups += time.perf_counter() - t0
            t0 = time.perf_counter()
            conn.commit()
            cum_com += time.perf_counter() - t0
            status_counts["success"] += len(slogan_ids)
            pbar.update(len(page))
            done = sum(status_counts.values())
            pbar.set_postfix({
                "success": f"{100.0 * status_counts['success'] / done:.1f}%",
                "enc": f"{cum_enc:.1f}s",
                "ups": f"{cum_ups:.1f}s",
                "com": f"{cum_com:.1f}s",
            })


if __name__ == "__main__":
    parser = ArgumentParser(
        description="Generate sentence-transformer embeddings for statement slogans."
    )

    parser.add_argument(
        "-m", "--model",
        type=str,
        required=True,
        dest="model_name",
        help="Short embedding-model name from models.json (e.g. 'qwen3-8b').",
    )
    parser.add_argument(
        "-c", "--condition",
        type=str,
        nargs="+",
        metavar=("SQL", "PARAM"),
        help=(
            "SQL WHERE condition to filter slogans, followed by bind parameters. "
            "The 'slogan', 'statement', and (if needed) 'paper'/'apm' tables are in scope. "
            "Example: -c \"apm.in_validation\""
        ),
    )
    parser.add_argument(
        "-o", "--overwrite",
        action="store_true",
        help="Re-generate embeddings for slogans that already have one for this model.",
    )
    parser.add_argument(
        "-b", "--batch-size",
        type=int,
        default=256,
        dest="batch_size",
        help="Slogans fetched from DB per page. Default: 256.",
    )
    parser.add_argument(
        "--encode-batch-size",
        type=int,
        default=8,
        dest="encode_batch_size",
        help=(
            "Encode batch size. For 'cpu'/'gpu', the sentence-transformers inner "
            "batch. For 'nebius', the number of inputs per API call. Default: 8."
        ),
    )
    parser.add_argument(
        "--device",
        type=str,
        required=True,
        choices=["nebius", "cpu", "gpu"],
        help=(
            "Where to run encoding. 'cpu'/'gpu' use sentence-transformers locally; "
            "'nebius' calls the Nebius embeddings endpoint and skips importing "
            "sentence-transformers."
        ),
    )
    parser.add_argument(
        "--shard",
        type=int,
        default=0,
        help="0-based shard index for array jobs. Default: 0.",
    )
    parser.add_argument(
        "--n-shards",
        type=int,
        default=1,
        dest="n_shards",
        help="Total number of shards. Default: 1 (no sharding).",
    )

    args = parser.parse_args()

    if args.condition and len(args.condition) >= 2:
        condition, *condition_params = args.condition
    else:
        condition = args.condition[0] if args.condition else None
        condition_params = []

    generate_embeddings(
        model_name=args.model_name,
        condition=condition,
        condition_params=condition_params,
        overwrite=args.overwrite,
        batch_size=args.batch_size,
        encode_batch_size=args.encode_batch_size,
        shard=args.shard,
        n_shards=args.n_shards,
        device=args.device,
    )
