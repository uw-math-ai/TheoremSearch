"""Root-cause empty-query rate in the matching sweeps.

For each completed sweep (gold f2i, gold i2f, non-gold random f2i), look at
the queries that returned zero candidates. Categorize the cause by joining
back to the source tables:

  - "no_slogan"          : no row in slogan for the statement
  - "insufficient_context": all slogans flagged insufficient_context
  - "no_embedding"       : slogan exists but no embedding row
  - "missing_embedding_model": embedding row exists for different model
  - "non_qwen_only"      : slogans exist only from non-qwen3-235b models
  - "had_results"        : query did run; emptiness is downstream of ANN

Produces:
  - stdout summary table
  - data/empty_query_audit.csv with one row per investigated query

Reproduce:
    python -m experiments.nl_fl_matching.analysis.diagnose_empties
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "rds"))

from utils.connect import get_rds_connection  # noqa: E402
from experiments.nl_fl_matching import gold, pools  # noqa: E402


_DIAGNOSE_SQL = """
WITH q AS (SELECT UNNEST(%(sids)s::uuid[]) AS sid),
     have_slogan AS (
        SELECT q.sid,
               BOOL_OR(NOT sl.insufficient_context AND sl.model_name = ANY(%(slogan_models)s)) AS has_good_slogan,
               BOOL_OR(sl.model_name = ANY(%(slogan_models)s)) AS has_any_qwen_slogan,
               BOOL_OR(true)                                  AS has_any_slogan,
               BOOL_OR(sl.insufficient_context)               AS has_insufficient
          FROM q
          LEFT JOIN slogan sl ON sl.statement_id = q.sid
         GROUP BY q.sid
     ),
     have_embedding AS (
        SELECT q.sid,
               BOOL_OR(e.model_name = %(emb_model)s) AS has_target_embedding,
               BOOL_OR(true)                          AS has_any_embedding
          FROM q
          LEFT JOIN slogan sl ON sl.statement_id = q.sid
          LEFT JOIN embedding e ON e.slogan_id = sl.slogan_id
         GROUP BY q.sid
     )
SELECT q.sid::text,
       hs.has_any_slogan,
       hs.has_any_qwen_slogan,
       hs.has_good_slogan,
       hs.has_insufficient,
       he.has_target_embedding,
       he.has_any_embedding
  FROM q
  LEFT JOIN have_slogan have_slogan ON have_slogan.sid = q.sid
  LEFT JOIN have_embedding he ON he.sid = q.sid
  LEFT JOIN have_slogan hs ON hs.sid = q.sid
"""


def _categorize(row) -> str:
    (sid, has_slogan, has_qwen, has_good, has_insuf,
     has_emb, has_any_emb) = row
    if not has_slogan:
        return "no_slogan"
    if not has_qwen:
        return "non_qwen_only"
    if has_insuf and not has_good:
        return "insufficient_context"
    if not has_any_emb:
        return "no_embedding"
    if not has_emb:
        return "missing_embedding_model"
    # had a good slogan + embedding → not empty for a structural reason.
    return "had_results"


def main() -> None:
    conn = get_rds_connection("v2")
    print("loading gold pairs...", flush=True)
    g = gold.load_gold(conn, embedding_model="qwen3-8b")
    gold_formals = list(g.formals)
    gold_informals = list(g.informals)
    print(f"  gold formals: {len(gold_formals)}, gold informals: {len(gold_informals)}",
          flush=True)

    # f2i gold queries: the 1,577 gold formals, of which 15 came back empty
    # (per bidirectional_matching.md).
    # i2f gold queries: 1,308 — 0 empty.
    # Non-gold sample (n=500): 114 empty.
    # Pull *all* gold formal sids, then partition by sweep results.

    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT query_statement_id::text
              FROM nl_fl_match_pilot
             WHERE direction='f2i' AND pool_descriptor='gold_subset_f2i'
        """)
        f2i_queries_with_rows = {r[0] for r in cur.fetchall()}
        cur.execute("""
            SELECT DISTINCT query_statement_id::text
              FROM nl_fl_match_pilot
             WHERE direction='f2i' AND pool_descriptor='nongold_random_f2i'
        """)
        nongold_queries_with_rows = {r[0] for r in cur.fetchall()}

    gold_formal_sids = {s.statement_id for s in gold_formals}
    f2i_empty = gold_formal_sids - f2i_queries_with_rows

    # Need the nongold sample's intended sids: rebuild deterministically.
    print("recomputing intended non-gold sample...", flush=True)
    all_formals = pools.fetch_project_formals(conn, embedding_model="qwen3-8b")
    gold_fsids_for_exclusion = {fid for _, fid in g.pairs}
    nongold_pool = [s for s in all_formals
                    if s.statement_id not in gold_fsids_for_exclusion]
    import random
    rng = random.Random(42)
    rng.shuffle(nongold_pool)
    nongold_sample = [s.statement_id for s in nongold_pool[:500]]
    nongold_empty = set(nongold_sample) - nongold_queries_with_rows
    print(f"  recomputed sample of {len(nongold_sample)}, "
          f"{len(nongold_empty)} empties found", flush=True)

    sweeps = {
        "f2i_gold":    sorted(f2i_empty),
        "f2i_nongold": sorted(nongold_empty),
    }

    audit_rows = []
    for sweep_name, sids in sweeps.items():
        if not sids:
            print(f"\n[{sweep_name}] 0 empties — skipping")
            continue
        print(f"\n[{sweep_name}] {len(sids)} empties — diagnosing...")
        with conn.cursor() as cur:
            cur.execute(_DIAGNOSE_SQL, {
                "sids": sids,
                "slogan_models": ["qwen3-235b"],
                "emb_model": "qwen3-8b",
            })
            cats = []
            for row in cur.fetchall():
                cat = _categorize(row)
                cats.append(cat)
                audit_rows.append({
                    "sweep":          sweep_name,
                    "statement_id":   row[0],
                    "category":       cat,
                    "has_any_slogan": row[1],
                    "has_qwen_slogan": row[2],
                    "has_good_slogan": row[3],
                    "has_insufficient": row[4],
                    "has_target_embedding": row[5],
                    "has_any_embedding": row[6],
                })
        from collections import Counter
        c = Counter(cats)
        for cat, n in c.most_common():
            print(f"  {cat:<26} {n:>4}  {n/len(sids):>6.1%}")

    out = REPO_ROOT / "experiments/nl_fl_matching/data/empty_query_audit.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as fh:
        if audit_rows:
            w = csv.DictWriter(fh, fieldnames=list(audit_rows[0].keys()),
                               quoting=csv.QUOTE_ALL)
            w.writeheader()
            w.writerows(audit_rows)
    print(f"\nwrote {len(audit_rows)} rows → {out.relative_to(REPO_ROOT)}")
    conn.close()


if __name__ == "__main__":
    main()
