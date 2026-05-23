"""Compare stored slogan embeddings to freshly Nebius-generated ones.

Picks N random slogans that already have a stored embedding for the given
model, re-embeds the same text via Nebius (using the registered instruction
prefix), and reports per-slogan + aggregate cosine similarity.

If the storage pipeline produced its embeddings via Nebius, expect ≈ 1.0
across the board. Lower scores expose drift between sentence-transformers
and Nebius — pooling, normalization, precision, or instruction differences.

Usage::

    python -m experiments.nebius_vs_sentence_transformers
    python -m experiments.nebius_vs_sentence_transformers -n 50
"""
from __future__ import annotations

import argparse
import os
from typing import List

import numpy as np
from openai import OpenAI

from rds.utils.connect import get_rds_connection


_BASE_URL = "https://api.studio.nebius.ai/v1/"


def _fetch_model_info(conn, name: str):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT model, instruction, normalized FROM embedding_model WHERE name = %s",
            (name,),
        )
        row = cur.fetchone()
    if row is None:
        raise SystemExit(f"unknown embedding_model alias: {name!r}")
    return row  # (provider_model, instruction, normalized)


def _fetch_random_embedded(conn, model_name: str, n: int, seed: int):
    # TABLESAMPLE would be cheaper but doesn't compose with the model filter;
    # for n=10 the ORDER BY random() is fine.
    with conn.cursor() as cur:
        cur.execute("SELECT setseed(%s)", (max(-1.0, min(1.0, seed / 1e6)),))
        cur.execute(
            """
            SELECT sl.slogan_id, sl.slogan, e.embedding
            FROM embedding e
            JOIN slogan sl ON sl.slogan_id = e.slogan_id
            WHERE e.model_name = %s
            ORDER BY random()
            LIMIT %s
            """,
            (model_name, n),
        )
        return cur.fetchall()


def _parse_vec(emb) -> np.ndarray:
    if isinstance(emb, str):
        return np.fromstring(emb[1:-1], sep=",", dtype=np.float32)
    return np.asarray(emb, dtype=np.float32)


def _l2(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v if n == 0 else v / n


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-n", type=int, default=10,
                        help="Number of slogans to sample. Default: 10.")
    parser.add_argument("--embedding-model", default="qwen3-8b",
                        help="embedding_model.name in RDS. Default: qwen3-8b.")
    parser.add_argument("--seed", type=int, default=0,
                        help="Sampling seed for reproducibility. Default: 0.")
    args = parser.parse_args()

    conn = get_rds_connection("v2")
    provider_model, instruction, normalized = _fetch_model_info(conn, args.embedding_model)
    print(f"alias           : {args.embedding_model}")
    print(f"provider model  : {provider_model}")
    print(f"normalized      : {normalized}")
    print(f"instruction     : {instruction!r}")
    print()

    rows = _fetch_random_embedded(conn, args.embedding_model, args.n, args.seed)
    if not rows:
        raise SystemExit(f"no embeddings found for model {args.embedding_model!r}")
    print(f"sampled {len(rows)} slogans with stored embeddings\n")

    client = OpenAI(api_key=os.environ["NEBIUS_API_KEY"], base_url=_BASE_URL)

    sims: List[float] = []
    for i, (sl_id, slogan, stored_emb) in enumerate(rows, 1):
        stored = _l2(_parse_vec(stored_emb))
        text = (instruction or "") + slogan
        resp = client.embeddings.create(
            model=provider_model, input=text, encoding_format="float",
        )
        fresh = _l2(np.asarray(resp.data[0].embedding, dtype=np.float32))
        sim = float(np.dot(stored, fresh))
        sims.append(sim)
        preview = slogan.replace("\n", " ")
        if len(preview) > 70:
            preview = preview[:69] + "…"
        print(f"  [{i:2d}] sim={sim:+.6f}   {preview}")

    a = np.array(sims)
    print()
    print(f"min    = {a.min():+.6f}")
    print(f"p25    = {np.percentile(a, 25):+.6f}")
    print(f"median = {np.median(a):+.6f}")
    print(f"mean   = {a.mean():+.6f}")
    print(f"p75    = {np.percentile(a, 75):+.6f}")
    print(f"max    = {a.max():+.6f}")
    print()
    if a.mean() >= 0.999:
        verdict = "≈1.0 — pipelines are equivalent."
    elif a.mean() >= 0.95:
        verdict = "small drift (precision / quantization); usually safe to mix."
    elif a.mean() >= 0.7:
        verdict = "noticeable drift — likely a pooling or instruction mismatch."
    else:
        verdict = "incompatible — different pooling or normalization. Re-embed."
    print(f"verdict: {verdict}")


if __name__ == "__main__":
    main()
