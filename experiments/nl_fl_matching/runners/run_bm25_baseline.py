"""BM25 baseline for the bidirectional gold-pair sweep.

Mirrors the embedding sweep's gold-pool retrieval but uses rank_bm25.BM25Okapi
over tokenized slogans:

  --direction f2i: 1,562 gold formal slogans queried against the 2,544
                    blueprint informal slogans (Lean Community papers).
                    NOTE: this is a much smaller haystack than what the
                    embedding searched (11.7M). The point is to show
                    "does BM25 with a paper-prior beat embedding with
                    full corpus", which is the strongest baseline framing.
  --direction i2f: 1,308 gold informal slogans queried against the 36,708
                    project_formals slogans. Same pool as the embedding
                    sweep — direct comparison.

Tokenization: lowercase + split on whitespace/punctuation (cheap).
Writes top-10 to nl_fl_match_pilot with embedding_model='bm25' so
analysis/eval.py and analysis/agreement.py work unchanged.

Wall: ~2-5 min total (BM25 is fast on these scales).

Reproduce:
    python -m experiments.nl_fl_matching.runners.run_bm25_baseline --direction f2i
    python -m experiments.nl_fl_matching.runners.run_bm25_baseline --direction i2f
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "rds"))

import numpy as np
from rank_bm25 import BM25Okapi

from utils.connect import get_rds_connection  # noqa: E402

from experiments.nl_fl_matching import gold, store, topk  # noqa: E402


TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def tokenize(text: str) -> List[str]:
    if not text:
        return []
    return TOKEN_RE.findall(text.lower())


_QUERY_SLOGAN_SQL = """
WITH ids AS (SELECT UNNEST(%(sids)s::uuid[]) AS sid)
SELECT DISTINCT ON (sl.statement_id)
       sl.statement_id::text, sl.slogan
  FROM ids JOIN slogan sl ON sl.statement_id = ids.sid
 WHERE sl.model_name = 'qwen3-235b' AND NOT sl.insufficient_context
 ORDER BY sl.statement_id, sl.created_at
"""


_BLUEPRINT_POOL_SQL = """
SELECT DISTINCT ON (sl.statement_id)
       sl.statement_id::text, st.paper_id::text, sl.slogan
  FROM slogan sl
  JOIN statement st ON st.statement_id = sl.statement_id
  JOIN paper p      ON p.paper_id = st.paper_id
 WHERE sl.model_name = 'qwen3-235b'
   AND NOT sl.insufficient_context
   AND p.source = 'Lean Community'
   AND st.formality = 'informal'
 ORDER BY sl.statement_id, sl.created_at
"""


_PROJECT_FORMAL_POOL_SQL = """
SELECT DISTINCT ON (sl.statement_id)
       sl.statement_id::text, st.paper_id::text, sl.slogan
  FROM slogan sl
  JOIN statement st ON st.statement_id = sl.statement_id
  JOIN paper p      ON p.paper_id = st.paper_id
 WHERE sl.model_name = 'qwen3-235b'
   AND NOT sl.insufficient_context
   AND p.source = 'Lean Repo'
   AND p.external_id NOT LIKE 'Mathlib_%%'
   AND p.external_id NOT LIKE 'Batteries_%%'
 ORDER BY sl.statement_id, sl.created_at
"""


def fetch_slogans(conn, sids: List[str]) -> dict:
    out = {}
    with conn.cursor() as cur:
        cur.execute(_QUERY_SLOGAN_SQL, {"sids": sids})
        for sid, slogan in cur.fetchall():
            out[sid] = slogan
    return out


def fetch_pool(conn, sql: str) -> Tuple[List[str], List[str], List[str]]:
    sids, pids, slogans = [], [], []
    with conn.cursor() as cur:
        cur.execute(sql)
        for sid, pid, slogan in cur.fetchall():
            sids.append(sid); pids.append(pid); slogans.append(slogan)
    return sids, pids, slogans


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--direction", choices=("f2i","i2f"), required=True)
    p.add_argument("--k", type=int, default=10)
    p.add_argument("--limit", type=int, default=None,
                   help="cap queries for smoke testing")
    args = p.parse_args()

    conn = get_rds_connection("v2")
    store.ensure_table(conn)

    print(f"[1] loading gold + pool for direction={args.direction}...", flush=True)
    g = gold.load_gold(conn, embedding_model="qwen3-8b")

    if args.direction == "f2i":
        queries = g.formals
        pool_sql = _BLUEPRINT_POOL_SQL
        pool_descriptor = "gold_subset_f2i_bm25_blueprint"
    else:  # i2f
        queries = g.informals
        pool_sql = _PROJECT_FORMAL_POOL_SQL
        pool_descriptor = "gold_subset_i2f_bm25_projformal"

    if args.limit:
        queries = queries[: args.limit]
        pool_descriptor += f"_limit{args.limit}"

    t0 = time.perf_counter()
    pool_sids, pool_pids, pool_slogans = fetch_pool(conn, pool_sql)
    print(f"  pool size: {len(pool_sids):,}  ({time.perf_counter()-t0:.1f}s)",
          flush=True)

    print(f"  tokenizing pool...", flush=True)
    t0 = time.perf_counter()
    pool_tokens = [tokenize(s) for s in pool_slogans]
    print(f"  done ({time.perf_counter()-t0:.1f}s)", flush=True)

    print(f"[2] building BM25 index...", flush=True)
    t0 = time.perf_counter()
    bm25 = BM25Okapi(pool_tokens)
    print(f"  done ({time.perf_counter()-t0:.1f}s)", flush=True)

    print(f"[3] fetching query slogans...", flush=True)
    query_sids = [q.statement_id for q in queries]
    qslogans = fetch_slogans(conn, query_sids)
    print(f"  {len(qslogans)} / {len(query_sids)} queries have a usable slogan",
          flush=True)

    # Clear any prior bm25 run for this direction.
    store.clear_run(conn, direction=args.direction, exclusion="statement",
                    embedding_model="bm25", pool_descriptor=pool_descriptor)

    print(f"[4] scoring {len(queries):,} queries via BM25 (k={args.k})...", flush=True)
    t0 = time.perf_counter()

    pending = []
    total_written = 0
    empty = 0

    # Map sid → index for fast self-exclusion.
    sid_to_idx = {s: i for i, s in enumerate(pool_sids)}

    for qi, q in enumerate(queries):
        slogan = qslogans.get(q.statement_id)
        if not slogan:
            empty += 1
            continue
        tokens = tokenize(slogan)
        if not tokens:
            empty += 1
            continue
        scores = bm25.get_scores(tokens)
        # Self-exclusion (in case the query is in the pool).
        idx = sid_to_idx.get(q.statement_id)
        if idx is not None:
            scores[idx] = -np.inf
        if args.k >= len(scores):
            order = np.argsort(-scores)
        else:
            cand = np.argpartition(-scores, args.k)[:args.k]
            order = cand[np.argsort(-scores[cand])]
        results = []
        for rank, j in enumerate(order, 1):
            if not np.isfinite(scores[j]):
                continue
            results.append(topk.TopKResult(
                query_statement_id=q.statement_id,
                rank=rank,
                candidate_statement_id=pool_sids[j],
                candidate_paper_id=pool_pids[j],
                similarity=float(scores[j]),  # raw BM25 score, NOT cosine
            ))
        pending.extend(results)
        if (qi + 1) % 200 == 0 and pending:
            n = store.write_rows(
                conn, pending,
                direction=args.direction, exclusion="statement",
                pool_descriptor=pool_descriptor, embedding_model="bm25",
            )
            total_written += n; pending.clear()
            elapsed = time.perf_counter() - t0
            print(f"  [{qi+1}/{len(queries)}] wrote {total_written:,} "
                  f"({elapsed:.0f}s)", flush=True)
    if pending:
        n = store.write_rows(
            conn, pending,
            direction=args.direction, exclusion="statement",
            pool_descriptor=pool_descriptor, embedding_model="bm25",
        )
        total_written += n

    elapsed = time.perf_counter() - t0
    print(f"[5] done. {len(queries)} queries, {total_written:,} rows, "
          f"{empty} empty, {elapsed:.0f}s", flush=True)
    conn.close()


if __name__ == "__main__":
    main()
