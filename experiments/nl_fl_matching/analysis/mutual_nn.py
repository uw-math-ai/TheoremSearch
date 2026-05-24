"""Compute mutual rank-1 nearest-neighbour pairs across f2i and i2f.

A pair (informal i, formal f) is mutual rank-1 if both:
  - formal f's f→i top-1 = i
  - informal i's i→f top-1 = f

Mutual pairs are higher-confidence than one-sided rank-1 matches and are the
strongest "this is the same statement" signal the pipeline produces.

Outputs:
  - stdout: counts + bucket overlap (mutual ∩ gold vs mutual ∖ gold)
  - data/mutual_rank1_pairs.csv: (informal_sid, formal_sid, sim_f2i, sim_i2f,
    is_blueprint_gold)

Usage:
    python -m experiments.nl_fl_matching.analysis.mutual_nn
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "rds"))

from utils.connect import get_rds_connection  # noqa: E402
from experiments.nl_fl_matching import gold  # noqa: E402


_MUTUAL_SQL = """
WITH f2i_top1 AS (
    SELECT query_statement_id     AS fml_sid,
           candidate_statement_id AS inf_sid,
           similarity              AS sim_f2i
      FROM nl_fl_match_pilot
     WHERE direction = 'f2i'
       AND embedding_model = %(model)s
       AND exclusion = %(exclusion)s
       AND pool_descriptor = %(f2i_pool)s
       AND rank = 1
),
i2f_top1 AS (
    SELECT query_statement_id     AS inf_sid,
           candidate_statement_id AS fml_sid,
           similarity              AS sim_i2f
      FROM nl_fl_match_pilot
     WHERE direction = 'i2f'
       AND embedding_model = %(model)s
       AND exclusion = %(exclusion)s
       AND pool_descriptor = %(i2f_pool)s
       AND rank = 1
)
SELECT f.inf_sid::text, f.fml_sid::text, f.sim_f2i, i.sim_i2f
  FROM f2i_top1 f
  JOIN i2f_top1 i
    ON i.inf_sid = f.inf_sid
   AND i.fml_sid = f.fml_sid
"""


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--embedding-model", default="qwen3-8b")
    p.add_argument("--exclusion", default="statement")
    p.add_argument("--f2i-pool", default="gold_subset_f2i")
    p.add_argument("--i2f-pool", default="gold_subset_i2f")
    p.add_argument("--out", type=Path,
                   default=REPO_ROOT / "experiments/nl_fl_matching/data/mutual_rank1_pairs.csv")
    args = p.parse_args()

    conn = get_rds_connection("v2")
    print("loading gold pairs...", flush=True)
    g = gold.load_gold(conn, embedding_model=args.embedding_model)
    print(f"  {len(g.pairs):,} gold pairs", flush=True)

    print("querying mutual rank-1 pairs...", flush=True)
    with conn.cursor() as cur:
        cur.execute(_MUTUAL_SQL, {
            "model":     args.embedding_model,
            "exclusion": args.exclusion,
            "f2i_pool":  args.f2i_pool,
            "i2f_pool":  args.i2f_pool,
        })
        rows = cur.fetchall()
    conn.close()

    rows_with_gold = []
    n_gold = 0
    for inf_sid, fml_sid, sim_f2i, sim_i2f in rows:
        is_gold = (inf_sid, fml_sid) in g.pairs
        n_gold += int(is_gold)
        rows_with_gold.append((inf_sid, fml_sid, sim_f2i, sim_i2f, is_gold))

    n = len(rows_with_gold)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as fh:
        w = csv.writer(fh, quoting=csv.QUOTE_ALL)
        w.writerow(["informal_sid", "formal_sid", "sim_f2i", "sim_i2f", "is_blueprint_gold"])
        for r in rows_with_gold:
            w.writerow(r)

    print()
    print("=" * 64)
    print(f"MUTUAL RANK-1 PAIRS")
    print("=" * 64)
    print(f"  total mutual:        {n:,}")
    print(f"  mutual ∩ gold:       {n_gold:,}  ({n_gold/max(n,1):.1%} of mutual)")
    print(f"  mutual ∖ gold:       {n - n_gold:,}  (candidates for blueprint backfill)")
    print(f"  gold ∩ mutual:       {n_gold:,}  ({n_gold/max(len(g.pairs),1):.1%} of gold)")
    print(f"  wrote {n:,} rows to {args.out.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
