"""Bulk-insert formal_dependency edges from the corpus SQLite DB into RDS.

For each row in SQLite `edges`, resolves source_id/target_id (integer node ids
local to the SQLite file) to RDS statement_ids, then streams the resolved rows
into formal_dependency via PostgreSQL COPY.

Resolution path: nodes.id → (project_id, full_name) → (paper_id, decl_name)
                          → statement_id (via paper.external_id + formal_metadata.decl_name).

NOT idempotent: writes go straight into formal_dependency with no ON CONFLICT
handling. The target table MUST be empty for the rows being inserted (run
rds/interface/update.sql first to wipe). Re-running over a populated table
will fail with a PK violation.

Run from the TheoremSearch repo root:
    python formalized_graph/tmp/upsert_formal_dependencies.py
    python formalized_graph/tmp/upsert_formal_dependencies.py --project Mathlib
"""

import argparse
import io
import sqlite3
import sys
from pathlib import Path

from tqdm import tqdm

from rds.utils.connect import get_rds_connection

DEFAULT_DB = Path("/home/ericleonen/TheoremSearch/formalized_graph/corpus_v3.db")
SOURCE = "Lean Repo"

_COPY_SQL = "COPY formal_dependency (src_id, dep_id, edge_type) FROM STDIN"


def _fetch_paper_id_by_slug(conn) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute("SELECT external_id, paper_id FROM paper WHERE source = %s", (SOURCE,))
        return dict(cur.fetchall())


def _fetch_statement_id_by_decl(conn, paper_ids: list) -> dict[tuple, str]:
    """Return {(paper_id, decl_name): statement_id} for the given papers."""
    if not paper_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.paper_id, fm.decl_name, s.statement_id
              FROM statement s
              JOIN formal_metadata fm ON fm.statement_id = s.statement_id
             WHERE s.paper_id = ANY(%s::uuid[])
            """,
            ([str(pid) for pid in paper_ids],),
        )
        return {(p, d): sid for p, d, sid in cur.fetchall()}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DEFAULT_DB,
                        help=f"Path to corpus SQLite DB. Default: {DEFAULT_DB.name}")
    parser.add_argument("--project", type=str, default=None,
                        help="Restrict to edges whose SOURCE node is in this project.")
    parser.add_argument("-b", "--batch-size", type=int, default=100_000,
                        help="Edges streamed per COPY chunk. Default: 100,000.")
    args = parser.parse_args()

    if not args.db.exists():
        sys.exit(f"missing: {args.db}")

    conn = get_rds_connection("v2")

    paper_id_by_slug = _fetch_paper_id_by_slug(conn)
    if not paper_id_by_slug:
        sys.exit("No Lean Repo papers in RDS. Run upsert_lean_repos.py first.")
    print(f"resolved {len(paper_id_by_slug)} papers from RDS")

    sconn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    sconn.row_factory = sqlite3.Row

    project_slug_by_id = {
        row["id"]: row["name"]
        for row in sconn.execute("SELECT id, name FROM projects")
    }

    # Build node_id → statement_id by combining SQLite's (project_id, full_name)
    # with RDS's (paper_id, decl_name) → statement_id index.
    print("loading RDS statement index...")
    decl_to_sid = _fetch_statement_id_by_decl(conn, list(paper_id_by_slug.values()))
    print(f"  {len(decl_to_sid):,} formal statements indexed")

    print("building node_id → statement_id map...")
    sid_by_node: dict[int, str] = {}
    unresolved_nodes = 0
    for n in sconn.execute("SELECT id, project_id, full_name FROM nodes"):
        slug = project_slug_by_id.get(n["project_id"])
        paper_id = paper_id_by_slug.get(slug)
        if paper_id is None:
            unresolved_nodes += 1
            continue
        sid = decl_to_sid.get((paper_id, n["full_name"]))
        if sid is None:
            unresolved_nodes += 1
            continue
        sid_by_node[n["id"]] = sid
    print(f"  resolved {len(sid_by_node):,} nodes; {unresolved_nodes:,} unresolved")
    del decl_to_sid  # free ~60MB

    # Optional filter by source-side project.
    where = ""
    params: list = []
    if args.project:
        proj_row = sconn.execute(
            "SELECT id FROM projects WHERE name = ?", (args.project,)
        ).fetchone()
        if proj_row is None:
            sys.exit(f"project '{args.project}' not found in SQLite DB")
        where = "WHERE source_id IN (SELECT id FROM nodes WHERE project_id = ?)"
        params = [proj_row["id"]]

    total = sconn.execute(f"SELECT COUNT(*) FROM edges {where}", params).fetchone()[0]
    print(f"edges to process: {total:,}")

    cur_sqlite = sconn.execute(
        f"SELECT source_id, target_id, edge_type FROM edges {where}",
        params,
    )

    submitted = unresolved_edges = 0
    pbar = tqdm(total=total, dynamic_ncols=True)
    buf = io.StringIO()
    get_sid = sid_by_node.get  # local-name lookup is faster in the hot loop

    with conn.cursor() as cur:
        try:
            while True:
                rows = cur_sqlite.fetchmany(args.batch_size)
                if not rows:
                    break

                buf.seek(0)
                buf.truncate()
                kept = 0
                for e in rows:
                    src = get_sid(e["source_id"])
                    dep = get_sid(e["target_id"])
                    if src is None or dep is None:
                        unresolved_edges += 1
                        continue
                    # TSV: src \t dep \t edge_type \n. No values contain \t or \n
                    # (UUIDs and edge_type ∈ {sig,def,proof,extends,field,docref}),
                    # so no escaping is needed.
                    buf.write(src)
                    buf.write("\t")
                    buf.write(dep)
                    buf.write("\t")
                    buf.write(e["edge_type"])
                    buf.write("\n")
                    kept += 1

                if kept:
                    buf.seek(0)
                    cur.copy_expert(_COPY_SQL, buf)
                    submitted += kept

                pbar.update(len(rows))
                pbar.set_postfix(ins=submitted, unres=unresolved_edges)

            # Single commit at the end amortizes fsync over the whole load.
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    pbar.close()
    sconn.close()
    print(
        f"\nDone."
        f"\n  inserted:    {submitted:,}"
        f"\n  unresolved:  {unresolved_edges:,}  (src or dep node missing in RDS)"
    )


if __name__ == "__main__":
    main()
