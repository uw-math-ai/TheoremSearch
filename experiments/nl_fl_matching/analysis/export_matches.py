"""Export ranked matches to a flat JSONL for downstream agents.

Joins nl_fl_match_pilot with statement / paper / slogan / formal_metadata
/ informal_metadata so each row is self-contained — no further DB queries
needed by the consumer.

Each line is one (query, candidate, rank) triple with both sides hydrated.

Usage:
    python -m experiments.nl_fl_matching.analysis.export_matches \\
        --out data/matches.jsonl
    python -m experiments.nl_fl_matching.analysis.export_matches \\
        --rank-max 1 --direction i2f --out data/rank1_i2f.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "rds"))

from utils.connect import get_rds_connection  # noqa: E402
from experiments.nl_fl_matching import gold  # noqa: E402


# One mega-JOIN per side. Heavy SQL but only runs once.
_EXPORT_SQL = """
WITH m AS (
    SELECT *
      FROM nl_fl_match_pilot
     WHERE direction = %(direction)s
       AND embedding_model = %(model)s
       AND ({pool_clause})
       AND rank <= %(rank_max)s
),
q_first_slogan AS (
    SELECT DISTINCT ON (sl.statement_id) sl.statement_id, sl.slogan
      FROM slogan sl
     WHERE sl.statement_id IN (SELECT query_statement_id FROM m)
       AND NOT sl.insufficient_context
     ORDER BY sl.statement_id, sl.created_at
),
c_first_slogan AS (
    SELECT DISTINCT ON (sl.statement_id) sl.statement_id, sl.slogan
      FROM slogan sl
     WHERE sl.statement_id IN (SELECT candidate_statement_id FROM m)
       AND NOT sl.insufficient_context
     ORDER BY sl.statement_id, sl.created_at
)
SELECT
    m.query_statement_id::text     AS q_sid,
    m.candidate_statement_id::text AS c_sid,
    m.rank, m.similarity, m.direction, m.pool_descriptor,

    -- query side
    q_st.formality::text           AS q_formality,
    q_st.kind                      AS q_kind,
    q_st.body                      AS q_body,
    q_pp.source                    AS q_source,
    q_pp.title                     AS q_paper_title,
    q_pp.external_id               AS q_paper_external_id,
    q_pp.url                       AS q_paper_url,
    q_fm.decl_name                 AS q_decl_name,
    q_fm.module                    AS q_module,
    q_fm.file_path                 AS q_file_path,
    q_im.ref                       AS q_ref,
    q_im.lean                      AS q_lean_annotation,
    q_sl.slogan                    AS q_slogan,

    -- candidate side
    c_st.formality::text           AS c_formality,
    c_st.kind                      AS c_kind,
    c_st.body                      AS c_body,
    c_pp.source                    AS c_source,
    c_pp.title                     AS c_paper_title,
    c_pp.external_id               AS c_paper_external_id,
    c_pp.url                       AS c_paper_url,
    c_fm.decl_name                 AS c_decl_name,
    c_fm.module                    AS c_module,
    c_fm.file_path                 AS c_file_path,
    c_im.ref                       AS c_ref,
    c_im.lean                      AS c_lean_annotation,
    c_sl.slogan                    AS c_slogan
  FROM m
  JOIN statement q_st  ON q_st.statement_id = m.query_statement_id
  JOIN paper     q_pp  ON q_pp.paper_id     = q_st.paper_id
  LEFT JOIN formal_metadata   q_fm ON q_fm.statement_id = m.query_statement_id
  LEFT JOIN informal_metadata q_im ON q_im.statement_id = m.query_statement_id
  LEFT JOIN q_first_slogan    q_sl ON q_sl.statement_id = m.query_statement_id
  JOIN statement c_st  ON c_st.statement_id = m.candidate_statement_id
  JOIN paper     c_pp  ON c_pp.paper_id     = c_st.paper_id
  LEFT JOIN formal_metadata   c_fm ON c_fm.statement_id = m.candidate_statement_id
  LEFT JOIN informal_metadata c_im ON c_im.statement_id = m.candidate_statement_id
  LEFT JOIN c_first_slogan    c_sl ON c_sl.statement_id = m.candidate_statement_id
 ORDER BY m.query_statement_id, m.rank
"""


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--direction", choices=("f2i", "i2f", "both"), default="both")
    p.add_argument("--rank-max", type=int, default=10)
    p.add_argument("--embedding-model", default="qwen3-8b")
    p.add_argument("--exclusion", default="statement")
    p.add_argument("--pools", nargs="+",
                   default=["gold_subset_f2i", "gold_subset_i2f"])
    args = p.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)

    conn = get_rds_connection("v2")
    print(f"loading gold pairs for annotation...", flush=True)
    g = gold.load_gold(conn, embedding_model=args.embedding_model)
    print(f"  {len(g.pairs)} gold pairs loaded", flush=True)

    pool_clause = "pool_descriptor = ANY(%(pools)s)"

    directions = ["f2i", "i2f"] if args.direction == "both" else [args.direction]
    total_written = 0
    with args.out.open("w") as fh:
        for direction in directions:
            print(f"exporting {direction}...", flush=True)
            with conn.cursor() as cur:
                cur.execute(
                    _EXPORT_SQL.replace("{pool_clause}", pool_clause),
                    {
                        "direction":       direction,
                        "model":           args.embedding_model,
                        "rank_max":        args.rank_max,
                        "pools":           args.pools,
                    },
                )
                cols = [d.name for d in cur.description]
                n = 0
                while True:
                    batch = cur.fetchmany(500)
                    if not batch:
                        break
                    for row in batch:
                        rec = dict(zip(cols, row))
                        if direction == "f2i":
                            is_gold = (rec["c_sid"], rec["q_sid"]) in g.pairs
                        else:
                            is_gold = (rec["q_sid"], rec["c_sid"]) in g.pairs
                        rec["is_blueprint_gold"] = is_gold
                        fh.write(json.dumps(rec, default=str) + "\n")
                        n += 1
                print(f"  {direction}: {n:,} rows", flush=True)
                total_written += n

    conn.close()
    print(f"\nwrote {total_written:,} rows to {args.out}")


if __name__ == "__main__":
    main()
