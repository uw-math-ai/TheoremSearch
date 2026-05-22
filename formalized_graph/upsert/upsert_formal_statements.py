"""Upsert formal statements (statement + formal_metadata) from the corpus_v2
SQLite DB into RDS.

Each row in SQLite `nodes` becomes one `statement` row (formality='formal',
body=signature, proof=NULL) and one `formal_metadata` row (decl_name=full_name).
The paper is resolved by joining nodes → projects.name → paper.external_id
(source='Lean Repo').

Idempotency key: (paper_id, formal_metadata.decl_name). The schema has no
unique index on that pair, so we pre-fetch existing keys and partition the
ingest into new vs. existing rows in Python.

Run from the TheoremSearch repo root:
    python formalized_graph/tmp/upsert_formal_statements.py
    python formalized_graph/tmp/upsert_formal_statements.py --overwrite
    python formalized_graph/tmp/upsert_formal_statements.py --project Mathlib

Without --overwrite, existing (paper_id, decl_name) pairs are skipped.
With --overwrite, statement.{kind,body} and formal_metadata.{file_path,
module,docstring} are refreshed for those rows. proof is left untouched.
"""

import argparse
import sqlite3
import sys
from pathlib import Path

from tqdm import tqdm

from rds.utils.connect import get_rds_connection
from rds.utils.upsert import insert_rows_returning, update_rows, upsert_rows

DEFAULT_DB = Path("/home/ericleonen/TheoremSearch/formalized_graph/corpus_v3.db")
SOURCE = "Lean Repo"


def _fetch_paper_id_by_slug(conn) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute("SELECT external_id, paper_id FROM paper WHERE source = %s", (SOURCE,))
        return dict(cur.fetchall())


def _fetch_existing_decl_index(conn, paper_ids: list[str]) -> dict[tuple, str]:
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
                        help="Restrict to a single project (e.g. 'Mathlib'). Default: all.")
    parser.add_argument("-o", "--overwrite", action="store_true",
                        help="Refresh kind/body/file_path/module/docstring for existing rows. "
                             "proof is never touched.")
    parser.add_argument("-b", "--batch-size", type=int, default=5000,
                        help="Nodes per insert batch. Default: 5000.")
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

    # Build per-batch fetch query
    where = ""
    params: list = []
    if args.project:
        proj_row = sconn.execute("SELECT id FROM projects WHERE name = ?", (args.project,)).fetchone()
        if proj_row is None:
            sys.exit(f"project '{args.project}' not found in SQLite DB")
        where = "WHERE project_id = ?"
        params = [proj_row["id"]]

    total = sconn.execute(f"SELECT COUNT(*) FROM nodes {where}", params).fetchone()[0]
    print(f"nodes to process: {total:,}")

    # Pre-fetch existing decl index, scoped to the papers we'll touch.
    if args.project:
        scope_paper_ids = [paper_id_by_slug[args.project]] if args.project in paper_id_by_slug else []
    else:
        scope_paper_ids = list(paper_id_by_slug.values())
    existing = _fetch_existing_decl_index(conn, scope_paper_ids)
    print(f"existing formal statements in scope: {len(existing):,}")

    cur_sqlite = sconn.execute(
        f"""
        SELECT project_id, full_name, kind, module, file_path, signature, docstring
          FROM nodes {where}
         ORDER BY id
        """,
        params,
    )

    inserted = updated = skipped = unresolved = 0
    pbar = tqdm(total=total, dynamic_ncols=True)

    while True:
        rows = cur_sqlite.fetchmany(args.batch_size)
        if not rows:
            break

        new_stmt_rows: list[dict] = []
        new_meta_rows: list[dict] = []
        upd_stmt_rows: list[dict] = []
        upd_meta_rows: list[dict] = []

        for n in rows:
            slug = project_slug_by_id.get(n["project_id"])
            paper_id = paper_id_by_slug.get(slug)
            if paper_id is None:
                unresolved += 1
                continue

            decl_name = n["full_name"]
            sid = existing.get((paper_id, decl_name))

            if sid is None:
                new_stmt_rows.append({
                    "paper_id":  paper_id,
                    "formality": "formal",
                    "kind":      n["kind"],
                    "body":      n["signature"],
                    # proof intentionally omitted → NULL
                })
                new_meta_rows.append({
                    "decl_name": decl_name,
                    "file_path": n["file_path"],
                    "module":    n["module"],
                    "docstring": n["docstring"],
                })
            elif args.overwrite:
                upd_stmt_rows.append({
                    "statement_id": sid,
                    "kind":         n["kind"],
                    "body":         n["signature"],
                })
                upd_meta_rows.append({
                    "statement_id": sid,
                    "decl_name":    decl_name,
                    "file_path":    n["file_path"],
                    "module":       n["module"],
                    "docstring":    n["docstring"],
                })
            else:
                skipped += 1

        # Inserts: statement first (to get statement_ids), then formal_metadata.
        # No need to update `existing` — SQLite nodes.full_name is UNIQUE, so
        # each decl_name appears at most once per run.
        if new_stmt_rows:
            statement_ids = insert_rows_returning(
                conn, table="statement", rows=new_stmt_rows, returning="statement_id"
            )
            for sid, meta in zip(statement_ids, new_meta_rows):
                meta["statement_id"] = sid
            upsert_rows(conn, table="formal_metadata", rows=new_meta_rows)
            inserted += len(new_stmt_rows)

        # Updates: keyed by statement_id (PK).
        if upd_stmt_rows:
            update_rows(conn, table="statement",        rows=upd_stmt_rows, where=["statement_id"])
            update_rows(conn, table="formal_metadata",  rows=upd_meta_rows, where=["statement_id"])
            updated += len(upd_stmt_rows)

        conn.commit()
        pbar.update(len(rows))
        pbar.set_postfix(ins=inserted, upd=updated, skip=skipped, unres=unresolved)

    pbar.close()
    sconn.close()
    print(
        f"\nDone."
        f"\n  inserted:   {inserted:,}"
        f"\n  updated:    {updated:,}"
        f"\n  skipped:    {skipped:,}"
        f"\n  unresolved: {unresolved:,}  (project not in RDS paper table)"
    )


if __name__ == "__main__":
    main()
