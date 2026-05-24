"""Hit@k + MRR evaluation against blueprint gold pairs.

Reads ranked rows from nl_fl_match_pilot, joins to gold.load_gold,
prints the headline table per direction. Mirrors the prior paper's
reporting format (Hit@k / MRR@k).

Usage:
    python -m experiments.nl_fl_matching.analysis.eval

    # restrict to a specific pool_descriptor or k
    python -m experiments.nl_fl_matching.analysis.eval \
        --pool-descriptor gold_subset_f2i --k 20
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "rds"))

from utils.connect import get_rds_connection  # noqa: E402
from experiments.nl_fl_matching import gold  # noqa: E402


@dataclass
class DirectionScore:
    direction: str
    evaluated: int
    hit_at_1: float
    hit_at_5: float
    hit_at_10: float
    mrr_at_10: float
    coverage: float   # % of gold queries that even appear in nl_fl_match_pilot


def fetch_rows(
    conn, direction: str, embedding_model: str,
    pool_descriptor: str | None = None,
    exclusion: str = "statement",
) -> Dict[str, List[tuple]]:
    """Return {query_sid: [(rank, candidate_sid, similarity), ...]} sorted by rank."""
    where = [
        "direction = %s", "embedding_model = %s", "exclusion = %s",
    ]
    params: list = [direction, embedding_model, exclusion]
    if pool_descriptor:
        where.append("pool_descriptor = %s")
        params.append(pool_descriptor)
    sql = f"""
    SELECT query_statement_id::text, rank, candidate_statement_id::text, similarity
      FROM nl_fl_match_pilot
     WHERE {' AND '.join(where)}
     ORDER BY query_statement_id, rank
    """
    out: Dict[str, List[tuple]] = {}
    with conn.cursor() as cur:
        cur.execute(sql, params)
        for qid, rank, cid, sim in cur.fetchall():
            out.setdefault(qid, []).append((rank, cid, float(sim)))
    return out


def score_direction(
    direction: str,
    ranks_by_query: Dict[str, List[tuple]],
    gold_lookup: Dict[str, Set[str]],
    k_max: int = 10,
) -> DirectionScore:
    """gold_lookup is query_sid → set of acceptable candidate_sids."""
    queries_with_gold = list(gold_lookup.keys())
    evaluated = 0
    h1 = h5 = h10 = 0
    rr_sum = 0.0

    for qid in queries_with_gold:
        gold_set = gold_lookup[qid]
        ranked = ranks_by_query.get(qid, [])
        if not ranked:
            continue
        evaluated += 1
        # Best (smallest) rank at which any gold candidate appears.
        best_rank = None
        for rank, cid, _sim in ranked:
            if cid in gold_set:
                best_rank = rank
                break
        if best_rank is None:
            continue
        if best_rank <= 1:
            h1 += 1
        if best_rank <= 5:
            h5 += 1
        if best_rank <= 10:
            h10 += 1
        if best_rank <= k_max:
            rr_sum += 1.0 / best_rank

    n = max(1, evaluated)
    return DirectionScore(
        direction=direction,
        evaluated=evaluated,
        hit_at_1=h1 / n,
        hit_at_5=h5 / n,
        hit_at_10=h10 / n,
        mrr_at_10=rr_sum / n,
        coverage=evaluated / max(1, len(queries_with_gold)),
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--embedding-model", default="qwen3-8b")
    p.add_argument("--exclusion", default="statement",
                   choices=("statement", "paper"))
    p.add_argument("--f2i-pool", default="gold_subset_f2i")
    p.add_argument("--i2f-pool", default="gold_subset_i2f")
    args = p.parse_args()

    conn = get_rds_connection("v2")
    print("loading gold pairs...", flush=True)
    g = gold.load_gold(conn, embedding_model=args.embedding_model)
    print(f"  {len(g.informals)} informals, {len(g.formals)} formals, "
          f"{len(g.pairs)} pairs", flush=True)

    print(f"\nfetching f2i ranks (pool={args.f2i_pool})...", flush=True)
    f2i = fetch_rows(conn, "f2i", args.embedding_model,
                     pool_descriptor=args.f2i_pool, exclusion=args.exclusion)
    print(f"  {len(f2i)} queries with ranks", flush=True)

    print(f"fetching i2f ranks (pool={args.i2f_pool})...", flush=True)
    i2f = fetch_rows(conn, "i2f", args.embedding_model,
                     pool_descriptor=args.i2f_pool, exclusion=args.exclusion)
    print(f"  {len(i2f)} queries with ranks", flush=True)
    conn.close()

    f2i_score = score_direction("f2i", f2i, g.formal_to_gold_informals)
    i2f_score = score_direction("i2f", i2f, g.informal_to_gold_formals)

    print()
    print("=" * 80)
    print(f"BLUEPRINT GOLD-PAIR HEADLINE TABLE  (embedding_model={args.embedding_model})")
    print("=" * 80)
    print()
    print(f"  {'direction':<14} {'evaluated':>10} "
          f"{'Hit@1':>8} {'Hit@5':>8} {'Hit@10':>8} {'MRR@10':>8} {'coverage':>10}")
    print(f"  {'-'*14} {'-'*10} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*10}")
    for s in (f2i_score, i2f_score):
        print(f"  {s.direction:<14} {s.evaluated:>10,} "
              f"{s.hit_at_1:>8.3f} {s.hit_at_5:>8.3f} {s.hit_at_10:>8.3f} "
              f"{s.mrr_at_10:>8.3f} {s.coverage:>10.1%}")
    print()


if __name__ == "__main__":
    main()
