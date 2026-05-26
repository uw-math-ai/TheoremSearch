"""Pull all formal slogan embeddings from v2 into a local index.

Output (cache/):
  formal_emb.f16.npy   float16 [N, 4096]   row i = embedding of formal_ids[i]
  formal_ids.json      list[str]           v2 statement_id (UUID str), row-aligned

The whole formal corpus (one slogan per decl, prompt_name='formal', model
qwen3-235b) is embedded 1:1, so this is the full retrievable universe for the
formal premise-retrieval objective. Read-only; safe to re-run (overwrites).

Run:
    python scripts/build_formal_index.py
"""
import json
import os
import time
from pathlib import Path

import dotenv
import numpy as np

dotenv.load_dotenv(os.environ.get("LPR_ENV_FILE", str(Path(__file__).resolve().parent.parent / ".env")))
import boto3
import psycopg2

CACHE = Path(__file__).resolve().parent.parent / "cache"
DIM = 4096


def connect():
    secret = json.loads(
        boto3.client("secretsmanager", region_name="us-west-2")
        .get_secret_value(SecretId=os.getenv("RDS_SECRET_ARN"))["SecretString"]
    )
    return psycopg2.connect(
        host=os.getenv("RDS_HOST"), port=5432, dbname="v2",
        user=secret["username"], password=secret["password"], sslmode="require",
        connect_timeout=20,
        # No statement timeout: this is a long read-only stream.
        options="-c default_transaction_read_only=on -c statement_timeout=0",
    )


def main():
    conn = connect()
    with conn.cursor() as c:
        c.execute(
            "SELECT COUNT(*) FROM embedding e JOIN slogan sl ON sl.slogan_id=e.slogan_id "
            "WHERE sl.prompt_name='formal'"
        )
        n = c.fetchone()[0]
    print(f"[{time.strftime('%H:%M:%S')}] formal embeddings to pull: {n:,}")

    emb = np.empty((n, DIM), dtype=np.float16)
    ids: list[str] = []

    # Server-side cursor streams rows without buffering all client-side.
    cur = conn.cursor(name="formal_emb_stream")
    cur.itersize = 2000
    cur.execute(
        "SELECT sl.statement_id::text, e.embedding::text "
        "FROM embedding e JOIN slogan sl ON sl.slogan_id=e.slogan_id "
        "WHERE sl.prompt_name='formal' ORDER BY sl.statement_id"
    )

    t0 = time.time()
    i = 0
    for sid, vec_txt in cur:
        # pgvector ::text is '[f,f,...]'
        v = np.fromstring(vec_txt[1:-1], sep=",", dtype=np.float32)
        if v.shape[0] != DIM:
            raise ValueError(f"row {i} ({sid}) dim={v.shape[0]} != {DIM}")
        emb[i] = v.astype(np.float16)
        ids.append(sid)
        i += 1
        if i % 20000 == 0:
            dt = time.time() - t0
            print(f"[{time.strftime('%H:%M:%S')}] {i:,}/{n:,}  "
                  f"({i/dt:.0f} rows/s, eta {(n-i)/(i/dt)/60:.1f} min)")
    cur.close()
    conn.close()

    assert i == n, f"pulled {i} != expected {n}"
    CACHE.mkdir(exist_ok=True)
    np.save(CACHE / "formal_emb.f16.npy", emb)
    (CACHE / "formal_ids.json").write_text(json.dumps(ids))
    print(f"[{time.strftime('%H:%M:%S')}] saved {emb.shape} float16 -> "
          f"{CACHE/'formal_emb.f16.npy'} ({emb.nbytes/1e9:.2f} GB), "
          f"{len(ids):,} ids")


if __name__ == "__main__":
    main()
