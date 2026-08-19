"""Spike (a)+(d): live RDS census that DECIDES experiment parameters. Run FIRST.

  1. formal_dependency edge_type counts — schema.md's census says only {def, proof,
     sig} are populated even though the DDL allows extends/field/docref. If
     extends/field are 0, export GP_EDGE_TYPES=sig (or sig,proof) before any run.
  2. formalization_candidate_neighborhood status counts + column sanity (arm C
     coverage; the SQL in INTEGRATION.md was written from a doc, not run).
  3. embedding model_name counts (qwen3-8b must exist for graph_pack / re-query).
  4. statement.body proof check for 20 theorems (does body carry the proof term? —
     decides whether the proof-length filter in build_tasks works from the DB or
     needs the Mathlib checkout).

    python -m experiments.graph_prover.spikes.edge_census
"""
from __future__ import annotations

from .. import config


def main():
    conn = config.get_rds_conn(statement_timeout_ms=300_000)
    with conn.cursor() as cur:
        print("== formal_dependency edge_type census ==")
        cur.execute("SELECT edge_type, COUNT(*) FROM formal_dependency GROUP BY 1 "
                    "ORDER BY 2 DESC")
        rows = dict(cur.fetchall())
        for et, n in rows.items():
            print(f"  {et:10} {n:>12,}")
        if not rows.get("extends") and not rows.get("field"):
            print("  -> extends/field EMPTY: export GP_EDGE_TYPES=sig,proof "
                  "(arm B fallback, approved plan risk #1)")

        print("\n== formalization_candidate_neighborhood ==")
        cur.execute("SELECT status, COUNT(*) FROM formalization_candidate_neighborhood "
                    "GROUP BY 1")
        for st, n in cur.fetchall():
            print(f"  {st:16} {n:>10,}")
        cur.execute("""SELECT column_name FROM information_schema.columns
                       WHERE table_name = 'formalization_candidate_neighborhood'""")
        cols = sorted(c for (c,) in cur.fetchall())
        print(f"  columns: {cols}")
        need = {"anchor_statement_id", "resolved_decls", "status"}
        missing = need - set(cols)
        if missing:
            print(f"  -> MISSING columns {missing}: fix retrieval/graph_pack.py SQL")

        print("\n== embedding model census ==")
        cur.execute("SELECT model_name, COUNT(*) FROM embedding GROUP BY 1")
        for mn, n in cur.fetchall():
            print(f"  {mn:24} {n:>12,}")

        print("\n== statement.body proof check (20 theorems) ==")
        cur.execute("""SELECT st.body FROM statement st
                       JOIN formal_metadata fm ON fm.statement_id = st.statement_id
                       WHERE st.kind = 'theorem' AND st.body IS NOT NULL LIMIT 20""")
        with_proof = 0
        for (body,) in cur.fetchall():
            from ..scripts.build_tasks import split_proof
            sp = split_proof(body.strip())
            if sp is not None and sp[1] and sp[1] != "sorry":
                with_proof += 1
        print(f"  bodies carrying a proof term: {with_proof}/20")
        if with_proof < 15:
            print("  -> body is statement-only: proof-length filter must read from "
                  "the Mathlib checkout via formal_metadata.file_path (plan spike d)")


if __name__ == "__main__":
    main()
