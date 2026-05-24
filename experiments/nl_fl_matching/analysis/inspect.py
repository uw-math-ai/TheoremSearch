"""Eyeball-inspect top-K results for a few gold queries.

For each sampled query, print:
  - the query statement (slogan + name)
  - its top-K candidates from nl_fl_match_pilot
  - whether each candidate is in the query's gold set

Helps spot-check that the embedding is surfacing sensible matches before
investing in a full eval.

Usage:
  python -m experiments.nl_fl_matching.analysis.inspect \\
      --direction f2i --pool-descriptor gold_subset_f2i --samples 5
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "rds"))

from utils.connect import get_rds_connection  # noqa: E402
from experiments.nl_fl_matching import gold  # noqa: E402
from experiments.nl_fl_matching.analysis.eval import fetch_rows  # noqa: E402


def _truncate(s: str, n: int = 110) -> str:
    s = (s or "").replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def fetch_stmt_briefs(conn, statement_ids: List[str]) -> Dict[str, Dict]:
    """Return {sid: {'name', 'slogan', 'source', 'paper_title'}}."""
    if not statement_ids:
        return {}
    sql = """
    SELECT DISTINCT ON (s.statement_id)
           s.statement_id::text,
           CASE WHEN fm.decl_name IS NOT NULL THEN fm.decl_name
                ELSE initcap(s.kind) || COALESCE(' ' || im.ref, '') END AS name,
           sl.slogan,
           p.source,
           p.title
      FROM statement s
      JOIN slogan sl ON sl.statement_id = s.statement_id
      LEFT JOIN formal_metadata   fm ON fm.statement_id = s.statement_id
      LEFT JOIN informal_metadata im ON im.statement_id = s.statement_id
      LEFT JOIN paper p ON p.paper_id = s.paper_id
     WHERE s.statement_id = ANY(%s::uuid[])
       AND NOT sl.insufficient_context
     ORDER BY s.statement_id, sl.created_at
    """
    out: Dict[str, Dict] = {}
    with conn.cursor() as cur:
        cur.execute(sql, (statement_ids,))
        for sid, name, slogan, source, title in cur.fetchall():
            out[sid] = {
                "name":         name or "<unnamed>",
                "slogan":       slogan or "",
                "source":       source or "?",
                "paper_title":  title or "?",
            }
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--embedding-model", default="qwen3-8b")
    p.add_argument("--direction", default="f2i", choices=("f2i", "i2f"))
    p.add_argument("--pool-descriptor", default="gold_subset_f2i")
    p.add_argument("--exclusion", default="statement")
    p.add_argument("--samples", type=int, default=5)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()

    conn = get_rds_connection("v2")
    g = gold.load_gold(conn, embedding_model=args.embedding_model)
    ranks = fetch_rows(conn, args.direction, args.embedding_model,
                      pool_descriptor=args.pool_descriptor,
                      exclusion=args.exclusion)
    if not ranks:
        raise SystemExit(f"no rows for {args.direction!r} / "
                         f"{args.pool_descriptor!r} yet")

    rng = random.Random(args.seed)
    qids = sorted(ranks.keys())
    sample_qids = rng.sample(qids, min(args.samples, len(qids)))

    gold_lookup = (g.formal_to_gold_informals if args.direction == "f2i"
                   else g.informal_to_gold_formals)

    all_sids = set(sample_qids)
    for qid in sample_qids:
        for _, cid, _ in ranks[qid]:
            all_sids.add(cid)
    briefs = fetch_stmt_briefs(conn, list(all_sids))
    conn.close()

    print()
    print(f"=== {args.direction} inspection ({len(sample_qids)} queries) ===")
    for qid in sample_qids:
        qb = briefs.get(qid, {})
        golds = gold_lookup.get(qid, set())
        print()
        print(f"--- query {qid[:8]} ({len(golds)} gold candidates) ---")
        print(f"  name:   {_truncate(qb.get('name', '?'))}")
        print(f"  source: {qb.get('source', '?')}")
        print(f"  paper:  {_truncate(qb.get('paper_title', '?'), 80)}")
        print(f"  slogan: {_truncate(qb.get('slogan', ''))}")
        print(f"  --- top {len(ranks[qid])} candidates ---")
        for rank, cid, sim in ranks[qid]:
            cb = briefs.get(cid, {})
            mark = " *GOLD*" if cid in golds else ""
            print(f"   {rank:>2}. {sim:.3f}  {_truncate(cb.get('name', '?'), 50)}"
                  f"  [{cb.get('source', '?')}]{mark}")
            print(f"        {_truncate(cb.get('slogan', ''))}")


if __name__ == "__main__":
    main()
