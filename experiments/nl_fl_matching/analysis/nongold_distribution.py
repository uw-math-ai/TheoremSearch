"""Analyze the non-gold random f→i sweep.

Pulls direction='f2i', pool_descriptor='nongold_random_f2i' from
nl_fl_match_pilot. Compares the rank-1 similarity distribution against
the gold-pool baseline. Surfaces:

  - histogram of rank-1 similarities
  - cumulative twin counts at threshold
  - source breakdown of rank-1 candidates (Lean Repo / arXiv / Stacks / ...)
  - top-N highest-sim non-gold matches, hydrated for eyeballing

Usage:
    python -m experiments.nl_fl_matching.analysis.nongold_distribution
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "rds"))

from utils.connect import get_rds_connection  # noqa: E402


_RANK1_SQL = """
WITH r1 AS (
    SELECT query_statement_id, candidate_statement_id, similarity
      FROM nl_fl_match_pilot
     WHERE direction = 'f2i' AND exclusion = 'statement'
       AND embedding_model = %(model)s
       AND pool_descriptor = %(pool)s
       AND rank = 1
),
q_sl AS (
    SELECT DISTINCT ON (sl.statement_id) sl.statement_id, sl.slogan
      FROM slogan sl
     WHERE sl.statement_id IN (SELECT query_statement_id FROM r1)
       AND NOT sl.insufficient_context
     ORDER BY sl.statement_id, sl.created_at
),
c_sl AS (
    SELECT DISTINCT ON (sl.statement_id) sl.statement_id, sl.slogan
      FROM slogan sl
     WHERE sl.statement_id IN (SELECT candidate_statement_id FROM r1)
       AND NOT sl.insufficient_context
     ORDER BY sl.statement_id, sl.created_at
)
SELECT r1.similarity,
       r1.query_statement_id::text     AS q_sid,
       qp.external_id                   AS q_paper,
       qp.source                        AS q_source,
       qfm.decl_name                    AS q_decl_name,
       qsl.slogan                       AS q_slogan,
       r1.candidate_statement_id::text  AS c_sid,
       cp.external_id                   AS c_paper,
       cp.source                        AS c_source,
       cim.ref                          AS c_ref,
       cim.lean                         AS c_lean_annotation,
       csl.slogan                       AS c_slogan
  FROM r1
  JOIN statement qst ON qst.statement_id = r1.query_statement_id
  JOIN paper     qp  ON qp.paper_id      = qst.paper_id
  LEFT JOIN formal_metadata   qfm ON qfm.statement_id = r1.query_statement_id
  LEFT JOIN q_sl              qsl ON qsl.statement_id = r1.query_statement_id
  JOIN statement cst ON cst.statement_id = r1.candidate_statement_id
  JOIN paper     cp  ON cp.paper_id      = cst.paper_id
  LEFT JOIN informal_metadata cim ON cim.statement_id = r1.candidate_statement_id
  LEFT JOIN c_sl              csl ON csl.statement_id = r1.candidate_statement_id
 ORDER BY r1.similarity DESC
"""


def _bucket(sim: float) -> str:
    for thr, label in ((0.95, "≥0.95"), (0.90, "≥0.90"),
                       (0.85, "≥0.85"), (0.80, "≥0.80"),
                       (0.70, "≥0.70"), (0.50, "≥0.50")):
        if sim >= thr:
            return label
    return "<0.50"


def _short(s, n=200):
    if not s:
        return ""
    s = str(s).replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--pool", default="nongold_random_f2i")
    p.add_argument("--embedding-model", default="qwen3-8b")
    p.add_argument("--top-n", type=int, default=20)
    p.add_argument("--out-csv", type=Path,
                   default=REPO_ROOT / "experiments/nl_fl_matching/data/nongold_rank1.csv")
    p.add_argument("--out-md", type=Path,
                   default=REPO_ROOT / "experiments/nl_fl_matching/data/nongold_top20.md")
    args = p.parse_args()

    conn = get_rds_connection("v2")
    print("fetching rank-1 rows...", flush=True)
    with conn.cursor() as cur:
        cur.execute(_RANK1_SQL, {"model": args.embedding_model, "pool": args.pool})
        cols = [d.name for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    print(f"  {len(rows):,} rank-1 rows", flush=True)

    if not rows:
        print("no rows; aborting.")
        return

    # 1. Histogram + cumulative twins.
    buckets = Counter(_bucket(r["similarity"]) for r in rows)
    print("\nrank-1 similarity distribution")
    for label in ("≥0.95", "≥0.90", "≥0.85", "≥0.80", "≥0.70", "≥0.50", "<0.50"):
        n = buckets.get(label, 0)
        print(f"  {label:>7}  {n:>5}  {n/len(rows):>6.1%}")

    print("\ncumulative")
    for thr in (0.95, 0.90, 0.85, 0.80, 0.70):
        n = sum(1 for r in rows if r["similarity"] >= thr)
        print(f"  sim ≥ {thr:.2f}: {n:>5}  ({n/len(rows):>5.1%})")

    # 2. Candidate source breakdown.
    src = Counter(r["c_source"] for r in rows)
    print("\nrank-1 candidate sources")
    for s, n in src.most_common():
        print(f"  {n:>5}  {s}")

    # High-sim candidate sources (≥ 0.85).
    src_hi = Counter(r["c_source"] for r in rows if r["similarity"] >= 0.85)
    print("\nrank-1 candidate sources (sim ≥ 0.85)")
    for s, n in src_hi.most_common():
        print(f"  {n:>5}  {s}")

    # 3. Per-paper query counts (top repos with high-sim matches).
    qp_hi = Counter(r["q_paper"] for r in rows if r["similarity"] >= 0.85)
    print("\nrepos with most rank-1 high-sim (≥ 0.85) matches")
    for paper, n in qp_hi.most_common(10):
        print(f"  {n:>4}  {paper}")

    # CSV: all rank-1.
    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.out_csv.open("w") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, quoting=csv.QUOTE_ALL)
        w.writeheader()
        for r in rows:
            w.writerow({k: _short(r.get(k), 600) for k in cols})
    print(f"\nwrote {len(rows):,} rows → {args.out_csv.relative_to(REPO_ROOT)}")

    # MD: top-N hydrated.
    top = rows[: args.top_n]
    with args.out_md.open("w") as fh:
        fh.write(f"# Top-{len(top)} non-gold random f→i matches\n\n")
        fh.write(f"Pool: `{args.pool}`. Each is a project formal (not in "
                 "blueprint gold) and its rank-1 informal match from the "
                 "11.7M informal pool, sorted by cosine similarity.\n\n")
        for r in top:
            fh.write(f"## sim {r['similarity']:.3f}\n")
            fh.write(f"- **formal** `{r['q_decl_name']}` "
                     f"({r['q_paper']}, source={r['q_source']})\n")
            fh.write(f"  > {_short(r['q_slogan'], 300)}\n")
            fh.write(f"- **informal** `{r['c_ref']}` "
                     f"({r['c_paper']}, source={r['c_source']})\n")
            if r['c_lean_annotation']:
                fh.write(f"  *blueprint `\\lean{{}}` says:* `{r['c_lean_annotation']}`\n")
            fh.write(f"  > {_short(r['c_slogan'], 300)}\n\n")
    print(f"wrote top-{len(top)} md → {args.out_md.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
