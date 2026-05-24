"""Correlation between embedding similarity and basic NL methods.

For a sample of pairs surfaced by the embedding sweep (typically the
top-1 from each gold f2i row), compute the canonical lexical metrics
(BM25, TF-IDF cosine, char-trigram Jaccard, token Jaccard, normalized
edit distance) and report Spearman correlation against embedding cosine.

Answers task (4): "do we see a correlation between basic NL methods and
the matches we think are good quality from (1-3)?". Useful as both a
sanity check (high-emb-sim pairs should also score high on simple
metrics if the embedding is honest) and as material for a paper figure.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "rds"))

from utils.connect import get_rds_connection  # noqa: E402
from experiments.formal_graph.blueprint_matching import metrics  # noqa: E402
from experiments.nl_fl_matching.analysis.eval import fetch_rows  # noqa: E402


def fetch_slogans(conn, statement_ids: List[str]) -> Dict[str, str]:
    """Return {statement_id: earliest non-insufficient slogan text}."""
    if not statement_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (statement_id)
                   statement_id::text, slogan
              FROM slogan
             WHERE statement_id = ANY(%s::uuid[])
               AND NOT insufficient_context
             ORDER BY statement_id, created_at
            """,
            (statement_ids,),
        )
        return {sid: text for sid, text in cur.fetchall()}


def spearman(xs: List[float], ys: List[float]) -> float:
    """Spearman rank correlation. Local impl so we don't pull scipy."""
    n = len(xs)
    if n < 2:
        return 0.0
    def rank(arr):
        order = sorted(range(n), key=lambda i: arr[i])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and arr[order[j+1]] == arr[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                ranks[order[k]] = avg
            i = j + 1
        return ranks
    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx)/n, sum(ry)/n
    num = sum((rx[i]-mx)*(ry[i]-my) for i in range(n))
    den_x = sum((rx[i]-mx)**2 for i in range(n)) ** 0.5
    den_y = sum((ry[i]-my)**2 for i in range(n)) ** 0.5
    return num / (den_x * den_y) if den_x and den_y else 0.0


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--embedding-model", default="qwen3-8b")
    p.add_argument("--exclusion", default="statement")
    p.add_argument("--direction", default="f2i", choices=("f2i", "i2f"))
    p.add_argument("--pool-descriptor", default="gold_subset_f2i")
    p.add_argument("--sample", type=int, default=500,
                   help="Number of top-1 pairs to sample for the analysis.")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out-csv", type=Path, default=None,
                   help="Optional path to write per-pair scores for plotting.")
    args = p.parse_args()

    conn = get_rds_connection("v2")
    ranks = fetch_rows(
        conn, args.direction, args.embedding_model,
        pool_descriptor=args.pool_descriptor, exclusion=args.exclusion,
    )
    # Take rank-1 row from each query → one (query, candidate, sim) per query.
    top1: List[tuple] = []
    for qid, ranked in ranks.items():
        for rank, cid, sim in ranked:
            if rank == 1:
                top1.append((qid, cid, sim))
                break
    if not top1:
        raise SystemExit("no rank-1 rows in nl_fl_match_pilot — has the sweep finished?")

    import random
    rng = random.Random(args.seed)
    if len(top1) > args.sample:
        top1 = rng.sample(top1, args.sample)
    print(f"sampled {len(top1)} top-1 pairs", flush=True)

    all_ids = sorted({qid for qid, _, _ in top1} | {cid for _, cid, _ in top1})
    slogans = fetch_slogans(conn, all_ids)
    conn.close()

    q_texts = [slogans.get(qid, "") for qid, _, _ in top1]
    c_texts = [slogans.get(cid, "") for _, cid, _ in top1]
    emb_sims = [sim for _, _, sim in top1]

    methods = {
        "edit_norm":       metrics.edit_norm,
        "jaccard_tokens":  metrics.jaccard_tokens,
        "char_3gram":      lambda a, b: metrics.char_ngram_jaccard(a, b, 3),
        "char_4gram":      lambda a, b: metrics.char_ngram_jaccard(a, b, 4),
        "tfidf_cosine":    metrics.tfidf_cosine,
        "bm25":            metrics.bm25,
    }

    # Each metric returns N×M; we just want the diagonal (i-th query vs i-th cand).
    rows: List[Dict] = []
    for i in range(len(top1)):
        rows.append({"emb_cos": emb_sims[i]})
    print(f"\ncomputing text metrics on {len(top1)} pairs...", flush=True)
    for name, fn in methods.items():
        import time
        t0 = time.perf_counter()
        mat = fn(q_texts, c_texts)
        diag = [float(mat[i, i]) for i in range(len(top1))]
        for i, v in enumerate(diag):
            rows[i][name] = v
        rho = spearman(emb_sims, diag)
        print(f"  {name:<16} spearman(emb_cos, {name}) = {rho:+.3f}  "
              f"({time.perf_counter() - t0:.1f}s)", flush=True)

    if args.out_csv:
        import csv
        cols = ["emb_cos"] + list(methods.keys())
        with args.out_csv.open("w") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            for r in rows:
                w.writerow(r)
        print(f"\nwrote per-pair scores to {args.out_csv}")


if __name__ == "__main__":
    main()
