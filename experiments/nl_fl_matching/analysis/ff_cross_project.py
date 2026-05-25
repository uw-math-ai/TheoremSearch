"""Analyze the f→f cross-project sweep.

Pulls direction='f2f', exclusion='paper', pool_descriptor='cross_project_f2f'
from nl_fl_match_pilot and reports:

  - rank-1 similarity distribution (count by bucket)
  - "twin" candidates per threshold (sim ≥ 0.85 / 0.90 / 0.95)
  - per-paper twin counts (which repos have the most cross-project overlap)
  - top-20 highest-similarity twin pairs, hydrated for eyeballing

Outputs:
  stdout summary
  data/ff_cross_project_twins.csv (rank-1 rows sorted by sim desc)
  data/ff_cross_project_top20.md  (hydrated eyeball list)

Usage:
    python -m experiments.nl_fl_matching.analysis.ff_cross_project
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


_RANK1_SQL = """
WITH r1 AS (
    SELECT query_statement_id, candidate_statement_id, candidate_paper_id,
           similarity
      FROM nl_fl_match_pilot
     WHERE direction = 'f2f'
       AND exclusion = 'paper'
       AND embedding_model = %(model)s
       AND pool_descriptor = %(pool)s
       AND rank = 1
)
SELECT r1.query_statement_id::text,
       r1.candidate_statement_id::text,
       qst.paper_id::text   AS q_paper_id,
       qp.external_id        AS q_paper,
       qfm.decl_name         AS q_decl_name,
       qfm.module            AS q_module,
       cst.paper_id::text   AS c_paper_id,
       cp.external_id        AS c_paper,
       cfm.decl_name         AS c_decl_name,
       cfm.module            AS c_module,
       r1.similarity
  FROM r1
  JOIN statement        qst ON qst.statement_id = r1.query_statement_id
  JOIN paper            qp  ON qp.paper_id      = qst.paper_id
  LEFT JOIN formal_metadata qfm ON qfm.statement_id = r1.query_statement_id
  JOIN statement        cst ON cst.statement_id = r1.candidate_statement_id
  JOIN paper            cp  ON cp.paper_id      = cst.paper_id
  LEFT JOIN formal_metadata cfm ON cfm.statement_id = r1.candidate_statement_id
 ORDER BY r1.similarity DESC
"""


_SLOGAN_SQL = """
SELECT DISTINCT ON (sl.statement_id) sl.statement_id::text, sl.slogan
  FROM slogan sl
 WHERE sl.statement_id = ANY(%(sids)s::uuid[])
   AND NOT sl.insufficient_context
 ORDER BY sl.statement_id, sl.created_at
"""


def _bucket(sim: float) -> str:
    for thr, label in ((0.95, "≥0.95"), (0.90, "≥0.90"),
                       (0.85, "≥0.85"), (0.80, "≥0.80"),
                       (0.70, "≥0.70"), (0.50, "≥0.50")):
        if sim >= thr:
            return label
    return "<0.50"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--embedding-model", default="qwen3-8b")
    p.add_argument("--pool", default="cross_project_f2f")
    p.add_argument("--out-csv", type=Path,
                   default=REPO_ROOT / "experiments/nl_fl_matching/data/ff_cross_project_twins.csv")
    p.add_argument("--out-md", type=Path,
                   default=REPO_ROOT / "experiments/nl_fl_matching/data/ff_cross_project_top20.md")
    p.add_argument("--top-n", type=int, default=20)
    args = p.parse_args()

    conn = get_rds_connection("v2")
    print("fetching rank-1 rows...", flush=True)
    with conn.cursor() as cur:
        cur.execute(_RANK1_SQL, {"model": args.embedding_model, "pool": args.pool})
        cols = [d.name for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    print(f"  {len(rows):,} rank-1 pairs", flush=True)

    # Hydrate slogans for the top-N.
    top_n = rows[: args.top_n]
    sid_set = {r["query_statement_id"] for r in top_n} | {r["candidate_statement_id"] for r in top_n}
    with conn.cursor() as cur:
        cur.execute(_SLOGAN_SQL, {"sids": list(sid_set)})
        slogan_by_sid = {sid: sl for sid, sl in cur.fetchall()}
    conn.close()

    # Histogram.
    from collections import Counter
    buckets = Counter(_bucket(r["similarity"]) for r in rows)
    print()
    print("rank-1 similarity distribution")
    for label in ("≥0.95", "≥0.90", "≥0.85", "≥0.80", "≥0.70", "≥0.50", "<0.50"):
        count = buckets.get(label, 0)
        print(f"  {label:>7}  {count:>6,}  {count/max(len(rows),1):>6.1%}")

    # Cumulative twin counts.
    print()
    print("cumulative twin counts")
    for thr in (0.95, 0.90, 0.85, 0.80, 0.70):
        n = sum(1 for r in rows if r["similarity"] >= thr)
        print(f"  sim ≥ {thr:.2f}: {n:>6,}  ({n/max(len(rows),1):>5.1%})")

    # Per-paper twin counts (sim ≥ 0.85).
    thr = 0.85
    per_paper_q = Counter()
    per_paper_pair = Counter()
    for r in rows:
        if r["similarity"] < thr:
            continue
        per_paper_q[r["q_paper"]] += 1
        pair = tuple(sorted([r["q_paper"], r["c_paper"]]))
        per_paper_pair[pair] += 1

    print()
    print(f"top repos by query count with twin at sim ≥ {thr}")
    for paper, n in per_paper_q.most_common(15):
        print(f"  {n:>5,}  {paper}")

    print()
    print(f"top repo-pairs (sim ≥ {thr})")
    for (a, b), n in per_paper_pair.most_common(15):
        print(f"  {n:>5,}  {a}  ↔  {b}")

    # CSV: all rank-1.
    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.out_csv.open("w") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, quoting=csv.QUOTE_ALL)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"\nwrote {len(rows):,} rows → {args.out_csv.relative_to(REPO_ROOT)}")

    # Markdown: hydrated top-N.
    with args.out_md.open("w") as fh:
        fh.write(f"# Top-{len(top_n)} cross-project formal twins\n\n")
        fh.write("Generated by `analysis/ff_cross_project.py`. "
                 "Each row: a project formal's rank-1 nearest neighbour "
                 "from a *different* project, sorted by cosine similarity.\n\n")
        for r in top_n:
            fh.write(f"## sim {r['similarity']:.3f}\n")
            fh.write(f"- **{r['q_paper']}** `{r['q_decl_name']}` "
                     f"(`{r['q_module']}`)\n")
            fh.write(f"  > {(slogan_by_sid.get(r['query_statement_id']) or '')[:300]}\n")
            fh.write(f"- **{r['c_paper']}** `{r['c_decl_name']}` "
                     f"(`{r['c_module']}`)\n")
            fh.write(f"  > {(slogan_by_sid.get(r['candidate_statement_id']) or '')[:300]}\n\n")
    print(f"wrote top-{len(top_n)} md → {args.out_md.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
